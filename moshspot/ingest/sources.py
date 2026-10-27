"""Camera sources: frames at a target rate from video files, RTSP/HTTP streams, or webcams.

`read_file` is the deterministic path for evaluation. It decodes as fast as it can, and timestamps are
seconds into the video, so the same file always gives the same frames and the same results.

`LiveCamera` is the path the worker uses. A background thread reads the source and keeps only the newest
frame, so a slow consumer skips frames instead of falling behind real time. Files play at real speed and
loop by default ("replay as live" for the demo). Lost streams reconnect with exponential backoff.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2 as cv

from moshspot.ingest.frame import Frame
from moshspot.ingest.ring_buffer import RingBuffer

log = logging.getLogger(__name__)


def redact(source):
    """Source for logs: drop the query string, which may carry the bridge token (?token=...)."""
    return str(source).split("?", 1)[0]

STREAM_TIMEOUT_MS = 5000
CADENCE_TOLERANCE = 1e-3  # s; absorbs float error and small timestamp jitter
HEALTH_WINDOW = 2.0       # s of recent frames used to measure fps


class Cadence:
    """Picks frames at a target rate (0 = every frame) from increasing timestamps, without drifting."""

    def __init__(self, fps):
        self.period = 1.0 / fps if fps else 0.0
        self.next_due = None

    def due(self, t):
        if self.next_due is not None and t < self.next_due - CADENCE_TOLERANCE:
            return False
        # Step from the previous due time so the rate doesn't drift; resync after a gap.
        if self.next_due is None or t - self.next_due >= self.period:
            self.next_due = t + self.period
        else:
            self.next_due += self.period
        return True


def read_file(path, camera_id="file", fps=5.0, start=0.0, end=None, source_fps=None):
    """Frames from a video file at `fps` (0 = every frame) between `start` and `end` seconds.

    `source_fps` times frames as index / source_fps instead of trusting the container. Image
    sequences such as `run/CAM-1/%06d.jpg` need it, because OpenCV assumes 25 fps for them.
    """
    cap = _open(path)
    try:
        index = 0
        if start and source_fps:
            index = round(start * source_fps)
            cap.set(cv.CAP_PROP_POS_FRAMES, index)
        elif start:
            cap.set(cv.CAP_PROP_POS_MSEC, start * 1000)
        cadence = Cadence(fps)
        seq = 0
        while cap.grab():
            t = index / source_fps if source_fps else _position(cap)
            index += 1
            if end is not None and t > end:
                break
            if t < start or not cadence.due(t):
                continue
            ok, image = cap.retrieve()
            if not ok:
                break
            yield Frame(camera_id, seq, t, t, image)
            seq += 1
    finally:
        cap.release()


@dataclass
class CameraHealth:
    camera_id: str
    connected: bool
    fps: float                    # frames published per second, over the last couple of seconds
    last_frame_age: float | None  # seconds since the newest frame, None before the first
    frames: int
    skipped: int                  # frames replaced before the consumer read them
    reconnects: int


class LiveCamera:
    """A camera read on a background thread: RTSP/HTTP stream, webcam index, or video file.

    Every published frame also goes into `buffer`, a ring buffer the agent can look back through.
    `source_fps` times a replayed file by frame index, as read_file does (needed for image sequences).
    """

    def __init__(self, camera_id, source, fps=5.0, buffer_seconds=20.0, loop=True, reconnect_delay=(0.5, 30.0),
                 source_fps=None):
        self.camera_id = camera_id
        self.source = source
        self.fps = fps
        self.loop = loop
        self.source_fps = source_fps
        self.buffer = RingBuffer(buffer_seconds) if buffer_seconds else None
        self._reconnect_delay = reconnect_delay
        self._condition = threading.Condition()
        self._stopping = threading.Event()
        self._finished = threading.Event()
        self._thread = None
        self._latest = None
        self._last_read_seq = -1
        self._seq = 0
        self._connected = False
        self._skipped = 0
        self._reconnects = 0
        self._publish_times = deque(maxlen=512)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name=f"camera-{self.camera_id}", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout=STREAM_TIMEOUT_MS / 1000 + 1):
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def read(self, timeout=None):
        """The newest frame not returned before; waits up to `timeout` s. None on timeout or once finished."""
        with self._condition:
            self._condition.wait_for(lambda: self._has_fresh() or self._finished.is_set(), timeout)
            if not self._has_fresh():
                return None
            self._last_read_seq = self._latest.seq
            return self._latest

    def frames(self, timeout=None):
        """Frames until the camera stops, a non-looping file ends, or `timeout` passes without one."""
        while (frame := self.read(timeout)) is not None:
            yield frame

    def health(self):
        now = time.monotonic()
        with self._condition:
            recent = [t for t in self._publish_times if t >= now - HEALTH_WINDOW]
            last = self._publish_times[-1] if self._publish_times else None
        fps = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 and recent[-1] > recent[0] else 0.0
        return CameraHealth(self.camera_id, self._connected, fps, None if last is None else now - last,
                            self._seq, self._skipped, self._reconnects)

    def _has_fresh(self):
        return self._latest is not None and self._latest.seq > self._last_read_seq

    def _run(self):
        delay = self._reconnect_delay[0]
        try:
            while not self._stopping.is_set():
                frames_before = self._seq
                try:
                    if self._read_source():
                        return  # a non-looping file ended
                except OSError as error:
                    log.warning("camera %s: %s", self.camera_id, error)
                if self._stopping.is_set():
                    return
                self._set_connected(False)
                self._reconnects += 1
                if self._seq > frames_before:
                    delay = self._reconnect_delay[0]  # it was working; retry quickly
                if self._stopping.wait(delay):
                    return
                delay = min(delay * 2, self._reconnect_delay[1])
        finally:
            self._set_connected(False)
            self._finished.set()
            with self._condition:
                self._condition.notify_all()

    def _read_source(self):
        """Read until the source fails or we stop. True when a non-looping file played to the end."""
        return self._replay() if _is_file(self.source) else self._stream()

    def _replay(self):
        """Play a file at real speed, looping if asked."""
        cadence = Cadence(self.fps)
        started = time.monotonic()
        offset = 0.0  # seconds of video played in earlier loops
        while not self._stopping.is_set():
            cap = _open(self.source)
            self._set_connected(True)
            frame_period = 1.0 / (self.source_fps or cap.get(cv.CAP_PROP_FPS) or 30.0)
            duration, index = None, 0
            try:
                while not self._stopping.is_set() and cap.grab():
                    t = index / self.source_fps if self.source_fps else _position(cap)
                    index += 1
                    duration = t + frame_period
                    if not cadence.due(offset + t):
                        continue
                    if self._stopping.wait(max(0.0, started + offset + t - time.monotonic())):
                        break
                    ok, image = cap.retrieve()
                    if ok:
                        self._publish(image, t)
            finally:
                cap.release()
            if duration is None:
                raise OSError(f"no frames in {redact(self.source)}")
            if not self.loop:
                return True
            offset += duration
        return False

    def _stream(self):
        """Read a stream or webcam as fast as it delivers, decoding only the frames that are due."""
        cap = _open(self.source)
        self._set_connected(True)
        cadence = Cadence(self.fps)
        try:
            while not self._stopping.is_set():
                if not cap.grab():
                    raise OSError(f"lost {redact(self.source)}")
                if cadence.due(time.monotonic()):
                    ok, image = cap.retrieve()
                    if ok:
                        self._publish(image, None)
        finally:
            cap.release()
        return False

    def _publish(self, image, source_time):
        frame = Frame(self.camera_id, self._seq, time.time(), source_time, image)
        self._seq += 1
        if self.buffer is not None:
            self.buffer.push(frame)
        with self._condition:
            if self._has_fresh():
                self._skipped += 1
            self._latest = frame
            self._publish_times.append(time.monotonic())
            self._condition.notify_all()

    def _set_connected(self, connected):
        if connected != self._connected:
            log.info("camera %s %s", self.camera_id, "connected" if connected else "disconnected")
        self._connected = connected


def _is_file(source):
    text = str(source)
    return not text.isdigit() and "://" not in text


def _open(source):
    text = str(source)
    if text.isdigit():
        cap = cv.VideoCapture(int(text))
    elif "://" in text:
        cap = cv.VideoCapture(text, cv.CAP_FFMPEG, [cv.CAP_PROP_OPEN_TIMEOUT_MSEC, STREAM_TIMEOUT_MS,
                                                    cv.CAP_PROP_READ_TIMEOUT_MSEC, STREAM_TIMEOUT_MS])
    else:
        cap = cv.VideoCapture(text)
    if not cap.isOpened():
        cap.release()
        raise OSError(f"cannot open {redact(source)}")
    return cap


def _position(cap):
    """Seconds into the video of the frame just grabbed."""
    return cap.get(cv.CAP_PROP_POS_MSEC) / 1000.0
