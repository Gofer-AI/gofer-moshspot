# MoshSpot — Gofer AI

**MoshSpot** turns existing crowd cameras at concerts and festivals into tireless spotters:

1. It detects a person who collapses.
2. It recognises the bystanders gathering around them.
3. An agent verifies the event.
4. It pins the person on the venue map.
5. It dispatches the EMT team with the shortest walking time.

It's Gofer AI's entry to the [OpenCV AI Competition 2026](https://opencv26.devpost.com). Every vision step runs on **OpenCV 5** (the new DNN engine and calibration geometry), on **AWS Graviton with COOL**.

| | |
|---|---|
| **Technical report** (architecture, OpenCV 5 implementation, agent, AWS, evaluation, limitations) | [docs/REPORT.md](docs/REPORT.md) |
| Problem statement and PRD | [docs/PRD.md](docs/PRD.md) |
| Dev log: measured findings | [docs/DEVLOG.md](docs/DEVLOG.md) |
| Deploying to AWS Graviton + COOL | [DEPLOY.md](DEPLOY.md) |

The repo has two halves:

- **`moshspot/`** is the worker that watches the cameras and dispatches. Its pieces:
  - ingest;
  - perception (tiled YOLO26n detection and top-down pose via `cv.dnn` ENGINE_NEW);
  - calibrated geometry;
  - help-ring and fall logic;
  - the incident agent;
  - the dispatcher.
- **`web/` + `bridge.py` + `score.py`** form **MoshSpot Sim**: a seeded concert simulator with exact ground truth. The worker is evaluated against it, and it closes the loop: dispatched EMT teams walk to the patient.

### Run the worker (laptop)

You need [uv](https://docs.astral.sh/uv/), which installs Python 3.12. Install the pinned dependencies, including OpenCV 5.0.0, then export the YOLO ONNX models in a throwaway environment:

```bash
uv sync --locked --extra local
bash tools/export_models.sh
```

**Score a recorded run.** Start `python3 bridge.py --record`, open http://localhost:8780, choose **Eval** and a seed, and click **Record run**. Then cache detection and pose once per run:

```bash
uv run python tools/perceive_run.py runs/<run>
```

Run the decision logic, which writes `alerts.jsonl` and `traces.jsonl` and then runs `score.py`:

```bash
uv run python tools/evaluate_run.py runs/<run>
```

**Live closed loop.** With the sim open in a browser, MoshSpot watches the four MJPEG camera streams and dispatches through the bridge, and the EMT teams walk to the patient:

```bash
uv run python -m moshspot.worker --calibration runs/<run>/gt.json
```

**Tests:**

```bash
uv run pytest
```

---

# MoshSpot Sim — the test rig

A lightweight browser simulation of a concert: a venue layout, a crowd of up to 3,000 people, and 4 fixed CCTV-style cameras. Its frames go straight into the MoshSpot worker, and it writes exact ground truth for the evaluation harness. No build step and no GPU. Three.js comes from a CDN, and the bridge uses only the Python standard library.

```bash
python3 bridge.py --record   # → http://localhost:8780  (PORT env var to change; --record allows saving runs)
```
Requires Python 3.9+ and a browser with WebGL. No `pip install` needed.

| Platform | Run | Notes |
|---|---|---|
| macOS (Apple Silicon or Intel) | `python3 bridge.py` | On Intel Macs with integrated graphics, if the fps pill drops below about 30, use 960×540 tiles or a crowd of about 1,000. Recorded runs are deterministic at any fps; a slower machine just takes longer to record. |
| Windows 10/11 | `py bridge.py` (or `python bridge.py`) | Different port: `$env:PORT=8781; py bridge.py` in PowerShell. Use Chrome or Edge. Recorded frames go to `runs\<run>\CAM-1\%06d.jpg`, which `cv.VideoCapture` reads the same way. |
| Linux | `python3 bridge.py` | Any desktop browser with WebGL. |

## What it simulates

| | |
|---|---|
| **Venue** | Stage, barricade, pit L/R, GA mid/back, FOH tent, 4 EMT posts, 10 floor calibration markers |
| **Cameras** | CAM-1/2 on the stage trusses, CAM-3 on the FOH tower, CAM-4 on the delay tower. Fixed, 640×360 to 1280×720, with a CCTV timestamp overlay. There are deliberate blind spots (back-right) |
| **Crowd** | Denser toward the stage. People dance (arms up, jump on the beat), walkers circulate, and everyone keeps personal space. Drawn with 10 instanced meshes, so 1,500 people at 720p run at 60 fps on a MacBook |
| **Conditions** | House lights, haze, strobe, moving colored stage lights |

### Incidents (ground truth)

| Type | What happens | Should MoshSpot alert? |
|---|---|---|
| `collapse` | Knees buckle, then a 0.9–1.4 s gravity fall to back / front / side, then motionless. After 3–9 s, 2–4 bystanders form a **help ring** (crouch, one waves) | ✅ HIGH |
| `lie_down` | Slow crouch → sit → lie over about 6 s (**no observed fall**), then motionless | ✅ MEDIUM (MoshSpot's 20 s immobility path) |
| `crush_collapse` + `crush_cluster` | Crowd surge: the pit compresses toward the barricade, then 3–5 people go down within 3.5 m. No help ring | ✅ HIGH + cluster escalation |
| `collapse_recover` | Falls, stirs at 2–3 s, sits up at about 5–6 s, stands | ❌ distractor (must not dispatch; tests the 8 s immobility window) |
| `sit` | Sits on the floor for 1–3 min (height ratio about 0.5, slow) | ❌ distractor |
| `crouch` | Crouches for 4–12 s, then stands | ❌ distractor |

Trigger incidents by clicking a camera tile or the map, with the buttons, or through a scenario:

- **Demo:** a 3-minute story.
- **Eval:** 10 minutes. 11 positives (6 collapse, 2 lie-down, 3 collapse-recover) plus 16 distractors, at random seeded times; about 10% are outside camera coverage.
- **Crush:** a 2-minute crowd surge.
- **False-positive soak:** 10 minutes of sits and crouches only.

## Feeding MoshSpot

**Live** (the bridge re-streams frames as MJPEG, and OpenCV opens it like a camera):
```python
cap = cv.VideoCapture("http://localhost:8780/mjpeg/CAM-1")   # CAM-1..CAM-4, at the sim's fps (default 5)
```

**Recorded run** (deterministic, faster than real time; 180 s of sim records in about 30 s). Choose a scenario and seed, then click **Record run** (the bridge must be started with `--record`; it's off by default):
```
runs/<run>/CAM-1/000000.jpg …     cv.VideoCapture("runs/<run>/CAM-1/%06d.jpg")   # frame k ↔ t = k / fps
runs/<run>/gt.json                calibration, venue map, incidents
runs/<run>/gt_frames.jsonl        per frame: every non-upright person, with bbox + COCO-17 keypoints per camera + height_ratio
```

### `gt.json`
- `cameras[]`: OpenCV-convention `K`, `dist` (zeros), `R`, `t` (venue → camera), `H_floor_to_image`, and `markers_px` (pixel positions of the visible floor markers). Use them to **check MoshSpot's ChArUco + solvePnP calibration tool** (turn on "calibration view" to hide the crowd), or to skip calibration entirely.
- `venue`: zones (polygons), EMT posts, obstacles, markers, in venue metres (X right facing the stage, Y toward the stage, Z up).
- `incidents[]`: `type`, `should_alert`, `expected_priority`, `t_onset` (fall starts), `t_down` (on the ground), `t_recover`, `X/Y`, `zone`, `nearest_emt`, `visible_in` (cameras that can see the person), and `helpers`.

### Scoring
Have the worker write one line per alert to `alerts.jsonl`: `{"t": 41.2, "X": -6.3, "Y": 40.1, "priority": "HIGH"}`, where `t` is sim seconds. Then run:
```bash
python3 score.py runs/<run>/gt.json alerts.jsonl
```
It reports recall (overall and on covered incidents only), distractor false alarms, unmatched alerts per hour, time-to-alert after `t_down`, and priority accuracy.

## Closing the loop: dispatch → EMTs walk to the patient

Each EMT post has a 2-person team in hi-vis vests. When MoshSpot dispatches, the team walks to the patient: the crowd parts for them, and they route around the FOH tent. They kneel beside the patient. On resolve, they help the patient up, walk them back to the post, and the patient leaves the floor. This is the shot for the demo video.

```bash
# MoshSpot worker / dispatcher → sim
curl -X POST localhost:8780/dispatch -d '{"action":"dispatch","team":"EMT-1","X":-6.2,"Y":40.1,"incident_id":"ms-42"}'
curl -X POST localhost:8780/dispatch -d '{"action":"accept","incident_id":"ms-42"}'    # from the EMT PWA "Accept" button
curl -X POST localhost:8780/dispatch -d '{"action":"resolve","incident_id":"ms-42"}'   # or false_alarm / cancel
# sim → MoshSpot (poll; pass after=<last> for new events only)
curl localhost:8780/emt?after=0
```

| | |
|---|---|
| `action` | `dispatch` (needs `X`, `Y` in venue metres; leave out `team` to get the nearest free team), `accept`, `resolve`, `false_alarm`, `cancel` (for `cancel`, escalate, then re-dispatch to the next team) |
| Team status events | `dispatched` → `accepted` → `en_route` (with `eta_s`) → `on_scene` (with `response_s`) → `resolved` / `false_alarm` / `cancelled` → `available`. Also `rejected` (busy or unknown team) |
| **Accept** setting (UI) | auto after 2 / 5 / 15 s, **on MoshSpot `accept`** (the EMT phone app's Accept button drives it), or **never**, which tests the 45–60 s ack timer and escalation to the next team |
| Ground truth | `gt.json` gets `dispatches[]` (team, MoshSpot's `incident_id`, the matched sim incident, accept / arrive / resolve times, outcome, `response_s`) and `emt_events[]`. `score.py` prints down → EMT-on-scene time |

**Which team goes:** if the dispatch leaves out `team`, the sim runs **Dijkstra** from the patient over a 0.5 m floor grid (121×98 cells, 8-connected, about 3–5 ms). Each cell's cost is the walking time through it: 1.5 m/s in the clear, slower as crowd density rises, a wall at the FOH tent, and a steep cost for stepping over someone on the ground. One search gives every team's real walking time, and the fastest **free** team goes, along that shortest path. The team re-plans when it accepts, because the crowd has moved. The `dispatched` event includes the full `ranking` (each team's `eta_s` and `straight_m`) and `chosen_by: "dijkstra"`. If MoshSpot names a `team`, the sim obeys it (`chosen_by: "moshspot"`). With 3,000 people, Dijkstra picks a different team than straight-line in about 5% of floor positions: the dense pit, and the area behind the FOH tent.

### Same pick inside MoshSpot: `emt_router.py`
Copy `emt_router.py` (standard library only) into the MoshSpot dispatcher so it makes the same choice as the sim:
```python
from emt_router import EmtRouter
router = EmtRouter.from_venue_json("moshspot-venue.json")   # the sim's "Download venue JSON", or gt.json
best = router.pick(x, y,                                      # patient, venue metres
                   people=[(t.X, t.Y) for t in tracks if t.posture != "lying"],
                   lying=[(t.X, t.Y) for t in tracks if t.posture == "lying"],
                   busy={"EMT-2"})                            # teams already on a job
# best.team, best.eta_s, best.path  →  POST /dispatch {"team": best.team, ...}
ranking = router.rank(x, y, ...)   # every team, fastest first, for the escalation order and the agent trace
```
It's the same grid, cost model and rounding as the sim. `tests/test_emt_router.py` checks it against a crowd snapshot exported from the sim: walking times agree to within 2 µs, and it picks the same team at all 7 test points. Each query takes about 15 ms in pure Python. Pass the people MoshSpot is tracking (floor X/Y) to get crowd-aware times; with no people, it's plain walking distance around obstacles. CLI: `python3 emt_router.py moshspot-venue.json 4 38 --busy EMT-3`. Tests: `python3 -m unittest discover -s tests`.

Coordinates: `X`/`Y` are the venue floor metres MoshSpot already computes from the homography (they match `gt.json`). The sim assigns the dispatch to the person on the ground nearest that point, within 4 m. If no one is there, the team still walks out and reports `patient_found: false`.

## What we learned testing it (YOLOX-S via `cv.dnn`)

- **Calibration:** ground-truth pixel positions land exactly on rendered people and markers.
- **Resolution matters:** at 640×360 a person 30 m away is about 15 px tall, and YOLOX finds only 2–21 of hundreds of people. At 1280×720 with 2×2 tiling, detections roughly triple (17 → 49 in one CAM-3 frame). So 720p is the default.
- **People who are already down were not detected** in our tests. They were either hidden by standing people or were a dark shape inside a ring of crouching helpers. This matches the real-world problem, and it's why MoshSpot tracks the **fall onset** while the person is still visible and uses help-ring and immobility signals.
- The figures are low-poly, so treat absolute detector numbers as a lower bound. Use the sim to test the **pipeline logic** (tracking, state machine, agent, dispatch, escalation), not to benchmark a detector.

## Security (anything beyond localhost)
- **Token:** set `MOSHSPOT_TOKEN` (16+ characters, e.g. `openssl rand -hex 24`) and every API call needs it, as `Authorization: Bearer <token>`, `X-MoshSpot-Token`, or `?token=` (for MJPEG URLs in `cv.VideoCapture`). Only the page itself and `/status` stay public. Open the page as `https://host/#token=<token>`; the fragment never reaches the server or its logs, and the page removes it from the address bar.
- **Refuses to start** on a non-loopback `--host` (such as `0.0.0.0`) without a token.
- **Limits:** request bodies are capped (4 MB per frame, 32 MB for `gt.json`, 64 KB for commands and events), with at most 16 cameras, 64 teams and 32 concurrent MJPEG viewers. The command and event queues keep the last 1,000 entries, and a 30 s socket timeout stops idle clients from tying up threads.
- **Recording is off by default:** `--record` (or `MOSHSPOT_RECORD=1`) is the only way the bridge writes to disk.
- The bridge speaks plain HTTP. Put it behind HTTPS (Caddy or an AWS load balancer). See [DEPLOY.md](DEPLOY.md).

With a token set, add it to the curl calls above: `curl -H "Authorization: Bearer $MOSHSPOT_TOKEN" …`

## Hosting for judges
See [DEPLOY.md](DEPLOY.md): MoshSpot's worker and this bridge on one Graviton instance running COOL, behind HTTPS. `web/index.html` also works as a plain static page (S3 + CloudFront) without the bridge; the sim runs and **Download GT** works, but frames aren't streamed anywhere.

## License
[MIT](LICENSE) © 2026 Gofer AI
