"""Day-1 spike: run person detection + pose through OpenCV 5 DNN, time each stage, write an overlay video.

Top-down (default) detects people on the full frame, then estimates pose on enlarged crops around them.
Full-frame runs the pose model alone on the whole frame, for comparison.

    uv run python tools/spike_pose.py --video data/samples/vtest.avi
    uv run python tools/spike_pose.py --video data/samples/vtest.avi --mode full --pose models/yolo26n-pose.onnx
    uv run python tools/spike_pose.py --video data/samples/fall-01-cam0.mp4 --roi 320,0,320,240
"""

import argparse
import time
from pathlib import Path

import cv2 as cv
import numpy as np

from moshspot.perception.detect import PersonDetector
from moshspot.perception.pose import PoseEstimator, draw_poses


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", required=True)
    parser.add_argument("--mode", choices=["top-down", "full"], default="top-down")
    parser.add_argument("--detector", default="models/yolo26n.onnx")
    parser.add_argument("--pose", default="models/yolo26n-pose-dynamic.onnx")
    parser.add_argument("--engine", choices=["new", "classic", "auto"], default="new")
    parser.add_argument("--size", type=int, default=640, help="full-frame model input size")
    parser.add_argument("--crop-size", type=int, default=256, help="top-down pose crop size")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--roi", help="crop x,y,w,h before inference, e.g. the RGB half of UR Fall clips")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--threads", type=int, default=0, help="cv.setNumThreads; 0 keeps OpenCV's default")
    parser.add_argument("--out", help="overlay video path (default outputs/spike_<video>_<mode>.mp4)")
    return parser.parse_args()


def summarize(name, times):
    # The first frame includes one-time graph setup, so it's left out of the steady-state numbers.
    steady = np.array(times[1:] or times)
    print(f"{name:<8}{steady.mean():>8.1f}{np.percentile(steady, 50):>8.1f}{np.percentile(steady, 95):>8.1f}")
    return steady


def main():
    args = parse_args()
    if args.threads:
        cv.setNumThreads(args.threads)
    detector = PersonDetector(args.detector, args.size, args.conf, engine=args.engine) if args.mode == "top-down" else None
    estimator = PoseEstimator(args.pose, args.size, args.conf, engine=args.engine, crop_size=args.crop_size)
    cap = cv.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.video}")
    roi = [int(v) for v in args.roi.split(",")] if args.roi else None
    out_path = Path(args.out or f"outputs/spike_{Path(args.video).stem}_{args.mode}.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    stages = {"detect": [], "pose": []}
    people, posed = [], []
    while not args.max_frames or len(people) < args.max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if roi:
            x, y, w, h = roi
            frame = frame[y:y + h, x:x + w].copy()
        t0 = time.perf_counter()
        boxes = detector.detect(frame)[0] if detector else np.zeros((0, 4))
        t1 = time.perf_counter()
        poses = estimator.estimate(frame, boxes) if detector else estimator.detect(frame)
        t2 = time.perf_counter()
        stages["detect"].append((t1 - t0) * 1000)
        stages["pose"].append((t2 - t1) * 1000)
        people.append(len(boxes) if detector else len(poses))
        posed.append(sum(pose is not None for pose in poses))

        for box, pose in zip(boxes, poses):
            if pose is None:  # detected, but no pose found in the crop
                x1, y1, x2, y2 = box.round().astype(int)
                cv.rectangle(frame, (x1, y1), (x2, y2), (160, 160, 160), 1)
        draw_poses(frame, poses)
        if writer is None:
            fps = cap.get(cv.CAP_PROP_FPS) or 10
            writer = cv.VideoWriter(str(out_path), cv.VideoWriter.fourcc(*"mp4v"), fps, frame.shape[1::-1])
        writer.write(frame)
    if writer is None:
        raise SystemExit("no frames read")
    writer.release()

    models = f"{Path(args.detector).name} + {Path(args.pose).name}" if detector else Path(args.pose).name
    print(f"{args.mode} | {models} | engine {args.engine} | threads {cv.getNumThreads()} | frames {len(people)}")
    print(f"first frame (warm-up): {stages['detect'][0] + stages['pose'][0]:.1f} ms")
    print(f"{'stage':<8}{'mean':>8}{'p50':>8}{'p95':>8}   ms, excluding the first frame")
    total = sum(summarize(name, times) for name, times in stages.items() if any(times))
    print(f"{'total':<8}{total.mean():>8.1f}{np.percentile(total, 50):>8.1f}{np.percentile(total, 95):>8.1f}"
          f"   -> {1000 / total.mean():.1f} fps")
    print(f"people per frame: mean {np.mean(people):.1f}, max {max(people)} | "
          f"with pose: {sum(posed)}/{sum(people)} ({100 * sum(posed) / max(sum(people), 1):.0f}%)")
    print(f"overlay: {out_path}")


if __name__ == "__main__":
    main()
