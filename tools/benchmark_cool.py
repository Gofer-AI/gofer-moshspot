"""Benchmark the MoshSpot perception pipeline on this machine's OpenCV build: COOL on Graviton vs a baseline.

Times each stage on real frames from a recorded run, records which OpenCV build ran them (KleidiCV/HAL lines
from cv2.getBuildInformation()), and turns the throughput into cameras per instance and $ per camera-hour.
Run it with the same arguments on each configuration you compare (e.g. c8g + COOL, c8g + stock opencv-python,
c7i x86), then compare the JSON files it writes to eval/results/.

    python tools/benchmark_cool.py runs/demo-s7-20261026234005 --frames 60 --price-per-hour 0.159
"""

import argparse
import json
import platform
import time
from pathlib import Path

import cv2 as cv
import numpy as np

from moshspot.perceive import CameraPerception
from moshspot.perception.detect import PersonDetector
from moshspot.perception.pose import PoseEstimator
from moshspot.perception.yolo import letterbox
from moshspot.sim import SimRun

ROOT = Path(__file__).resolve().parent.parent
TARGET_FPS = 5.0  # per camera


def timed(fn, *args):
    started = time.perf_counter()
    result = fn(*args)
    return result, (time.perf_counter() - started) * 1000


def stats(values):
    v = np.array(values[1:] or values)  # the first call includes one-time setup
    return {"mean_ms": round(float(v.mean()), 2), "p50_ms": round(float(np.percentile(v, 50)), 2),
            "p95_ms": round(float(np.percentile(v, 95)), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run")
    parser.add_argument("--camera", default="CAM-3")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--price-per-hour", type=float, help="instance on-demand price plus any software fee, USD")
    parser.add_argument("--label", default=platform.machine())
    args = parser.parse_args()

    run = SimRun.load(args.run)
    paths = sorted((Path(args.run) / args.camera).glob("*.jpg"))[: args.frames]
    detector = PersonDetector(ROOT / "models/yolo26n.onnx", conf_threshold=0.15)
    perception = CameraPerception(run.cameras[args.camera], detector, PoseEstimator(ROOT / "models/yolo26n-pose-dynamic.onnx"))

    stages = {"decode": [], "imgproc": [], "detect_tiled": [], "frame_total": []}
    for path in paths:
        data = np.fromfile(path, np.uint8)
        image, ms = timed(cv.imdecode, data, cv.IMREAD_COLOR)
        stages["decode"].append(ms)

        def imgproc():  # the image operations around the model: letterbox, colour, blur, crop warps
            letterbox(image, 640)
            cv.cvtColor(image, cv.COLOR_BGR2RGB)
            cv.GaussianBlur(image, (0, 0), 3)
            M = np.float32([[2, 0, -300], [0, 2, -200]])
            cv.warpAffine(image, M, (640, 640))
        stages["imgproc"].append(timed(imgproc)[1])
        stages["detect_tiled"].append(timed(detector.detect_tiled, image)[1])
        stages["frame_total"].append(timed(perception, image)[1])

    frame_ms = stats(stages["frame_total"])["mean_ms"] + stats(stages["decode"])["mean_ms"]
    threads = cv.getNumThreads()
    cameras_per_instance = round(1000 / frame_ms / TARGET_FPS, 2)  # one frame at a time, all threads
    build = cv.getBuildInformation()
    result = {
        "label": args.label, "machine": platform.machine(), "processor": platform.processor(),
        "opencv": cv.__version__, "threads": threads, "frames": len(paths), "camera": args.camera,
        "image_size": list(image.shape[1::-1]),
        "stages": {name: stats(values) for name, values in stages.items()},
        "cameras_at_5fps": cameras_per_instance,
        "build_lines": [line.strip() for line in build.splitlines()
                        if any(k in line for k in ("KleidiCV", "HAL", "Version control", "CPU/HW", "Baseline", "Dispatched"))],
    }
    if args.price_per_hour:
        result["usd_per_camera_hour"] = round(args.price_per_hour / max(cameras_per_instance, 1e-6), 4)
    out = ROOT / "eval" / "results" / f"benchmark-{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
