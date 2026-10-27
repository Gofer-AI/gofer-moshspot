"""The live MoshSpot worker: camera streams in, alerts and EMT dispatches out.

One process per camera reads its stream (LiveCamera) and runs perception. The main process tracks people,
fuses cameras into incidents, lets the agent decide, and dispatches through the bridge.

    MOSHSPOT_TOKEN=... uv run python -m moshspot.worker --calibration runs/<any recorded run>/gt.json

The calibration file is any recorded run's gt.json at the same resolution: the cameras are fixed.
"""

import argparse
import json
import logging
import multiprocessing as mp
import os
import queue
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

import cv2 as cv
import numpy as np

from moshspot.decide import CameraTracker, IncidentAgent, RingDetector, SpotEvidence, barricade_shadow
from moshspot.dispatch import Dispatcher
from moshspot.ingest.sources import LiveCamera
from moshspot.perceive import CameraPerception
from moshspot.perception.detect import PersonDetector
from moshspot.perception.pose import PoseEstimator
from moshspot.sim import camera_from_gt
from moshspot.zoom import ZoomInspector

ROOT = Path(__file__).resolve().parent.parent
DETECTOR, POSE = ROOT / "models/yolo26n.onnx", ROOT / "models/yolo26n-pose-dynamic.onnx"
log = logging.getLogger("moshspot.worker")


def camera_process(camera_id, source, source_fps, calibration, fps, threads, results, stop):
    cv.setNumThreads(threads)
    perception = CameraPerception(camera_from_gt(calibration), PersonDetector(DETECTOR, conf_threshold=0.15),
                                  PoseEstimator(POSE))
    with LiveCamera(camera_id, source, fps=fps, buffer_seconds=0, source_fps=source_fps) as camera:
        while not stop.is_set():
            frame = camera.read(timeout=1.0)
            if frame is not None:
                results.put((camera_id, frame.timestamp, perception(frame.image), asdict(camera.health())))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bridge", default="http://127.0.0.1:8780")
    parser.add_argument("--calibration", required=True, help="gt.json of a recorded run (cameras + venue)")
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--replay", help="loop a recorded run (runs/<run>) as live cameras instead of the bridge streams")
    parser.add_argument("--out", default="runs/live", help="directory for alerts.jsonl and traces.jsonl")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    token = os.environ.get("MOSHSPOT_TOKEN")
    gt = json.loads(Path(args.calibration).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    entries = {c["id"]: c for c in gt["cameras"]}
    results, stop = mp.Queue(maxsize=64), mp.Event()
    threads = max(1, (os.cpu_count() or 4) // len(entries))
    suffix = f"?token={token}" if token else ""
    if args.replay:  # always-on demo: the recorded run loops forever at real speed
        replay_fps = json.loads((Path(args.replay) / "gt.json").read_text())["fps"]
        sources = {cid: (str(Path(args.replay) / cid / "%06d.jpg"), replay_fps) for cid in entries}
    else:
        sources = {cid: (f"{args.bridge}/mjpeg/{cid}{suffix}", None) for cid in entries}
    processes = [mp.Process(target=camera_process, daemon=True,
                            args=(cid, *sources[cid], entry, args.fps, threads, results, stop))
                 for cid, entry in entries.items()]
    for process in processes:
        process.start()

    cameras = {cid: camera_from_gt(entry) for cid, entry in entries.items()}
    evidence = SpotEvidence(cameras)
    dispatcher = Dispatcher(args.bridge, gt, token)
    alerts_file = open(out / "alerts.jsonl", "a")

    def snapshot(camera_id, t):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(f"{args.bridge}/snapshot/{camera_id}.jpg", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return cv.imdecode(np.frombuffer(response.read(), np.uint8), cv.IMREAD_COLOR)
        except OSError:
            return None

    def crowd():
        latest = [rows for frames in evidence.frames.values() if frames for rows in [frames[-1][1]]]
        rows = np.vstack(latest) if latest else np.zeros((0, 5))
        return [tuple(r[:2]) for r in rows if r[2] >= 0.9], [tuple(r[:2]) for r in rows if r[2] < 0.45]

    def on_alert(incident, alert):
        log.warning("ALERT %s %s at (%.1f, %.1f) cluster=%s", alert["priority"], incident.id, incident.X, incident.Y,
                    alert["cluster"])
        alerts_file.write(json.dumps(alert) + "\n")
        alerts_file.flush()
        dispatcher.dispatch(incident, *crowd())

    agent = IncidentAgent(evidence, ZoomInspector(cameras, snapshot, PersonDetector(DETECTOR, conf_threshold=0.15),
                                                  PoseEstimator(POSE)), on_alert)
    trackers = {cid: CameraTracker(cid) for cid in entries}
    rings = {cid: RingDetector(cid, barricade_shadow(cameras[cid], gt["venue"])) for cid in entries}
    health, next_poll = {}, 0.0
    log.info("watching %s via %s", ", ".join(entries), args.bridge)
    try:
        while True:
            try:
                camera_id, t, people, health[camera_id] = results.get(timeout=1.0)
            except queue.Empty:
                pass
            else:
                evidence.add(camera_id, t, people)
                for fall in trackers[camera_id].update(t, people):
                    agent.add_fall(fall)
                for centre, helpers, arm_up in rings[camera_id].update(t, people):
                    incident = agent.add_ring(camera_id, t, centre, helpers, arm_up)
                    if len(incident.trace) <= 2:
                        log.info("help ring on %s -> %s at (%.1f, %.1f)", camera_id, incident.id, *centre)
            agent.step(time.time())
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + 1.0
                try:  # a bad bridge response must not take the worker down
                    dispatcher.poll(*crowd())
                    dispatcher.publish(agent.incidents)
                except Exception:
                    log.exception("dispatcher poll/publish failed; retrying next second")
                (out / "traces.jsonl").write_text("".join(json.dumps({"incident": i.id, "state": i.state,
                                                                      "trace": i.trace}) + "\n" for i in agent.incidents))
                (out / "health.json").write_text(json.dumps(health))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for process in processes:
            process.join(timeout=5)


if __name__ == "__main__":
    main()
