# Testing MoshSpot (for judges)

Three ways to check MoshSpot, from 2 to about 15 minutes.

## 1. Watch the demo (2 min)

**Video:** <VIDEO LINK>

It was recorded live: MoshSpot Sim, watched by the real MoshSpot worker.

## 2. Try the live demo on AWS (5 min)

Open the **judge link** from our judges-only submission notes. It ends in `#token=…`. The token keeps the endpoint private, so it is not in this repo.

Use desktop **Chrome or Edge**. The concert renders in your browser with WebGL, so a machine with a GPU works best.

1. Wait for the header to show **bridge: connected**.
2. Set up and start the scripted demo:
   - **Scenario:** Demo — 3 min story
   - **seed:** 7
   - **Accept:** auto after 5 s
   - Click **Reset / start**.
3. About 12 s in, someone collapses in **Pit Left**, close to CAM-1. Soon after, people around them crouch down to help.
4. Watch the **MoshSpot incidents** panel. Within about a minute it shows a **HIGH** alert, with each step of the agent's trace:
   - fall seen
   - help ring found
   - evidence checked at the spot (is anyone standing or lying there?)
   - looked closer at a zoomed crop
   - alert
   - teams ranked by walking time
   - team dispatched

   If the agent can't confirm it, the incident shows **REVIEW** with a **Dispatcher: send nearest team** button. That button is the human-in-the-loop path.
5. On the **venue map**, the nearest EMT team walks to the patient. Its status goes accepted → en route → on scene.

**Next, try these in the same page.** Choose **Scenario: Sandbox (manual)**, pick an action under **click →**, then click a person in the **lower half of a camera tile**, where people are close to that camera.

| Click action | What MoshSpot should do |
|---|---|
| **Sit down** or **Crouch & recover** | No alert. Look-alikes must not send a team. |
| **Collapse (stays down)** | Alert and dispatch, usually within a minute (helpers gather first, then the agent decides). |
| **Collapse, gets up** | The agent closes the incident on its own once the person is back up. |
| Any collapse, with **Accept: never (test escalation)** set first | After 45 s with no acknowledgement, the trace shows **escalate** and the next team is sent. |

**Notes:**

- **One judge at a time.** The endpoint runs one shared sim. If you see incidents you didn't cause, someone else is driving it. Wait a few minutes, then click **Reset / start**.
- **Range limit, by design.** A collapse is caught where a standing person looks at least ~75 px tall in some camera: the lower half of the tiles. Collapses far from every camera are usually missed. That's the camera-placement rule in [REPORT.md §6.2](REPORT.md).
- **Privacy.** There's no face recognition and no identity, and frames are processed in memory.

## 3. Run it yourself (about 15 min)

**You need:**

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- A desktop browser with WebGL
- Linux or macOS (on Windows, use WSL for the model export)

```bash
git clone https://github.com/Gofer-AI/gofer-moshspot && cd gofer-moshspot
uv sync --locked --extra local     # pinned dependencies, including opencv-contrib-python 5.0
uv run pytest                      # 103 tests
bash tools/export_models.sh        # once: exports YOLO26n and YOLO26n-pose to ONNX (installs PyTorch in a throwaway folder)
python3 bridge.py                  # then open http://localhost:8780
```

1. In the page, click **Download venue JSON**. It holds the camera calibration and the venue.
2. Start the worker in a second terminal:

   ```bash
   uv run python -m moshspot.worker --calibration ~/Downloads/moshspot-venue.json --cameras CAM-1
   ```

3. Follow the steps in section 2.

Watching one camera keeps a laptop CPU fast enough, at about 3 fps. Add cameras (`--cameras CAM-1,CAM-3`) on a bigger machine.

**To reproduce the evaluation,** see "Score a recorded run" in the [README](../README.md):

1. Record a run in the sim.
2. Cache perception with `tools/perceive_run.py`.
3. Score it with `tools/evaluate_run.py`.

Results, ablations and failure cases are in [REPORT.md §6–7](REPORT.md).
