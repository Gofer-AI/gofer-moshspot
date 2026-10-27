# Devpost submission text (paste into the form)

**Project name:** MoshSpot

**Tagline (≤ 200 characters):**
MoshSpot turns a venue's crowd cameras into tireless spotters. It sees someone go down in a dense crowd, checks with an agent, and walks the nearest EMT to them in seconds.

**Special awards to opt into:** Agentic Vision ✅ · Best Use of COOL ✅

---

## Inspiration

At Astroworld 2021, officials first heard "people are going down" at 9:30 pm. Two minutes later, a fan climbed onto a camera platform to beg the operator for help. The show went on for about 40 more minutes, and ten people died of compression asphyxia.

The cameras were already pointed at the crowd. No one was watching them for people going down.

At every big concert, people collapse from heat, drugs, cardiac arrest, or crowd pressure. In a dense, dark, loud crowd they vanish below the crowd line within seconds. For cardiac arrest, each minute without CPR costs about 7–10% survival.

## What it does

MoshSpot watches a venue's fixed crowd cameras with OpenCV 5 and:

1. **Notices a collapse.** It catches a person's height dropping fast, then the bystanders who crouch around them and stay. That second signal still works when the person themself is hidden by the crowd.
2. **Lets an agent verify it.** The agent checks whether anyone is standing at the spot, looks closer at the real pixels with a zoomed re-detection, and waits long enough for someone who stumbled to get back up. It closes or alerts, and logs every step.
3. **Pins the person on the venue map**, in metres, from calibrated cameras.
4. **Dispatches the EMT team with the shortest walking time through the crowd** (Dijkstra over the tracked crowd), and escalates if nobody accepts within 45 s.
5. **Flags clusters.** Several people down close together raises a "possible crowd crush" alarm.

We test it end to end in **MoshSpot Sim**, our seeded concert simulator: 1,500 people, four CCTV cameras, scripted collapses and look-alikes, and simulated EMT teams. The sim dispatches teams that walk to the patient, so the loop is closed.

## How we built it

- **OpenCV 5 DNN, new engine (`ENGINE_NEW`):**
  - YOLO26n person detection on the full frame plus 2×2 tiles. Tiling took us from 0–26 to 22–46 people per frame.
  - Top-down YOLO26n-pose on enlarged crops cut with `cv.warpAffine`. Pose models miss people under ~100 px; this lifted pose coverage from 0.5 to 6.0 people per frame.
- **Calibrated geometry:**
  - `cv.projectPoints`, `cv.undistortPoints`, and `cv.Rodrigues` give every detection a floor position and a height ratio (how tall it looks versus a standing adult at that spot).
  - Posture comes from the torso axis in world coordinates.
- **Decision logic:**
  - fall candidates from a tracker (Hungarian assignment on floor distance);
  - a help-ring detector, with a static-clutter mask learned in each camera's first 20 s and barricade "shadows" for stage cameras;
  - an incident agent with tools (`spot_evidence`, `look_closer`, `rank_teams`, `dispatch_team`, `escalate`) and guardrails in code.
- **Ingest:** reads RTSP, MJPEG, files, and image sequences. Newest frame wins, so no lag builds up; streams reconnect; frames are kept in a RAM-only JPEG ring buffer.
- **AWS:** one Graviton4 `c8g` instance from the COOL AMI (OpenCV 5) runs the worker and the bridge under hardened systemd, behind Caddy HTTPS. `tools/benchmark_cool.py` measures COOL against stock OpenCV and x86.
- **Evaluation:** recorded sim runs, perception cached once, decisions replayed and scored with `score.py`. We tuned on one run and report on held-out runs.

## Challenges we ran into

- **People who fall disappear.** Once someone is on the ground, the detector rarely sees them; they're hidden by standing people. Worse, the tracker hands their identity to a neighbour, so "did they get up?" can't come from the track. We switched to reasoning about the *reaction around the spot*: the help ring.
- **False alarms.** A naive "fast drop" rule fired 927 times in 141 s, mostly people briefly hidden behind others. Static clutter and the barricade shadow took the dev run from 202 unmatched alerts to 1.
- **One zoomed frame isn't evidence.** Early on, a single zoomed frame saw a neighbour "standing" and closed a real collapse. Now the zoom can confirm or overturn, but it can't dismiss a patient on its own.
- **Timing bugs.** OpenCV reads image sequences at an assumed 25 fps, so our first replays ran 5× too fast.

## Accomplishments that we're proud of

- A closed loop from pixels to an EMT walking to the patient, with an auditable trace for every decision.
- Honest evaluation on held-out seeded runs, using the simulator's exact ground truth.
- Almost everything runs on CPU through OpenCV 5's new engine, which is why it fits on a Graviton box.

## What we learned

- In crowds, the bystanders are a better sensor than the patient.
- Calibration beats pixels: "how tall should a person look *here*" makes falls measurable.
- Agents need guardrails in code, not prompts. Ours can't close an incident without persistent visual evidence.

## What's next

- Thermal and PTZ cameras.
- Retraining the detector on staged real-world footage.
- A crowd-density and pressure layer for crush risk.
- An EMT phone app with web push.
- Pilots with event medical teams.

## Built with

OpenCV 5 (DNN ENGINE_NEW, calib, imgproc) · Python · NumPy · SciPy · Ultralytics YOLO26n / YOLO26n-pose (ONNX) · Three.js · AWS EC2 Graviton4 (c8g) · COOL (Cloud-Optimized OpenCV Library) · Caddy · systemd · uv
