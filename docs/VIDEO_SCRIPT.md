# MoshSpot — 5-minute video script

**Hard limit: 5:00.** Aim for 4:40, and keep captions on.

**Recording setup:** OBS or QuickTime at 1080p. Use the browser at http://localhost:8780 (or the deployed URL) and a terminal running the worker.

**Before you record:**

1. Start the bridge (`python3 bridge.py --record`) and open the page.
2. Set **Scenario: Demo**, **seed 7**, **Accept: auto after 5 s**, then click **Reset / start**.
3. Start the worker straight away, with nothing else running so it gets the full CPU:
   ```bash
   uv run python -m moshspot.worker --calibration runs/<any run>/gt.json
   ```
   The first collapse happens about 12 s in, and MoshSpot's alert lands 12–16 s after the person goes down.
4. Record the whole 3-minute run once, then cut it.

**Make the demo reliable.** MoshSpot catches a collapse when a standing person at that spot looks at least ~75 px tall in some camera (report §6.2). The scripted demo's first collapse (Pit Left, near CAM-1) meets that. For more collapses on camera:

1. Choose **Sandbox (manual)** and **click → Collapse (stays down)**.
2. Click a person in the **lower half of a camera tile** (CAM-3's lower half works well), so they're close to that camera.
3. Wait about 20 s, for the helpers to gather plus the 13 s decision delay.

**Look-alike shots:**

- For the "doesn't overreact" shot, use **Sit down** or **Crouch & recover**.
- For the agent closing an incident on its own, use **Collapse, gets up**.

Don't run anything heavy alongside the worker. It needs the CPU to keep up with four 5 fps streams.

| Time | Picture | Narration (say roughly this) |
|---|---|---|
| 0:00–0:20 | White text on black, one line at a time: "Astroworld, Nov 5, 2021", then "9:30 pm: 'people are going down'", then "9:32 pm: a fan climbs a camera platform and begs the operator for help", then "The show goes on for 40 more minutes. Ten people die." | (silent, or a single line) "The cameras were already pointed at the crowd. Nobody was watching them for people going down." |
| 0:20–0:35 | Team on camera, or photos with names | "We're Gofer AI: [names, roles]. This is MoshSpot." |
| 0:35–0:55 | The sim: four camera tiles, the venue map | "MoshSpot watches the cameras a venue already has. Here, that's our simulator: 1,500 people and four fixed CCTV cameras, with exact ground truth." |
| 0:55–1:40 | A collapse in Pit Left (about 12 s in). Zoom the screen recording on the incident panel as its steps appear. | "Someone goes down. In a crowd this dense, the camera can't see them once they're on the ground, but it sees the people who crouch down to help. MoshSpot saw the fall, found the ring of helpers, checked whether the person got back up, and looked closer at the real pixels. Then it alerted." |
| 1:40–2:10 | The map: the EMT team's dashed path, the team walking, then the panel showing "on_scene" | "It sends the team with the shortest walking time through the crowd, not the shortest straight line. Here's EMT-1 on their way." |
| 2:10–2:30 | A sit-down or crouch happening, and nothing alerting. Optionally the fall-and-recover with "closed: the person got back up". | "Just as important: someone sitting down, crouching, or getting back up doesn't send a team." |
| 2:30–2:45 | Accept set to **never**: the trace shows "escalated: no acknowledgement in 45 s; sending the next team" | "If a team doesn't acknowledge in 45 seconds, MoshSpot escalates to the next one." |
| 2:45–3:25 | Architecture diagram (README / REPORT.md §2) | "Every vision step runs on OpenCV 5's new DNN engine: YOLO26 detection on tiles, pose on enlarged crops, and calibrated geometry that turns pixels into metres. The agent is code with guardrails: it can't dismiss a patient without persistent visual evidence. It all runs on one AWS Graviton instance from the COOL AMI, behind HTTPS." |
| 3:25–4:10 | Results table (REPORT.md §6), then the range finding | "We tuned on one seeded run and tested on held-out runs. [Read the two headline numbers.] What limits it is range: a collapse is caught when a person standing at that spot is about 75 pixels tall in some camera. That's a camera placement rule, not a model limitation." |
| 4:10–4:35 | A failure case from §7, and a privacy line | "It isn't perfect, and the report shows where it fails. It never identifies anyone, raw video never leaves memory, and a human dispatcher always stays in the loop." |
| 4:35–4:45 | Logo plus the URL or QR code | "MoshSpot. Seconds, not minutes." |

**Tips:**

- Speak slowly. The panel's trace is the star, so leave it on screen long enough to read.
- Use real numbers only, the same as the report's.
- Upload as **unlisted** on YouTube, then test the link in a private window.
