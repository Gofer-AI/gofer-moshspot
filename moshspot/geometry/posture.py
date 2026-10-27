"""Posture in world coordinates from 2D keypoints and a calibrated camera (PRD §7.2).

The torso (hips -> head) drives the decision, because legs are unreliable: seated people stretch them
out, and in a crowd the feet are usually hidden. A torso lying across, diagonal to, or toward the camera
is unambiguous. A torso lying straight away from the camera projects onto the same image line as an
upright one, so that case is flagged `ambiguous` and left to the temporal logic and other cameras.
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np

HEAD = (0, 1, 2, 3, 4)
SHOULDERS = (5, 6)
HIPS = (11, 12)
ANKLES = (15, 16)

LYING_KEYPOINT_HEIGHT = 0.12  # m; joints of a person lying on the floor sit about this high
ANKLE_HEIGHT = 0.07
ANCHOR_HEIGHT = 0.5           # m; hips back-projected here to find the local vertical, standing or lying
TORSO_LYING_LENGTH = (0.35, 1.3)  # m; plausible hip-to-head distance along the floor
UPRIGHT_MAX_ANGLE = 30.0      # degrees between torso and local vertical
LYING_MIN_ANGLE = 45.0
LEGS_VERTICAL_MAX_ANGLE = 25.0
UPRIGHT_MIN_HEAD_HEIGHT = 1.25  # m
BENT_MIN_HIP_HEIGHT = 0.6       # m; hips this high over vertical legs means bending over, not lying


class Posture(str, Enum):
    UPRIGHT = "upright"  # torso vertical, head high (or feet hidden, so height unknown)
    LOW = "low"          # torso vertical with the head low (sitting, crouching), or bending over
    LYING = "lying"      # torso along the floor
    UNKNOWN = "unknown"


@dataclass
class PostureEstimate:
    posture: Posture
    ambiguous: bool             # a lying-on-the-floor reading is also geometrically plausible
    torso_angle: float          # degrees from local vertical: 0 upright, 90 across, 180 head below hips
    head_height: float          # m above the floor, NaN when the feet aren't usable
    torso_floor_length: float   # m between hips and head if both were on the floor
    floor_xy: np.ndarray | None  # where the person is on the venue floor


def estimate_posture(keypoints, camera, min_conf=0.3):
    head = _mean(keypoints, HEAD, min_conf)
    if head is None:
        head = _mean(keypoints, SHOULDERS, min_conf)
    hips = _mean(keypoints, HIPS, min_conf)
    if head is None or hips is None:
        return PostureEstimate(Posture.UNKNOWN, False, np.nan, np.nan, np.nan, None)

    anchor = camera.to_plane([hips], ANCHOR_HEIGHT)[0]
    if np.isnan(anchor).any():
        return PostureEstimate(Posture.UNKNOWN, False, np.nan, np.nan, np.nan, None)
    up = camera.up_direction(anchor[:2])
    torso_angle = _angle(head - hips, up)

    on_floor = camera.to_plane([hips, head], LYING_KEYPOINT_HEIGHT)
    torso_floor_length = float(np.linalg.norm(on_floor[1] - on_floor[0]))
    lying_plausible = TORSO_LYING_LENGTH[0] <= torso_floor_length <= TORSO_LYING_LENGTH[1]

    # Feet are usable when they stand under the hips; then heights above the floor are measurable.
    head_height = hip_height = np.nan
    feet_xy = None
    ankles = _mean(keypoints, ANKLES, min_conf)
    if ankles is not None and _angle(hips - ankles, up) < LEGS_VERTICAL_MAX_ANGLE:
        feet_xy = camera.to_plane([ankles], ANKLE_HEIGHT)[0][:2]
        head_height = camera.height_on_vertical(head, feet_xy)
        hip_height = camera.height_on_vertical(hips, feet_xy)
    bent_over = hip_height >= BENT_MIN_HIP_HEIGHT

    if torso_angle >= 180 - LYING_MIN_ANGLE:  # head below the hips in the image: can't be upright
        posture, ambiguous = Posture.LYING, False
    elif torso_angle >= LYING_MIN_ANGLE:
        if bent_over:
            posture, ambiguous = Posture.LOW, False
        else:
            posture, ambiguous = (Posture.LYING, False) if lying_plausible else (Posture.UNKNOWN, False)
    elif torso_angle < UPRIGHT_MAX_ANGLE:
        low = ankles is not None and (feet_xy is None or head_height < UPRIGHT_MIN_HEAD_HEIGHT)
        posture, ambiguous = (Posture.LOW if low else Posture.UPRIGHT), lying_plausible
    else:  # leaning: between upright and lying
        if lying_plausible and not bent_over:
            posture, ambiguous = Posture.LYING, True
        else:
            posture, ambiguous = Posture.LOW, False

    if posture is Posture.LYING:
        floor_xy = on_floor[0][:2]
    elif feet_xy is not None:
        floor_xy = feet_xy
    else:
        floor_xy = anchor[:2]
    return PostureEstimate(posture, ambiguous, torso_angle, head_height, torso_floor_length, floor_xy)


def _mean(keypoints, indices, min_conf):
    points = keypoints[list(indices)]
    visible = points[points[:, 2] >= min_conf]
    return visible[:, :2].mean(axis=0) if len(visible) else None


def _angle(vector, reference):
    cos = np.dot(vector, reference) / (np.linalg.norm(vector) * np.linalg.norm(reference) + 1e-9)
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))
