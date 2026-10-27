"""Check a camera source: connect, read at the target rate, and print its health every second.

Works with video files (replayed as live), RTSP/HTTP streams, and webcam indexes. With --pose it also
runs person detection + top-down pose on each frame, like the worker will.

    uv run python tools/camera_check.py data/samples/vtest.avi --pose
    uv run python tools/camera_check.py rtsp://192.168.1.20:8554/cam1 --seconds 30
"""

import argparse
import logging
import time

import cv2 as cv

from moshspot.ingest.sources import LiveCamera


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="video file, rtsp:// or http:// URL, or webcam index")
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--pose", action="store_true", help="run detection + pose on each frame")
    parser.add_argument("--detector", default="models/yolo26n.onnx")
    parser.add_argument("--pose-model", default="models/yolo26n-pose-dynamic.onnx")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    detector = estimator = None
    if args.pose:
        from moshspot.perception.detect import PersonDetector
        from moshspot.perception.pose import PoseEstimator
        detector, estimator = PersonDetector(args.detector), PoseEstimator(args.pose_model)

    deadline = time.monotonic() + args.seconds
    next_report = time.monotonic() + 1.0
    processed, people, busy = 0, 0, 0.0
    frame = None
    with LiveCamera("check", args.source, fps=args.fps) as camera:
        while time.monotonic() < deadline:
            frame = camera.read(timeout=0.5)
            if frame is not None and detector:
                started = time.perf_counter()
                boxes, _ = detector.detect(frame.image)
                estimator.estimate(frame.image, boxes)
                busy += time.perf_counter() - started
                people += len(boxes)
            processed += frame is not None
            if time.monotonic() >= next_report:
                next_report += 1.0
                health = camera.health()
                age = "-" if health.last_frame_age is None else f"{health.last_frame_age:.2f}s"
                line = (f"{'connected' if health.connected else 'DISCONNECTED':<12} fps {health.fps:4.1f}  "
                        f"age {age:>6}  frames {health.frames:>4}  skipped {health.skipped:>3}  "
                        f"reconnects {health.reconnects}  buffer {len(camera.buffer):>3} frames "
                        f"{camera.buffer.nbytes / 1e6:5.1f} MB")
                if detector and processed:
                    line += f"  | people/frame {people / processed:4.1f}  pipeline {1000 * busy / processed:5.1f} ms"
                print(line, flush=True)
        if frame is not None:
            print(f"last frame: {frame.image.shape[1]}x{frame.image.shape[0]}, source time {frame.source_time}")


if __name__ == "__main__":
    cv.utils.logging.setLogLevel(cv.utils.logging.LOG_LEVEL_ERROR)  # LiveCamera logs reconnects itself
    main()
