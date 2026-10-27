"""Per-frame perception for one calibrated camera: who is there, where they stand, how tall they look.

Every person gets a floor position (feet back-projected through the calibration) and a height ratio:
box height over how tall a standing adult appears at that floor point. Standing people measure about
1.0-1.4 (arms up adds height), crouching 0.6-0.9, and a falling person drops below 0.8 within a second.
Only people who look low get the more expensive pose model, which feeds world-coordinate posture and
the "arm raised" signal that bystanders use to call for help.
"""

import numpy as np

from moshspot.geometry.posture import Posture, estimate_posture

STANDING_HEIGHT = 1.8  # m, the sim's adult height; also typical for real crowds
POSE_BELOW = 0.85      # height ratio under which a person gets pose
NOSE, LEFT_WRIST, RIGHT_WRIST = 0, 9, 10


class CameraPerception:
    def __init__(self, camera, detector, pose_estimator=None, tiles=(2, 2)):
        self.camera = camera
        self.detector = detector
        self.pose_estimator = pose_estimator
        self.tiles = tiles

    def __call__(self, image):
        boxes, scores = self.detector.detect_tiled(image, self.tiles)
        return self.describe(image, boxes, scores)

    def describe(self, image, boxes, scores):
        """Floor position, height ratio, and (for low people) posture for each detected box."""
        if not len(boxes):
            return []
        feet = np.column_stack([(boxes[:, 0] + boxes[:, 2]) / 2, boxes[:, 3]])
        floor = self.camera.to_plane(feet)[:, :2]
        on_floor = ~np.isnan(floor).any(axis=1)
        boxes, scores, floor = boxes[on_floor], scores[on_floor], floor[on_floor]
        expected = self._standing_pixels(floor)
        heights = boxes[:, 3] - boxes[:, 1]
        ratios = heights / expected
        people = [{"box": [round(float(v), 1) for v in box], "score": round(float(score), 3),
                   "X": round(float(xy[0]), 2), "Y": round(float(xy[1]), 2),
                   "hr": round(float(ratio), 3), "aspect": round(float((box[2] - box[0]) / max(box[3] - box[1], 1)), 3)}
                  for box, score, xy, ratio in zip(boxes, scores, floor, ratios)]
        if self.pose_estimator is not None:
            low = np.flatnonzero(ratios < POSE_BELOW)
            for index, pose in zip(low, self.pose_estimator.estimate(image, boxes[low])):
                if pose is not None:
                    people[index].update(_pose_signals(pose.keypoints, self.camera))
        return people

    def _standing_pixels(self, floor):
        base = np.column_stack([floor, np.zeros(len(floor))])
        top = base + (0.0, 0.0, STANDING_HEIGHT)
        pixels = self.camera.project(np.vstack([base, top]))
        return np.maximum(np.linalg.norm(pixels[len(floor):] - pixels[:len(floor)], axis=1), 1.0)


def _pose_signals(keypoints, camera):
    estimate = estimate_posture(keypoints, camera)
    head_y = keypoints[NOSE, 1] if keypoints[NOSE, 2] > 0.3 else None
    wrists = [keypoints[i] for i in (LEFT_WRIST, RIGHT_WRIST) if keypoints[i, 2] > 0.3]
    arm_up = head_y is not None and any(w[1] < head_y for w in wrists)
    signals = {"posture": estimate.posture.value, "arm_up": bool(arm_up)}
    if estimate.posture is not Posture.UNKNOWN:
        signals["torso_angle"] = round(estimate.torso_angle, 1)
        signals["ambiguous"] = estimate.ambiguous
    return signals
