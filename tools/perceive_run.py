"""Run perception over a recorded sim run and cache it as RUN/perception/<camera>.jsonl, one line per frame.

Detection is the slow step (about 0.12 s per 1280x720 frame with tiling), so it runs once per run, with one
process per camera. The decision logic then replays the cache in seconds (tools/evaluate_run.py).

    uv run python tools/perceive_run.py runs/eval-s7-20261026234447
"""

import argparse
import json
import os
import time
from multiprocessing import Pool
from pathlib import Path

import cv2 as cv

from moshspot.perceive import CameraPerception
from moshspot.perception.detect import PersonDetector
from moshspot.perception.pose import PoseEstimator
from moshspot.sim import SimRun


def perceive_camera(job):
    run_dir, camera_id, threads, detector_path, pose_path, conf, tiles, out_dir, seconds = job
    cv.setNumThreads(threads)
    run = SimRun.load(run_dir)
    perception = CameraPerception(run.cameras[camera_id], PersonDetector(detector_path, conf_threshold=conf),
                                  PoseEstimator(pose_path), tiles=tiles)
    out = Path(run_dir) / out_dir / f"{camera_id}.jsonl"
    started, frames = time.perf_counter(), 0
    with open(out, "w") as f:
        for frame in run.frames(camera_id, end=seconds):
            f.write(json.dumps({"t": round(frame.timestamp, 3), "people": perception(frame.image)}) + "\n")
            frames += 1
    return camera_id, frames, time.perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", help="recorded run directory (contains gt.json and CAM-n/)")
    parser.add_argument("--detector", default="models/yolo26n.onnx")
    parser.add_argument("--pose", default="models/yolo26n-pose-dynamic.onnx")
    parser.add_argument("--conf", type=float, default=0.15, help="detector confidence threshold")
    parser.add_argument("--tiles", default="2x2", help="detection tile grid, rows x cols (plus the full frame)")
    parser.add_argument("--out-dir", default="perception", help="cache folder inside the run")
    parser.add_argument("--seconds", type=float, help="only the first N seconds of the run")
    args = parser.parse_args()
    run = SimRun.load(args.run)
    (Path(args.run) / args.out_dir).mkdir(exist_ok=True)
    tiles = tuple(int(v) for v in args.tiles.split("x"))
    (Path(args.run) / args.out_dir / "config.json").write_text(json.dumps(
        {"detector": args.detector, "pose": args.pose, "conf": args.conf, "tiles": tiles, "seconds": args.seconds}))
    cameras = sorted(run.cameras)
    threads = max(1, (os.cpu_count() or 4) // len(cameras))
    jobs = [(args.run, camera_id, threads, args.detector, args.pose, args.conf, tiles, args.out_dir, args.seconds)
            for camera_id in cameras]
    with Pool(len(jobs)) as pool:
        for camera_id, frames, seconds in pool.imap_unordered(perceive_camera, jobs):
            print(f"{camera_id}: {frames} frames in {seconds:.0f} s ({1000 * seconds / max(frames, 1):.0f} ms/frame)",
                  flush=True)


if __name__ == "__main__":
    main()
