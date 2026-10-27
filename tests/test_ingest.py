"""Ingest: sampling at a target rate, replay-as-live, slow consumers, reconnects, and the ring buffer."""

import time

import cv2 as cv
import numpy as np
import pytest

from moshspot.ingest.frame import Frame
from moshspot.ingest.ring_buffer import RingBuffer
from moshspot.ingest.sources import Cadence, LiveCamera, read_file


def write_video(path, frames, fps=30):
    """Frame k is flat grey at 4k, so tests can tell which frames came back."""
    writer = cv.VideoWriter(str(path), cv.VideoWriter.fourcc(*"MJPG"), fps, (64, 48))
    for k in range(frames):
        writer.write(np.full((48, 64, 3), 4 * k, np.uint8))
    writer.release()
    return path


def index_of(frame):
    return round(frame.image.mean() / 4)


@pytest.fixture(scope="module")
def two_seconds(tmp_path_factory):
    return write_video(tmp_path_factory.mktemp("video") / "two_seconds.avi", 60)


@pytest.fixture(scope="module")
def half_second(tmp_path_factory):
    return write_video(tmp_path_factory.mktemp("video") / "half_second.avi", 15)


def test_cadence_keeps_rate_without_drift():
    cadence = Cadence(5)
    assert [k for k in range(300) if cadence.due(k / 30)] == list(range(0, 300, 6))
    every = Cadence(0)
    assert all(every.due(k / 30) for k in range(10))


def test_cadence_resyncs_after_a_gap():
    cadence = Cadence(5)
    assert cadence.due(0.0) and cadence.due(0.2)
    assert cadence.due(5.0)  # stream stalled for ~5 s
    assert not cadence.due(5.1) and cadence.due(5.2)  # back on a 0.2 s rhythm, no burst


def test_read_file_samples_at_target_rate(two_seconds):
    frames = list(read_file(two_seconds, camera_id="cam", fps=5))
    assert [index_of(f) for f in frames] == list(range(0, 60, 6))
    assert [f.timestamp for f in frames] == pytest.approx([k / 5 for k in range(10)], abs=1e-3)
    assert [f.seq for f in frames] == list(range(10))
    assert {f.camera_id for f in frames} == {"cam"}


def test_read_file_window(two_seconds):
    assert len(list(read_file(two_seconds, fps=0))) == 60
    window = [index_of(f) for f in read_file(two_seconds, fps=10, start=0.5, end=1.01)]
    assert window == [15, 18, 21, 24, 27, 30]


def test_replay_loops_at_real_speed(half_second):
    with LiveCamera("cam", half_second, fps=10) as camera:
        frames = [camera.read(timeout=2) for _ in range(12)]
        health = camera.health()
    assert all(frames)
    assert np.diff([f.timestamp for f in frames]).mean() == pytest.approx(0.1, rel=0.2)
    # Half a second of video at 10 fps: the source time wraps back to 0 every 5 frames.
    assert [round(f.source_time, 2) for f in frames[:7]] == [0.0, 0.1, 0.2, 0.3, 0.4, 0.0, 0.1]
    assert health.connected
    assert health.fps == pytest.approx(10, rel=0.25)
    assert health.last_frame_age < 0.2


def test_slow_consumer_gets_the_newest_frame(half_second):
    with LiveCamera("cam", half_second, fps=20) as camera:
        first = camera.read(timeout=2)
        time.sleep(0.5)
        latest = camera.read(timeout=2)
        age = time.time() - latest.timestamp
        health = camera.health()
    assert latest.seq - first.seq >= 8
    assert age < 0.2  # current, not queued behind older frames
    assert health.skipped >= 7


def test_frames_are_buffered_for_look_back(half_second):
    with LiveCamera("cam", half_second, fps=10, buffer_seconds=0.35) as camera:
        frames = [camera.read(timeout=2) for _ in range(8)]
    buffered = camera.buffer.frames()
    assert [f.seq for f in buffered] == [f.seq for f in frames[-4:]]
    assert [index_of(f) for f in buffered] == [index_of(f) for f in frames[-4:]]


def test_non_looping_file_ends(half_second):
    with LiveCamera("cam", half_second, fps=10, loop=False) as camera:
        frames = list(camera.frames(timeout=2))
    assert [index_of(f) for f in frames] == [0, 3, 6, 9, 12]


def test_missing_source_keeps_retrying_until_stopped(tmp_path):
    camera = LiveCamera("cam", tmp_path / "missing.mp4", reconnect_delay=(0.05, 0.2)).start()
    time.sleep(0.5)
    health = camera.health()
    started = time.monotonic()
    camera.stop()
    assert time.monotonic() - started < 1.0
    assert not health.connected and health.frames == 0 and health.reconnects >= 2
    assert camera.read(timeout=0.1) is None


def test_ring_buffer_keeps_the_last_seconds():
    buffer = RingBuffer(seconds=2.0)
    image = np.zeros((48, 64, 3), np.uint8)
    for seq in range(50):  # 12.25 s at 4 fps
        buffer.push(Frame("cam", seq, seq * 0.25, None, image))
    assert [f.seq for f in buffer.frames()] == list(range(41, 50))
    assert [f.seq for f in buffer.frames(since=11.0, until=11.5)] == [44, 45, 46]
    assert len(buffer) == 9


def test_ring_buffer_round_trips_images_compressed():
    rng = np.random.default_rng(0)
    image = cv.resize(rng.integers(0, 255, (12, 16, 3), dtype=np.uint8), (640, 480), interpolation=cv.INTER_CUBIC)
    buffer = RingBuffer(seconds=1.0, jpeg_quality=90)
    buffer.push(Frame("cam", 0, 0.0, 0.0, image))
    (frame,) = buffer.frames()
    assert frame.image.shape == image.shape
    assert np.abs(frame.image.astype(int) - image).mean() < 2
    assert buffer.nbytes < image.nbytes / 10


@pytest.fixture(scope="module")
def jpeg_sequence(tmp_path_factory):
    """Like a recorded sim run: numbered JPEGs at 5 fps, which OpenCV would otherwise read as 25 fps."""
    folder = tmp_path_factory.mktemp("CAM-1")
    for k in range(15):
        cv.imwrite(str(folder / f"{k:06d}.jpg"), np.full((48, 64, 3), 4 * k, np.uint8))
    return folder / "%06d.jpg"


def test_image_sequence_is_timed_by_frame_index(jpeg_sequence):
    frames = list(read_file(jpeg_sequence, fps=5, source_fps=5))
    assert [index_of(f) for f in frames] == list(range(15))
    assert [f.timestamp for f in frames] == pytest.approx([k / 5 for k in range(15)])
    assert [index_of(f) for f in read_file(jpeg_sequence, fps=0, start=1.0, source_fps=5)][:2] == [5, 6]


def test_image_sequence_replays_at_its_own_speed(jpeg_sequence):
    with LiveCamera("cam", jpeg_sequence, fps=5, source_fps=5) as camera:
        frames = [camera.read(timeout=2) for _ in range(4)]
    assert np.diff([f.timestamp for f in frames]).mean() == pytest.approx(0.2, rel=0.25)
    assert [index_of(f) for f in frames] == [0, 1, 2, 3]
