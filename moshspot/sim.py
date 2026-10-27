"""Recorded MoshSpot Sim runs: calibrated cameras, venue map, and per-camera frame sources."""

import json
from dataclasses import dataclass
from pathlib import Path

import cv2 as cv
import numpy as np

from moshspot.geometry.camera import Camera
from moshspot.ingest.sources import read_file


def camera_from_gt(entry):
    """A Camera from one `gt.json` camera entry (OpenCV convention, venue metres -> camera)."""
    return Camera(entry["K"], cv.Rodrigues(np.asarray(entry["R"], dtype=float))[0], entry["t"], entry.get("dist"))


@dataclass
class SimRun:
    path: Path
    gt: dict
    fps: float
    cameras: dict  # camera id -> Camera

    @classmethod
    def load(cls, path):
        path = Path(path)
        gt = json.loads((path / "gt.json").read_text())
        return cls(path, gt, float(gt["fps"]), {c["id"]: camera_from_gt(c) for c in gt["cameras"]})

    @property
    def venue(self):
        return self.gt["venue"]

    def frames(self, camera_id, start=0.0, end=None):
        """Frames of one camera; frame k is at t = k / fps seconds of sim time."""
        return read_file(self.path / camera_id / "%06d.jpg", camera_id=camera_id, fps=0,
                         start=start, end=end, source_fps=self.fps)
