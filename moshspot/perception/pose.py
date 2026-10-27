"""Multi-person pose estimation with a YOLO pose model run by the OpenCV 5 DNN engine.

Pose models need people to be roughly 100 px or taller, but people in wide crowd shots are often half
that. `PoseEstimator.estimate` therefore works top-down: it takes person boxes from the detector,
enlarges a square crop around each one, and runs the pose model on the batch of crops. This needs a
model exported with dynamic shapes. `detect` runs the model on the whole frame instead.
"""

from dataclasses import dataclass

import cv2 as cv
import numpy as np

from moshspot.perception.yolo import PAD_VALUE, center_to_corners, iou, letterbox, load_net, nms, to_blob

# COCO keypoint order used by YOLO pose models.
KEYPOINT_NAMES = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)
SKELETON = (
    (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2), (1, 3), (2, 4),
)
CROP_MARGIN = 1.3  # square crop side = longest box side x margin, so lying people fit too


@dataclass
class Pose:
    box: np.ndarray        # (4,) x1, y1, x2, y2 in frame pixels
    score: float
    keypoints: np.ndarray  # (17, 3) x, y, confidence in frame pixels


class PoseEstimator:
    """Ultralytics YOLO pose model (output batch x 56 x anchors)."""

    def __init__(self, model_path, input_size=640, conf_threshold=0.25, nms_threshold=0.45, engine="new",
                 crop_size=256, max_batch=16):
        self.net = load_net(model_path, engine)
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.crop_size = crop_size
        self.max_batch = max_batch

    def infer(self, blob):
        self.net.setInput(blob)
        return self.net.forward()

    def detect(self, frame):
        """Bottom-up: every pose the model finds on the full frame."""
        padded, letterbox_ = letterbox(frame, self.input_size)
        preds = self.infer(to_blob([padded]))[0].T  # (anchors, 56): cx, cy, w, h, score, 17 x (x, y, conf)
        preds = preds[preds[:, 4] > self.conf_threshold]
        if not len(preds):
            return []
        boxes = center_to_corners(preds[:, :4])
        poses = []
        for i in nms(boxes, preds[:, 4], self.conf_threshold, self.nms_threshold):
            keypoints = preds[i, 5:].reshape(17, 3).copy()
            keypoints[:, :2] = letterbox_.to_frame(keypoints[:, :2])
            poses.append(Pose(letterbox_.to_frame(boxes[i].reshape(2, 2)).ravel(), float(preds[i, 4]), keypoints))
        return poses

    def estimate(self, frame, boxes):
        """Top-down: one pose (or None) per person box, from an enlarged crop around it."""
        poses = []
        for start in range(0, len(boxes), self.max_batch):
            poses += self._estimate_batch(frame, np.asarray(boxes[start:start + self.max_batch], dtype=float))
        return poses

    def _estimate_batch(self, frame, boxes):
        size = self.crop_size
        crops, transforms = [], []
        for x1, y1, x2, y2 in boxes:
            side = max(x2 - x1, y2 - y1) * CROP_MARGIN
            scale = size / side
            origin = np.array([(x1 + x2 - side) / 2, (y1 + y2 - side) / 2])
            # warpAffine crops and rescales in one step and pads where the crop leaves the frame.
            M = np.array([[scale, 0, -origin[0] * scale], [0, scale, -origin[1] * scale]], dtype=np.float32)
            crops.append(cv.warpAffine(frame, M, (size, size), flags=cv.INTER_LINEAR,
                                       borderMode=cv.BORDER_CONSTANT, borderValue=PAD_VALUE))
            transforms.append((origin, scale))
        outputs = self.infer(to_blob(crops))
        poses = []
        for box, output, (origin, scale) in zip(boxes, outputs, transforms):
            preds = output.T
            preds = preds[preds[:, 4] > self.conf_threshold]
            if not len(preds):
                poses.append(None)
                continue
            # A crop can contain neighbours; keep the detection that best matches the box we cropped around.
            target = (box - np.tile(origin, 2)) * scale
            overlap = iou(center_to_corners(preds[:, :4]), target)
            best = int(np.argmax(overlap))
            if overlap[best] < 0.3:
                poses.append(None)
                continue
            keypoints = preds[best, 5:].reshape(17, 3).copy()
            keypoints[:, :2] = keypoints[:, :2] / scale + origin
            poses.append(Pose(box, float(preds[best, 4]), keypoints))
        return poses


def draw_poses(frame, poses, keypoint_threshold=0.3):
    for pose in poses:
        if pose is None:
            continue
        x1, y1, x2, y2 = pose.box.round().astype(int)
        cv.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 1)
        cv.putText(frame, f"{pose.score:.2f}", (x1, max(y1 - 4, 10)), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
        points = pose.keypoints[:, :2].round().astype(int)
        visible = pose.keypoints[:, 2] > keypoint_threshold
        for a, b in SKELETON:
            if visible[a] and visible[b]:
                cv.line(frame, tuple(points[a]), tuple(points[b]), (80, 220, 80), 2, cv.LINE_AA)
        for point, is_visible in zip(points, visible):
            if is_visible:
                cv.circle(frame, tuple(point), 3, (255, 255, 255), -1, cv.LINE_AA)
    return frame
