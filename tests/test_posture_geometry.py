"""Posture geometry on synthetic people seen by a known camera.

The camera sits 8 m up and looks down across a 40 m floor, like a crowd camera on a truss. People are
placed near (45 degree view), centre, left, right, and far (12 degree view), in each pose and orientation.
"""

import numpy as np
import pytest

from moshspot.geometry.camera import Camera
from moshspot.geometry.posture import Posture, estimate_posture

WIDTH, HEIGHT = 1920, 1080
K = [[1000, 0, WIDTH / 2], [0, 1000, HEIGHT / 2], [0, 0, 1]]
CAMERA = Camera.look_at(K, position=(0, -6, 8), target=(0, 14, 0))
POSITIONS = {"near": (0, 3.5), "centre": (0, 14), "left": (-9, 14), "right": (9, 10), "far": (3, 30)}

# COCO keypoints in body coordinates for a 1.75 m adult: (along body from the feet, left, forward), metres.
STANDING = np.array([
    [1.64, 0.0, 0.09], [1.66, 0.03, 0.07], [1.66, -0.03, 0.07], [1.65, 0.075, 0.0], [1.65, -0.075, 0.0],
    [1.44, 0.19, 0.0], [1.44, -0.19, 0.0], [1.10, 0.22, 0.0], [1.10, -0.22, 0.0], [0.84, 0.22, 0.03],
    [0.84, -0.22, 0.03], [0.93, 0.10, 0.0], [0.93, -0.10, 0.0], [0.51, 0.10, 0.02], [0.51, -0.10, 0.02],
    [0.08, 0.10, 0.0], [0.08, -0.10, 0.0],
])
# Poses with bent joints, as (height above floor, left, forward) in metres.
CROUCHING = np.array([
    [1.10, 0.0, 0.12], [1.12, 0.03, 0.10], [1.12, -0.03, 0.10], [1.10, 0.075, 0.0], [1.10, -0.075, 0.0],
    [0.92, 0.19, 0.05], [0.92, -0.19, 0.05], [0.65, 0.25, 0.25], [0.65, -0.25, 0.25], [0.50, 0.20, 0.40],
    [0.50, -0.20, 0.40], [0.42, 0.12, -0.15], [0.42, -0.12, -0.15], [0.45, 0.18, 0.35], [0.45, -0.18, 0.35],
    [0.07, 0.15, 0.0], [0.07, -0.15, 0.0],
])
SITTING = np.array([  # on the ground, legs stretched out in front
    [0.80, 0.0, 0.08], [0.82, 0.03, 0.06], [0.82, -0.03, 0.06], [0.80, 0.075, 0.0], [0.80, -0.075, 0.0],
    [0.62, 0.19, -0.05], [0.62, -0.19, -0.05], [0.40, 0.22, 0.0], [0.40, -0.22, 0.0], [0.20, 0.25, 0.05],
    [0.20, -0.25, 0.05], [0.12, 0.10, 0.0], [0.12, -0.10, 0.0], [0.15, 0.10, 0.45], [0.15, -0.10, 0.45],
    [0.07, 0.10, 0.90], [0.07, -0.10, 0.90],
])


def heading(position, relative_degrees):
    """Unit floor direction at `relative_degrees` from the direction pointing away from the camera."""
    away = np.asarray(position) - CAMERA.center[:2]
    angle = np.arctan2(away[1], away[0]) + np.radians(relative_degrees)
    return np.array([np.cos(angle), np.sin(angle)])


def place(body, position, direction, lying=False):
    """World points for a body at `position`; `direction` is where the person faces, or where the head
    points when lying (on their back, face up)."""
    forward = np.append(direction, 0.0)
    left = np.array([-direction[1], direction[0], 0.0])
    up = np.array([0.0, 0.0, 1.0])
    base = np.append(position, 0.0)
    if lying:
        return base + np.outer(body[:, 0], forward) + np.outer(body[:, 1], left) + np.outer(0.10 + body[:, 2], up)
    return base + np.outer(body[:, 0], up) + np.outer(body[:, 1], left) + np.outer(body[:, 2], forward)


def observe(points, rng=None, noise=0.0):
    """Project to keypoints (17, 3); optional pixel noise as a fraction of the skeleton's size."""
    pixels = CAMERA.project(points)
    assert (pixels >= 0).all() and (pixels[:, 0] < WIDTH).all() and (pixels[:, 1] < HEIGHT).all(), "out of view"
    if noise:
        pixels = pixels + rng.normal(0, noise * np.ptp(pixels, axis=0).max(), pixels.shape)
    return np.column_stack([pixels, np.ones(len(pixels))])


def test_floor_round_trip():
    points = np.array([[0, 3.5, 0], [-9, 14, 0], [3, 30, 0]], dtype=float)
    np.testing.assert_allclose(CAMERA.to_plane(CAMERA.project(points)), points, atol=1e-6)


def test_height_on_vertical_recovers_height():
    for height in (0.5, 1.2, 1.75):
        pixel = CAMERA.project([[9, 10, height]])[0]
        assert CAMERA.height_on_vertical(pixel, (9, 10)) == pytest.approx(height, abs=1e-6)


@pytest.mark.parametrize("where", POSITIONS)
def test_standing_is_upright_and_located(where):
    position = POSITIONS[where]
    estimate = estimate_posture(observe(place(STANDING, position, heading(position, 180))), CAMERA)
    assert estimate.posture is Posture.UPRIGHT
    assert estimate.head_height == pytest.approx(1.65, abs=0.05)
    np.testing.assert_allclose(estimate.floor_xy, position, atol=0.05)


@pytest.mark.parametrize("where", POSITIONS)
@pytest.mark.parametrize("relative", [90, -90, 45, 135, 180], ids=["across", "across-r", "diagonal", "diag-toward", "toward"])
def test_lying_is_detected(where, relative):
    position = POSITIONS[where]
    estimate = estimate_posture(observe(place(STANDING, position, heading(position, relative), lying=True)), CAMERA)
    assert estimate.posture is Posture.LYING
    assert not estimate.ambiguous
    hips = place(STANDING, position, heading(position, relative), lying=True)[11:13, :2].mean(axis=0)
    # At shallow views a few cm of joint-height error moves the floor point ~0.1-0.2 m (PRD target: 1.5 m).
    np.testing.assert_allclose(estimate.floor_xy, hips, atol=0.3)


@pytest.mark.parametrize("where", POSITIONS)
def test_lying_straight_away_is_never_confidently_upright(where):
    # Head pointing straight away from the camera projects like an upright torso; it must be flagged.
    position = POSITIONS[where]
    estimate = estimate_posture(observe(place(STANDING, position, heading(position, 0), lying=True)), CAMERA)
    assert estimate.posture is not Posture.UPRIGHT or estimate.ambiguous


@pytest.mark.parametrize("where", POSITIONS)
@pytest.mark.parametrize("body", ["crouching", "sitting-across"])
def test_low_postures_are_not_lying(where, body):
    position = POSITIONS[where]
    pose, facing = (CROUCHING, 180) if body == "crouching" else (SITTING, 90)
    estimate = estimate_posture(observe(place(pose, position, heading(position, facing))), CAMERA)
    assert estimate.posture is Posture.LOW


@pytest.mark.parametrize("where", POSITIONS)
def test_standing_with_hidden_feet_is_upright(where):
    position = POSITIONS[where]
    keypoints = observe(place(STANDING, position, heading(position, 180)))
    keypoints[13:, 2] = 0.0  # knees and ankles occluded by the crowd
    estimate = estimate_posture(keypoints, CAMERA)
    assert estimate.posture is Posture.UPRIGHT
    assert np.isnan(estimate.head_height)


def test_robust_to_keypoint_noise():
    rng = np.random.default_rng(0)
    errors = 0
    trials = 0
    for position in POSITIONS.values():
        for _ in range(20):
            standing = estimate_posture(observe(place(STANDING, position, heading(position, 180)), rng, 0.02), CAMERA)
            lying = estimate_posture(observe(place(STANDING, position, heading(position, 90), lying=True), rng, 0.02), CAMERA)
            errors += standing.posture is Posture.LYING
            errors += lying.posture is not Posture.LYING
            trials += 2
    assert errors / trials <= 0.02
