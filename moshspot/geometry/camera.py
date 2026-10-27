"""Pinhole camera with a known pose relative to the venue floor.

World frame: metres, floor is z = 0, z points up. OpenCV camera frame: x right, y down, z forward.
"""

import cv2 as cv
import numpy as np


class Camera:
    def __init__(self, K, rvec, tvec, dist=None):
        self.K = np.asarray(K, dtype=float)
        self.rvec = np.asarray(rvec, dtype=float).reshape(3)
        self.tvec = np.asarray(tvec, dtype=float).reshape(3)
        self.dist = np.zeros(5) if dist is None else np.asarray(dist, dtype=float)
        self.R = cv.Rodrigues(self.rvec)[0]  # world -> camera
        self.center = -self.R.T @ self.tvec   # camera position in world coordinates

    @classmethod
    def look_at(cls, K, position, target, dist=None):
        """Camera at `position` looking at `target` (world metres), with no roll."""
        position, target = np.asarray(position, dtype=float), np.asarray(target, dtype=float)
        forward = (target - position) / np.linalg.norm(target - position)
        right = np.cross(forward, (0.0, 0.0, 1.0))
        right /= np.linalg.norm(right)
        down = np.cross(forward, right)
        R = np.vstack([right, down, forward])  # rows are the camera axes in world coordinates
        return cls(K, cv.Rodrigues(R)[0], -R @ position, dist)

    def project(self, points):
        """(N, 3) world points -> (N, 2) pixels."""
        pixels, _ = cv.projectPoints(np.asarray(points, dtype=float).reshape(-1, 1, 3),
                                     self.rvec, self.tvec, self.K, self.dist)
        return pixels.reshape(-1, 2)

    def rays(self, pixels):
        """(N, 2) pixels -> (N, 3) unit viewing directions in world coordinates."""
        normalized = cv.undistortPoints(np.asarray(pixels, dtype=float).reshape(-1, 1, 2), self.K, self.dist)
        directions = np.column_stack([normalized.reshape(-1, 2), np.ones(len(normalized))]) @ self.R
        return directions / np.linalg.norm(directions, axis=1, keepdims=True)

    def to_plane(self, pixels, height=0.0):
        """Where each pixel's viewing ray meets the horizontal plane z = height: (N, 2) -> (N, 3).

        Rays that never reach the plane (at or above the horizon) give NaN.
        """
        directions = self.rays(pixels)
        with np.errstate(divide="ignore", invalid="ignore"):
            distance = (height - self.center[2]) / directions[:, 2]
        distance = np.where(distance > 0, distance, np.nan)
        return self.center + distance[:, None] * directions

    def up_direction(self, floor_xy):
        """Unit image vector pointing 'up' at a floor point: the image of a vertical post standing there."""
        base, top = self.project([[floor_xy[0], floor_xy[1], 0.0], [floor_xy[0], floor_xy[1], 1.0]])
        return (top - base) / np.linalg.norm(top - base)

    def height_on_vertical(self, pixel, floor_xy):
        """Height (m) of the point on the vertical line through `floor_xy` that best explains `pixel`.

        This is the closest point between the pixel's viewing ray and that vertical line.
        """
        ray = self.rays([pixel])[0]
        offset = self.center - np.array([floor_xy[0], floor_xy[1], 0.0])
        # Closest points between C + s*ray and F + z*(0, 0, 1); |ray| = 1.
        b = ray[2]
        return (offset[2] - b * (ray @ offset)) / (1.0 - b * b)

    def pixel_height(self, floor_xy, height=1.7):
        """How many pixels tall a vertical object of `height` metres appears at a floor point."""
        base, top = self.project([[floor_xy[0], floor_xy[1], 0.0], [floor_xy[0], floor_xy[1], height]])
        return float(np.linalg.norm(top - base))
