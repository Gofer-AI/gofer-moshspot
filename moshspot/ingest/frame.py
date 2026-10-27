from dataclasses import dataclass

import numpy as np


@dataclass
class Frame:
    camera_id: str
    seq: int                   # per-camera counter, starting at 0
    timestamp: float           # seconds: wall clock for live cameras, seconds into the video for read_file
    source_time: float | None  # seconds into the source video; None for streams and webcams
    image: np.ndarray          # BGR
