"""In-memory look-back for one camera: the last few seconds of frames, JPEG-compressed, never on disk."""

import threading
from collections import deque
from dataclasses import dataclass

import cv2 as cv
import numpy as np

from moshspot.ingest.frame import Frame


@dataclass
class _Entry:
    camera_id: str
    seq: int
    timestamp: float
    source_time: float | None
    jpeg: np.ndarray


class RingBuffer:
    """The last `seconds` of frames for one camera, for the agent's look-back and incident clips.

    Frames are stored as JPEG: at 5 fps and 1080p, 20 s is 100 frames, about 620 MB raw but tens of MB
    compressed. Raw video never leaves memory (PRD §11).
    """

    def __init__(self, seconds=20.0, jpeg_quality=90):
        self.seconds = seconds
        self._params = [cv.IMWRITE_JPEG_QUALITY, jpeg_quality]
        self._entries = deque()
        self._lock = threading.Lock()

    def push(self, frame):
        ok, jpeg = cv.imencode(".jpg", frame.image, self._params)
        if not ok:
            raise ValueError(f"could not JPEG-encode frame {frame.seq} from camera {frame.camera_id}")
        with self._lock:
            self._entries.append(_Entry(frame.camera_id, frame.seq, frame.timestamp, frame.source_time, jpeg))
            while self._entries[0].timestamp < frame.timestamp - self.seconds:
                self._entries.popleft()

    def frames(self, since=None, until=None):
        """Decoded frames with `since` <= timestamp <= `until`, oldest first."""
        with self._lock:
            entries = [entry for entry in self._entries
                       if (since is None or entry.timestamp >= since) and (until is None or entry.timestamp <= until)]
        return [Frame(e.camera_id, e.seq, e.timestamp, e.source_time, cv.imdecode(e.jpeg, cv.IMREAD_COLOR))
                for e in entries]

    def __len__(self):
        with self._lock:
            return len(self._entries)

    @property
    def nbytes(self):
        with self._lock:
            return sum(entry.jpeg.nbytes for entry in self._entries)
