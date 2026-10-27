"""Shared helpers for Ultralytics YOLO models exported to ONNX and run by the OpenCV 5 DNN engine."""

from dataclasses import dataclass

import cv2 as cv
import numpy as np

ENGINES = {"new": cv.dnn.ENGINE_NEW, "classic": cv.dnn.ENGINE_CLASSIC, "auto": cv.dnn.ENGINE_AUTO}
PAD_VALUE = (114, 114, 114)


def load_net(model_path, engine="new"):
    # ENGINE_NEW raises if the graph engine can't load the model, instead of silently falling back.
    return cv.dnn.readNetFromONNX(str(model_path), ENGINES[engine])


@dataclass
class Letterbox:
    scale: float
    pad_x: int
    pad_y: int

    def to_frame(self, xy):
        """Map (..., 2) points from model-input pixels back to frame pixels."""
        return (np.asarray(xy) - (self.pad_x, self.pad_y)) / self.scale


def letterbox(image, size):
    h, w = image.shape[:2]
    scale = min(size / w, size / h)
    new_w, new_h = round(w * scale), round(h * scale)
    left, top = (size - new_w) // 2, (size - new_h) // 2
    resized = cv.resize(image, (new_w, new_h), interpolation=cv.INTER_LINEAR)
    padded = cv.copyMakeBorder(resized, top, size - new_h - top, left, size - new_w - left,
                               cv.BORDER_CONSTANT, value=PAD_VALUE)
    return padded, Letterbox(scale, left, top)


def to_blob(images):
    return cv.dnn.blobFromImages(images, scalefactor=1 / 255.0, swapRB=True)


def center_to_corners(cxcywh):
    """(N, 4) cx, cy, w, h -> (N, 4) x1, y1, x2, y2."""
    cx, cy, w, h = cxcywh.T
    return np.column_stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])


def nms(boxes, scores, conf_threshold, nms_threshold):
    """Indices kept by OpenCV's NMS for (N, 4) x1, y1, x2, y2 boxes."""
    xywh = np.column_stack([boxes[:, :2], boxes[:, 2:] - boxes[:, :2]])
    keep = cv.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), conf_threshold, nms_threshold)
    return np.asarray(keep, dtype=int).flatten()


def iou(boxes, box):
    """IoU of each (N, 4) x1, y1, x2, y2 box with one box."""
    x1 = np.maximum(boxes[:, 0], box[0])
    y1 = np.maximum(boxes[:, 1], box[1])
    x2 = np.minimum(boxes[:, 2], box[2])
    y2 = np.minimum(boxes[:, 3], box[3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / (area + (box[2] - box[0]) * (box[3] - box[1]) - inter + 1e-9)
