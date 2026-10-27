# MoshSpot — Win Strategy, Evidence Checklists, Schedule

**Companion docs:** [PRD.md](PRD.md) · [SHOOT_PLAN.md](SHOOT_PLAN.md)
**Roles:** **A** = CV + evaluation · **B** = agent, cloud, UI, video. If the team is solo, see §5.3.

---

## 1. Competition at a glance

| Item | Detail |
|---|---|
| Submission deadline | **Mon Oct 26, 11:45 pm PDT** (Devpost). opencv.org says 11:59 pm, so plan for the earlier time. We submit **Sun Oct 25**. |
| Judging | Oct 27 – Nov 9. **The demo endpoint must stay up for the whole window.** Winners are announced Nov 10 on OpenCV Live!. |
| Hard requirements | OpenCV 5 does the substantive image/video analysis; a meaningful part runs on AWS. |
| Judges | Gary Bradski (OpenCV founder), Phil Nelson (OpenCV Live! host), and up to two AWS nominees. Each entry gets at least two independent scores. |
| Overall rubric | Technical execution 30 · Innovation 20 · Real-world impact 20 · UX 10 · Documentation 10 · Responsible cloud delivery 10 |
| Tie-breaks | Technical execution, then Real-world impact |
| Prizes | 1st $5k · 2nd $3k · 3rd $2k. One overall award per entry, plus either or both special awards ($1k each): **Agentic Vision** and **Best Use of COOL** |
| Rules to respect | No surveillance risk without safeguards; every piece of media needs rights or consent |

**What the judges likely reward:**

- **Bradski:** principled geometry and honest, measured results, including ablations and failure cases.
- **Nelson:** a clear story and a strong video.
- **AWS judges:** clean, observable, secure deployment.

## 2. Rubric → evidence map

| Criterion | What wins it | Evidence artifact | Owner | Due |
|---|---|---|---|---|
| **Technical execution (30%)** | Everything runs in OpenCV 5:<br>• DNN ENGINE_NEW<br>• calibration + `solvePnP` + USAC homography<br>• DIS optical flow, KalmanFilter<br><br>Posture in world coordinates, with an explicit ambiguity flag. Held-out evaluation with ablations against naive baselines. | Report §3 + §6, ablation table, tests, clean code | A | Results Oct 21, report Oct 24 |
| **Innovation (20%)** | • Help-ring cue for hidden collapses<br>• Active-perception agent that spends compute or a second camera only when unsure<br>• Cluster escalation for crush risk | Demo scenarios S2 + S4, report §4 | A + B | Oct 21 |
| **Real-world impact (20%)** | • Astroworld timeline + time-to-care physiology<br>• Measured collapse → dispatch seconds<br>• $ per camera-hour on cameras venues already own<br>• Workflow designed around EMTs | Report §1 + §6, video hook | B | Oct 24 |
| **UX (10%)** | • Glanceable EMT card<br>• Judge's phone becomes the EMT radio via QR code<br>• "Why was I alerted" trace view | Live endpoint, video demo | B | Oct 21 |
| **Documentation (10%)** | Report mirrors the required sections; architecture and agent diagrams; one-command run/deploy/test | `docs/report/`, README, diagrams | A + B | Oct 24 |
| **Responsible cloud (10%)** | CDK, HTTPS via CloudFront, least-privilege IAM, encrypted S3 with expiry, CloudWatch dashboard + alarms, Budgets, privacy safeguards | `infra/`, report §5 + §8, screenshots | B | Oct 21 |

**Optional, high-leverage for Real-world impact:** one 15-minute call with an EMT or event medic for a quote. Try a collegiate EMS club, a local event-medical company, or a friend in EMS. Ask:

1. How do you find a collapsed patient in a crowd today?
2. What information do you need before you move?
3. How long does it usually take?

Send the outreach by **Wed Oct 7**.

## 3. Special awards: evidence checklists

### 3.1 Agentic Vision ($1,000)

**Qualifying bar:** OpenCV 5 results must change a later plan, tool call, action, or request for human approval. A chatbot that explains a fixed result does not qualify.

**Rubric:** OpenCV 5 + agent 30 · Orchestration & autonomy 25 · Task effectiveness 20 · Failure handling & human control 15 · UX 10.

- [ ] Agent workflow diagram (perceive → decide → act), saved to `docs/diagrams/agent_workflow.*`.
- [ ] At least 4 recorded traces where OpenCV output changes the next step:
  1. MEDIUM → `look_closer` → refined posture is LYING and immobile → `dispatch_team`.
  2. MEDIUM → `look_closer` → person is moving or upright → watch list. The dismissal recommendation goes to a human.
  3. Ambiguous posture → `cross_check_camera` → second view confirms lying → dispatch.
  4. HIGH → immediate dispatch → no acknowledgement in 45 s → `escalate`.
- [ ] Evaluation:
  - task success, meaning the final action matches ground truth;
  - time to decision;
  - precision with vs without the agent.
- [ ] Failure injection: Bedrock timeout, malformed tool output, and camera offline. The expected result in each case is human review, never a silent drop.
- [ ] Observability: a trace viewer in the dashboard, plus CloudWatch metrics for agent latency and errors.
- [ ] Human control: only a human can dismiss; the dispatcher can always override.

### 3.2 Best Use of COOL ($1,000)

**Qualifying bar:** COOL must run the claimed core workload on AWS Graviton, with reproducible measurements against a baseline.

**Rubric:** Verified COOL on Graviton 30 · Architecture & quality 25 · Measured performance/value 20 · Innovation 15 · Reproducibility 10.

- [ ] COOL version (v3.1 / OpenCV 5.0), AMI ID, and instance type stated in the report.
- [ ] Worker logs `cv2.getBuildInformation()` at startup, captured in CloudWatch and committed under `eval/results/cool/`.
- [ ] `tools/benchmark_cool.py` compares three configurations:
  - c8g + COOL;
  - c8g + stock `opencv-python` 5;
  - c7i + stock.

  For each, it reports per-stage ms, end-to-end fps, CPU utilization, and $ per camera-hour (prices dated).
- [ ] Results table and chart, with raw CSVs in the repo.
- [ ] Architecture note: the whole video hot path runs on Graviton. Any x86 component is named, and the report explains why it sits outside the hot path.

## 4. Devpost submission checklist

| Item | Owner | Due |
|---|---|---|
| Technical report covering problem, users, architecture, OpenCV 5 implementation, AWS deployment, evaluation, limitations, and responsible use | A | Sat Oct 24 |
| Repository judges can access, with pinned deps (`uv.lock`) and build/deploy/test instructions | A | Sat Oct 24 |
| Architecture diagram showing OpenCV 5, AWS, COOL, and the agent | B | Thu Oct 22 |
| Working web endpoint, plus demo access instructions and the QR flow | B | Wed Oct 21 |
| Video of **5:00 or less** showing the team, the app working, the architecture, and the results; public or unlisted | B | Sat Oct 24 |
| Evaluation evidence, including failure cases | A | Wed Oct 21 |
| COOL extras: version, instance config, method, baselines, results, proof COOL runs the workload | A | Wed Oct 21 |
| Agentic extras: workflow diagram, traces, evaluation of failure handling and human control | B | Wed Oct 21 |
| Devpost form: all team members added, **both special awards opted into**, every link tested in an incognito window | A + B | Sun Oct 25 |
| Data licences and attribution listed in the report appendix | A | Sat Oct 24 |

## 5. Schedule (today is Sat Oct 3)

### 5.1 Milestones

- **Sun Oct 4:** docs, repo, and the OpenCV 5 pose spike are done.
- **Wed Oct 7:** go/no-go on the Tier 2 volunteer shoot; EMT outreach sent.
- **Sat Oct 10:** Tier 1 shoot, session 1 (dev set).
- **Fri Oct 16:** **end-to-end on AWS**: footage → detection → agent → phone. P1 work starts only after this.
- **Sat Oct 17:** Tier 1 shoot, session 2 (held-out set, night). Tier 2 also runs this day if it's a go.
- **Wed Oct 21:** **feature freeze.** Evaluation numbers are final.
- **Sun Oct 25:** submit.

### 5.2 Day by day

| Date | A (CV + eval) | B (agent, cloud, UI, video) |
|---|---|---|
| Sat 3 – Sun 4 | Repo scaffold, pose ONNX spike, geometry module and tests | AWS account, Budgets alarm, check COOL/Bedrock pricing; shoot logistics (location, permission, ChArUco print, mats) |
| Mon 5 | Ingest + ring buffer + replay-as-live | Incident model, FastAPI skeleton, WebSocket |
| Tue 6 | Tracker (Kalman + Hungarian) | EMT PWA skeleton: card, sound, vibration, Accept |
| Wed 7 | Calibration tool (ChArUco, `solvePnP`, homography) + venue map JSON | Dashboard skeleton (tiles, queue, map). **Tier 2 go/no-go; EMT outreach.** |
| Thu 8 | Posture + state machine on public clips (Okutama, fall datasets) | Agent loop with mocked tools + guardrails + trace logging |
| Fri 9 | Head blur; pipeline v1 end-to-end on laptop | CDK skeleton (VPC, EC2 c8g, DynamoDB, S3, CloudFront) |
| **Sat 10** | **Shoot session 1** | **Shoot session 1** |
| Sun 11 | Calibrate cameras, label onsets | Cut clips, back up footage |
| Mon 12 | Tune posture and state machine on session 1 | Bedrock integration (Converse + tools) |
| Tue 13 | Help-ring cue | Real tools wired into the agent |
| Wed 14 | `look_closer` (tiles from the ring buffer) | Deploy worker to c8g + COOL (start the 7-day trial) |
| Thu 15 | Cross-camera fusion + `cross_check_camera` | Dispatch, acknowledgement timer, escalation, cluster alarm |
| Fri 16 | Evaluation harness v1 on session 1 | CloudWatch metrics, alarms, dashboard. **Milestone: end-to-end on AWS** |
| **Sat 17** | **Shoot session 2 (held-out, night)** | **Shoot session 2** (+ Tier 2 if go) |
| Sun 18 | Label session 2 | Demo scenarios S1–S4 from the footage |
| Mon 19 | Held-out evaluation + ablations | QR pairing flow, demo tokens |
| Tue 20 | COOL benchmark (3 configs), failure gallery | Security hardening, retention lifecycle, audit log |
| Wed 21 | Final numbers. **Freeze.** | UX polish. **Freeze.** |
| Thu 22 | Report draft (§1–§5) | Diagrams; video script and shot list |
| Fri 23 | Report draft (§6–§9) + README | Record the demo and voiceover |
| Sat 24 | Final report; reproducibility test on a clean machine | Edit the video (≤ 5:00); upload unlisted |
| **Sun 25** | **Submit** | **Submit** |
| Mon 26 | Buffer only (deadline 11:45 pm PDT) | Buffer only |
| Oct 27 – Nov 9 | Keep the endpoint up; watch alarms; no breaking changes | Same |

**Every Friday:** a 30-minute review against §2 and §4. If we're behind, cut scope, not quality.

### 5.3 If solo

Cut these, in order:

1. `cross_check_camera`, with one camera per take. `look_closer` still demonstrates active perception.
2. The Tier 2 shoot.
3. Cognito and all other P1 items.
4. The x86 COOL baseline. Compare c8g + COOL against c8g + stock only.

Keep the evaluation and the video. They're worth more than features.

## 6. Demo design (judge experience)

The landing page has three buttons:

- **Open control room**
- **Pair my phone** (shows a QR code that turns the judge's phone into EMT Team 2)
- **Run a scenario**

| Scenario | Shows | Expected outcome |
|---|---|---|
| S1 Clear collapse | Core detection + geometry | HIGH → immediate dispatch → phone buzzes in under 30 s |
| S2 Hidden collapse, helpers kneeling and waving | Help ring + active perception | MEDIUM → agent calls `look_closer` → dispatch, with the trace visible |
| S3 Look-alike (someone sits down to rest) | Restraint and precision | LOW watch item; no dispatch |
| S4 Two people down nearby | Crush risk | Cluster alarm in the control room |

The background loop plays footage with no incidents, so judges can see the system staying quiet. A **Reset** button restores the demo. A status bar shows fps per camera, worker heartbeat, and the time of the last alarm.

## 7. Video plan (5:00 hard limit; aim for 4:45)

| Time | Beat | Visual |
|---|---|---|
| 0:00–0:25 | Hook | White text on black: the Astroworld timeline (9:30, 9:32, 9:38, about 40 min, 10 deaths), then "The cameras were already pointed at the crowd." Factual; no real incident footage. |
| 0:25–0:40 | Team (required) | Faces, names, roles |
| 0:40–2:30 | Demo | Split screen: control room and phone. S1 → overlay and timeline → phone buzzes → Accept. S2 with the agent trace. S3 stays quiet. S4 cluster alarm. |
| 2:30–3:15 | Architecture | Animated diagram: cameras → OpenCV 5 on Graviton (COOL) → agent on Bedrock → apps; AWS services |
| 3:15–4:15 | Results | Metrics table, ablation chart, latency breakdown, COOL chart, $ per camera-hour |
| 4:15–4:45 | Limits + privacy | Failure-case montage; blur; no face recognition; human in control |
| 4:45–5:00 | Close | One-liner, URL/QR |

Captions on. 1080p screen recordings. Voiceover script locked by Thu Oct 22.

## 8. Technical report outline (`docs/report/`)

1. **Problem and users:** PRD §2–§3, condensed.
2. **Architecture:** the diagram, plus the data flow.
3. **OpenCV 5 implementation:** module table, posture geometry with figures, state machine, tracker, privacy blur.
4. **Agent:** workflow diagram, tools, guardrails, example traces.
5. **AWS deployment:** services, CDK, security, observability, cost.
6. **Evaluation:** data, metrics, baselines and ablations, COOL benchmark, results.
7. **Limitations and failure cases.**
8. **Responsible use and privacy.**
9. **Reproducibility:** how to run, test, and deploy.

**Appendix:** dataset licences and attribution; model licences (Ultralytics AGPL-3.0).

## 9. Messaging

**One-liner:** *MoshSpot puts a crowd spotter that never looks away on every camera a venue already owns.*

**30-second pitch:** At big events, people collapse in crowds where no one can see them or say where they are. For cardiac arrest, every minute costs about 10% survival. MoshSpot watches existing crowd cameras with OpenCV 5. It detects someone who goes down and stays down, measures their posture in real-world metres, and uses an AI agent to double-check. Then it sends the nearest EMT a pin on their phone within seconds. It runs on AWS Graviton for cents per camera-hour, never recognizes faces, and keeps a human in charge.

**Claims we make** (each backed by a measured number):

- Collapse-to-dispatch time.
- Recall and precision on held-out footage.
- False alerts per camera-hour.
- Cost per camera-hour.

**Claims we don't make:**

- "Saves X lives."
- "Works in any crowd."
- "Replaces staff."

## 10. Pitfalls to avoid

- Scraped concert footage, or anyone on camera without a signed release.
- Putting the LLM in the critical path for HIGH alerts.
- Overclaiming. Every number in the video must appear in the report.
- Demo endpoint down or broken during judging (Oct 27 – Nov 9). Freeze deploys after submitting.
- Video over 5:00, or a video that doesn't show the team.
- Repo or endpoint not accessible to judges. Test both from a logged-out browser.
- Forgetting to opt into the special awards on the Devpost form.
- Skipping the failure-cases section. The rules require it, and honesty scores well.
