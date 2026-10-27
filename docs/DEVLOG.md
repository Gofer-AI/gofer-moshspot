# Dev log

Findings worth keeping for the technical report, newest first.

Unless noted, numbers come from the commands shown, run on a laptop with an Intel i7-13650HX (20 threads). The OpenCV 5 new DNN engine is CPU-only, so the laptop GPU is unused.

---

## 2026-10-26 — The worker meets MoshSpot Sim

Every number below comes from the 3-minute dev run `demo-s7`: 1,500 people, four 1280×720 cameras at 5 fps.

### 1. Recorded runs were mis-timed

- The sim records numbered JPEGs at the run's fps. OpenCV's image-sequence reader assumes 25 fps.
- So `read_file` kept 6 of 30 frames, and 8 s of sim time looked like 1.6 s.
- **Fix:** `read_file(..., source_fps=)` and `LiveCamera(..., source_fps=)` time frames as index ÷ fps. Two regression tests cover it.

### 2. Tiling is required at 1280×720

| Camera | Full frame | Full frame + 2×2 tiles (20% overlap) |
|---|---|---|
| CAM-1 | 0 people | 22 |
| CAM-3 | 26 | 46 |
| CAM-4 | 7 | 35 |

Tiling costs about 115 ms per frame on an idle laptop.

### 3. People who fall vanish

Tracing two collapses frame by frame (`hr` = height ratio):

| Phase | What the detector reports |
|---|---|
| Standing | `hr` 1.1–1.4 |
| During the fall | Drops to about 0.6–0.8 within about 0.8 s |
| On the ground | Gone. Hidden by the crowd, or a dark shape among the helpers |

This matches Chidi's finding from YOLOX-S.

### 4. A fall alone can't be trusted

- A "fast drop" rule fired 927 times in 141 s, mostly people briefly hidden behind someone.
- "Did the same track stand up again?" doesn't separate the cases either: both true falls were "recovered". After a fall, the tracker hands the identity to a neighbour about 0.5 m away.

### 5. The help ring is the signal

- Two to four bystanders crouch around a collapsed person and stay. Two or more low people within 2.4 m, persisting about 3 s, detected both true collapses (16 s and 12 s after they went down).
- Most false rings sat at the same fixed spots from t = 3 s, before anything happened: **static clutter**, learned from each camera's first 20 s.
- Stage-truss cameras look over the barricade at front-row people whose legs it hides, so they read as crouching: the **barricade shadow**.
- With both fixes, unmatched alerts fell from 202 in 141 s to 1 in 180 s.

### 6. One zoomed frame must not dismiss a patient

- Look-closer on a single frame once saw a neighbour "standing" at the centre and closed a real collapse.
- Now the zoom can confirm a closure that the last 2 s of evidence already suggest, or force an alert by finding someone lying. It can't close an incident on its own. A test covers this.

---

## 2026-10-03 — Video ingest (PRD FR-1)

The `moshspot/ingest/` package has three parts:

- **`read_file`:** deterministic reading, for evaluation.
- **`LiveCamera`:** a background reader, for the worker.
- **`RingBuffer`:** look-back for the agent and for incident clips.

There are 11 tests in `tests/test_ingest.py`. The whole suite passed on 5 consecutive runs, so the timing-based tests aren't flaky.

### Design choices

- **Two paths, one `Frame` type.**
  - Evaluation must be reproducible. `read_file` decodes as fast as it can and stamps each frame with its time in the video.
  - The worker runs in real time. `LiveCamera` stamps frames with the wall clock.
  - The detection logic only uses differences between timestamps, so it behaves the same on both paths.
- **The newest frame wins.** If processing falls behind, the consumer skips to the newest frame instead of working through a queue. An alert computed from a 5-second-old backlog is worse than one that skips frames. In the test, a consumer that sleeps 0.5 s still gets a frame less than 0.2 s old.
- **Timestamps come from the stream.**
  - After `grab()`, `CAP_PROP_POS_MSEC` is the grabbed frame's own timestamp (0 for the first frame).
  - Seeking by time is frame-accurate: 500 ms lands on frame 15 of a 30 fps file.
  - Checked on an MJPG AVI, `vtest.avi`, and a UR Fall MP4.
  - This matters because phones often record at a variable frame rate, so frame index ÷ fps would drift.
- **The sampling rate doesn't drift.** A frame is taken when it's due at the target rate, and the next due time steps from the previous one. After a stall it resyncs instead of bursting.
- **Only due frames are decoded.** Streams are drained continuously with `grab()`, so OpenCV's internal buffer never adds latency. Only frames that are due get `retrieve()`d.
- **Reconnects** use exponential backoff from 0.5 s to 30 s. The delay resets to 0.5 s after any connection that delivered frames.
- **Health** reports connected, fps over the last 2 s, frame age, skipped frames, and reconnects. It feeds health monitoring (FR-13).

### Measurements

| Check | Result |
|---|---|
| `vtest.avi` replayed as live at 5 fps, with detect + pose (`tools/camera_check.py --pose`) | 5.0 fps; frames 50–70 ms old; 0 skipped; pipeline about 64 ms per frame with about 4 people. That's slower than the spike's 47 ms because decoding and JPEG encoding now run alongside, and warm-up is included. |
| Stream path, using a file served over local HTTP | Connects, detects the loss, and reconnects with backoff. A finite file ends after about 70 ms of decoding, so it reconnects constantly; a live camera delivers in real time. |
| Ring buffer at 1080p, JPEG quality 90 | 331 KB per frame; 5 ms to encode, 10 ms to decode. 20 s at 5 fps is about 33 MB per camera instead of 622 MB raw. Measured on upscaled footage; real 1080p detail will compress less well. |

**Not yet covered:** a real RTSP camera. The shoots record to files, so RTSP matters only for a live-camera demo. Check it on the Graviton instance before relying on it.

---

## 2026-10-03 — Day-1 spike: OpenCV 5 DNN pose, and posture geometry

**Setup:**

- `opencv-contrib-python` 5.0.0.93 on Python 3.12.
- Models exported with Ultralytics 8.4.172 (`tools/export_models.sh`).
- All inference runs through `cv.dnn.readNetFromONNX(path, cv.dnn.ENGINE_NEW)`, which raises an error rather than silently falling back to the old engine.

### 1. Both pose models load under the new engine

- YOLO26n-pose and YOLOv8n-pose both load. They are ONNX opset 18, using Conv, MatMul, Softmax, Resize, and similar operators.
- One 640×640 forward pass takes about 23 ms.

### 2. Full-frame pose models miss small people

Test clip: OpenCV's `vtest.avi`, 768×576, shot from an elevated camera, with about 6 people each 60–80 px tall. Table entries are people found at confidence 0.25, by model input size:

| Model | 640 | 960 | 1280 |
|---|---|---|---|
| yolo26n / yolov8n (detection) | **6** | 7 / 8 | 6 |
| yolo26n-pose / yolov8n-pose | **0** | 2 / 3 | 6 / 5 |
| yolo26s-pose / yolov8s-pose | 0 | 1 / 3 | 2 / 6 |

Ultralytics' own pipeline, in both PyTorch and ONNX Runtime, gives the same counts. So the problem is the model, not our post-processing. A larger pose model doesn't help. Pose models simply need people roughly twice this size.

### 3. Top-down pose fixes it

The fix:

1. Detect people on the full frame.
2. Cut a square crop around each person, 1.3× the box size.
3. Resize every crop to 256 px.
4. Run all the crops through a dynamic-shape pose model in one batched forward pass.

Results on 200 frames of `vtest.avi`:

| Mode | People/frame | With pose | ms/frame | fps |
|---|---|---|---|---|
| Full-frame pose (640) | 0.5 | — | 30.9 | 32 |
| **Top-down, 256 px crops** | **6.0** | **99%** | 47.1 | **21** |
| Top-down, 320 px crops | 6.0 | 99% | 62.6 | 16 |

```bash
uv run python tools/spike_pose.py --video data/samples/vtest.avi --crop-size 256
```

The cost grows with the number of people, roughly 4 ms per person at 256 px. A dense crowd will need pose to run only for people who matter: those whose box looks short for where they stand, those tracked as low, and periodic samples. Add this to the pipeline design.

### 4. Lying people are detected, but with lower confidence

Test clip: UR Fall clip 01, RGB half (`--roi 320,0,320,240`). Detector confidence:

| Person | Confidence |
|---|---|
| Standing | 0.86 |
| Lying, side view | 0.64 |
| Lying, ceiling view | 0.30–0.40 |

The detector also missed the mid-fall frame, where the person was crouched and motion-blurred.

What to do about it:

- Keep the detection threshold low for people already being tracked.
- Let the tracker bridge short gaps.
- Fine-tune on dev-session frames if recall falls short.

### 5. Posture geometry passes synthetic tests

`uv run pytest tests/test_posture_geometry.py` — 53 tests pass.

**Setup:**

- A camera 8 m up, with views ranging from 45° down (near) to 12° down (far).
- Standing, lying, crouching, and sitting people at 5 floor positions.
- Lying people in 5 orientations relative to the camera.
- With 2% keypoint noise, posture errors stay at or below 2%.

**Results:**

- **Lying across, diagonal, or toward the camera:** always LYING. The floor pin lands within 0.3 m of the hips, against a PRD target of 1.5 m.
- **Lying with the head straight away from the camera (the blind spot):** always LOW + ambiguous, never confidently UPRIGHT.
- **Standing:** always UPRIGHT. At the steep 45° view it's also flagged ambiguous, because a lying reading fits there too.
- **Sitting with legs toward the camera:** LOW, except at 45°, where it looks UPRIGHT. That doesn't matter for alerts.

| Case | Near (45°) | Centre | Far (12°) |
|---|---|---|---|
| Standing | upright, ambiguous | upright | upright |
| Lying straight away | low, ambiguous | low, ambiguous | low, ambiguous |
| Sitting, legs toward camera | upright, ambiguous | low | low |

**Design consequences:**

- Steep cameras benefit most from a second viewpoint (`cross_check_camera`).
- The fall-onset rule must use a burst of fast motion, not only a drop in head height (PRD §7.3).
