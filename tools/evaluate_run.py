"""Replay a recorded run's cached perception through the decision logic, then score it against ground truth.

Writes RUN/alerts.jsonl (what score.py reads) and RUN/traces.jsonl (one agent trace per incident), then runs
score.py. Run tools/perceive_run.py on the run first.

    uv run python tools/evaluate_run.py runs/eval-s7-20261026234447
    uv run python tools/evaluate_run.py runs/eval-s7-20261026234447 --no-look-closer   # ablation
"""

import argparse
import json
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import cv2 as cv

from moshspot.decide import CameraTracker, IncidentAgent, RingDetector, SpotEvidence, barricade_shadow
from moshspot.perception.detect import PersonDetector
from moshspot.perception.pose import PoseEstimator
from moshspot.sim import SimRun
from moshspot.zoom import ZoomInspector

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run")
    parser.add_argument("--no-look-closer", action="store_true", help="ablation: decide on cached evidence only")
    parser.add_argument("--zoom-dispatch", action="store_true", help="ablation: zoom-opened incidents dispatch instead of going to review")
    parser.add_argument("--out", default="alerts.jsonl", help="alerts file name inside the run directory")
    parser.add_argument("--perception", default="perception", help="perception cache folder inside the run")
    args = parser.parse_args()
    run = SimRun.load(args.run)
    run_dir = Path(args.run)

    look_closer = None
    if not args.no_look_closer:
        def frame_source(camera_id, t):
            return cv.imread(str(run_dir / camera_id / f"{round(t * run.fps):06d}.jpg"))
        look_closer = ZoomInspector(run.cameras, frame_source, PersonDetector(ROOT / "models/yolo26n.onnx", conf_threshold=0.15),
                                    PoseEstimator(ROOT / "models/yolo26n-pose-dynamic.onnx"))

    evidence = SpotEvidence(run.cameras)
    agent = IncidentAgent(evidence, look_closer, dispatch_zoom=args.zoom_dispatch)
    trackers = {cid: CameraTracker(cid) for cid in run.cameras}
    rings = {cid: RingDetector(cid, barricade_shadow(cam, run.venue)) for cid, cam in run.cameras.items()}
    alerts = []
    with ExitStack() as stack:
        caches = {cid: stack.enter_context(open(run_dir / args.perception / f"{cid}.jsonl")) for cid in sorted(run.cameras)}
        for lines in zip(*caches.values()):
            frames = {cid: json.loads(line) for cid, line in zip(caches, lines)}
            t = next(iter(frames.values()))["t"]
            for cid, frame in frames.items():
                evidence.add(cid, t, frame["people"])
                for fall in trackers[cid].update(t, frame["people"]):
                    agent.add_fall(fall)
                for ring in rings[cid].update(t, frame["people"]):
                    agent.add_ring(cid, t, *ring)
            alerts += agent.step(t)

    (run_dir / args.out).write_text("".join(json.dumps(a) + "\n" for a in alerts))
    with open(run_dir / args.out.replace("alerts", "traces"), "w") as f:
        for inc in agent.incidents:
            f.write(json.dumps({"incident": inc.id, "state": inc.state, "X": round(inc.X, 2),
                                "Y": round(inc.Y, 2), "cameras": sorted(inc.cameras), "trace": inc.trace}) + "\n")
    states = [inc.state for inc in agent.incidents]
    print(f"{len(agent.incidents)} incidents: {states.count('alerted')} alerted, {states.count('review')} sent to review, "
          f"{states.count('closed')} closed, {states.count('watching')} undecided at the end of the run; {agent.zooms} zoomed looks")
    subprocess.run([sys.executable, str(ROOT / "score.py"), str(run_dir / "gt.json"), str(run_dir / args.out)], check=True)


if __name__ == "__main__":
    main()
