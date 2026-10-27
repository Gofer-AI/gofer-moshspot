"""The agent's look-closer tool: re-run detection and pose on a zoomed crop of the real frame around a spot.

The always-on pass sees distant people at about 1x. Zooming a 3 m area around the spot up to the model's
640 px input shows the same pixels at 3-8x, where a person lying behind others is often found after all.
"""

import cv2 as cv
import numpy as np

from moshspot.perceive import STANDING_HEIGHT, CameraPerception
from moshspot.perception.yolo import PAD_VALUE

ZOOM_INPUT = 640
CROP_HEIGHTS = 3.0  # crop side, in standing-person heights at the spot


class ZoomInspector:
    def __init__(self, cameras, frame_source, detector, pose_estimator=None):
        self.cameras = cameras
        self.frame_source = frame_source  # (camera_id, t) -> BGR image or None
        self.detector = detector
        self.perception = {cid: CameraPerception(camera, detector, pose_estimator) for cid, camera in cameras.items()}

    def __call__(self, camera_id, X, Y, t):
        image = self.frame_source(camera_id, t)
        if image is None:
            return None
        camera = self.cameras[camera_id]
        feet = camera.project([[X, Y, 0.0]])[0]
        side = CROP_HEIGHTS * camera.pixel_height((X, Y), STANDING_HEIGHT)
        scale = ZOOM_INPUT / side
        origin = np.array([feet[0] - side / 2, feet[1] - 0.6 * side])
        M = np.array([[scale, 0, -origin[0] * scale], [0, scale, -origin[1] * scale]], dtype=np.float32)
        crop = cv.warpAffine(image, M, (ZOOM_INPUT, ZOOM_INPUT), flags=cv.INTER_LINEAR,
                             borderMode=cv.BORDER_CONSTANT, borderValue=PAD_VALUE)
        boxes, scores = self.detector.detect(crop)
        boxes = boxes / scale + np.tile(origin, 2) if len(boxes) else boxes
        people = self.perception[camera_id].describe(image, boxes, scores)
        d = {id(p): np.hypot(p["X"] - X, p["Y"] - Y) for p in people}
        near = [p for p in people if d[id(p)] < 1.0]
        around = [p for p in people if 0.5 <= d[id(p)] <= 1.8 and 0.35 < p["hr"] < 0.85 and p["aspect"] < 1.3]
        return {
            "zoom": round(scale, 1),
            "people_within_1m": len(near),
            "standing": any(p["hr"] >= 0.9 and d[id(p)] < 0.35 for p in near),
            "sitting": any(0.4 <= p["hr"] < 0.9 and p["aspect"] < 1.1 and d[id(p)] < 0.5 for p in near),
            "lying": any(p["hr"] < 0.35 or p["aspect"] >= 1.3 or p.get("posture") == "lying" for p in near),
            "crouching_around": len(around),
        }
