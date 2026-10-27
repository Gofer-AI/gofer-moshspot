# MoshSpot — Product Requirements Document

> **Planning document, written 2026-10-03.** What we actually built and measured is in [REPORT.md](REPORT.md); where they differ, the report is current.

**Status:** Draft v0.1 for team review · **Date:** 2026-10-03
**Competition:** OpenCV AI Competition 2026, powered by AWS · **Deadline:** Mon 2026-10-26, 11:45 pm PDT
**Companion docs:** [STRATEGY.md](STRATEGY.md) (rubric, awards, schedule, video) · [SHOOT_PLAN.md](SHOOT_PLAN.md) (footage)

---

## 1. Summary

MoshSpot turns the fixed crowd cameras a venue already owns into crowd spotters that never look away:

1. It detects a person who collapses and stays down.
2. An AI agent gathers more visual evidence to verify the event.
3. It pins the person's location on the venue map.
4. It sends the nearest EMT team a dispatch on their phone within seconds.

A human stays in control throughout. Privacy is built in: no face recognition, heads are blurred, and raw video is never stored.

## 2. Problem statement

At concerts, festivals, and stadium events, people collapse every night from heat, dehydration, intoxication, cardiac arrest, or crowd compression. In a dense, dark, loud crowd, a person who goes down drops below the crowd line within seconds. The people around them may not notice. The ones who do can't reach help or say where the person is. Event medics usually find out only when someone fights through the crowd to report it, or a spotter on a platform happens to see it.

Minutes decide outcomes:

- Cardiac arrest survival falls about 7–10% for every minute without CPR or defibrillation.
- Compression asphyxia kills within minutes.

At Astroworld 2021, officials first heard "people are going down" at 9:30 pm. At 9:32 an attendee climbed onto a camera platform to beg the operator for help. The show went on for about 40 more minutes, and ten people died of compression asphyxia. The cameras were already pointed at the crowd; no one was watching them for people going down.

Mass gatherings produce a steady flow of medical cases (about 13 patient presentations per 1,000 attendees at Glastonbury). Venues already run dozens of cameras and post human spotters on elevated platforms, but a few people can't watch 50,000 faces all night.

**MoshSpot closes the gap between "someone went down" and "a medic is on the way."** We measure the impact as *time to care*: the seconds from collapse to an EMT being dispatched to the right spot. That is the lever that drives survival, so we make no claims about lives saved.

### Key facts

| Fact | Source |
|---|---|
| Cardiac arrest survival drops about 7–10% per minute without CPR/defibrillation | American Heart Association, via [Red Cross](https://www.redcross.org/take-a-class/resources/articles/cpr-facts-and-statistics) |
| Astroworld 2021 timeline:<br>• 9:30 pm: first reports that people are going down<br>• 9:32 pm: attendee climbs camera platform to ask for help<br>• 9:38 pm: mass-casualty event declared<br>• Show continued about 40 minutes after the first reports<br>• 10 deaths from compression asphyxia | [CNN](https://www.cnn.com/2021/11/08/us/astroworld-festival-crowd-surge-timeline), [ABC13](https://abc13.com/post/astroworld-timeline-what-happened-at-concert-crowd-crush/13441821/) |
| 13.47 patient presentations per 1,000 attendees at Glastonbury; 12.01 per 1,000 at an Austrian festival (2011–2017) | [PMC11035920](https://pmc.ncbi.nlm.nih.gov/articles/PMC11035920/), [Wien Klin Wochenschr](https://link.springer.com/article/10.1007/s00508-021-01856-5) |
| Festivals post human crowd spotters on elevated platforms. Several medical extractions in a short time are a red flag for dangerous density. | [TicketFairy](https://www.ticketfairy.com/blog/what-most-festivals-get-wrong-about-crowd-safety-and-how-to-avoid-a-disaster) |

## 3. Users

### 3.1 Event EMT / medic (primary user)

- **Context:** on foot or at a medical post. It's loud, dark, and crowded, and one hand is usually busy.
- **Needs:**
  - *Where exactly:* a walkable location with a landmark.
  - *What to expect:* lying, not moving, bystanders helping.
  - *How sure:* the evidence.
  - A one-tap acknowledge.
- **Today:** hears about patients over the radio from security or a spotter, gets a verbal location ("near the left speaker stack"), and searches the crowd.

### 3.2 Medical dispatcher / control-room operator

- **Context:** watches many feeds plus radio traffic and coordinates several teams.
- **Needs:**
  - A prioritized queue with evidence and the system's reasoning.
  - Confirm / dismiss / reassign controls.
  - Team status.
  - Immediate notice when a feed or the system itself is unhealthy.

### 3.3 Venue safety manager (buyer)

- **Needs:** works with existing cameras, low cost per camera, privacy and legal compliance, an audit trail, and measurable response times.

### 3.4 Attendees (beneficiaries and data subjects)

- **Expect:** fast help, not being identified or tracked, and no footage of them kept.

## 4. Goals, non-goals, success metrics

### Goals

- **G1:** Detect people who collapse and stay down in fixed crowd-camera footage.
- **G2:** Deliver a verified, located dispatch to the nearest EMT team within seconds of the collapse.
- **G3:** Keep false alerts low enough that medics trust the system.
- **G4:** Protect attendee privacy and keep humans in control.
- **G5 (competition):** 1st place overall, plus the Agentic Vision and Best Use of COOL awards.

### Non-goals

- Face recognition, identity, or re-identification.
- Medical diagnosis.
- Replacing human spotters, medics, or radio.
- Drone flight or PTZ camera control (future work).
- Crowd-density forecasting (future work).

### Success metrics

All metrics are measured on held-out data. The targets are what we aim for, not promises.

| Metric | Definition | Target |
|---|---|---|
| Event recall (clear view) | Detected collapses ÷ staged collapses with the person visible | ≥ 90% |
| Event recall (occluded) | Same, with the person mostly hidden | Report only |
| False alerts per camera-hour | Dispatches or review requests on footage with no incident | ≤ 1 |
| Collapse → dispatch | Collapse onset to EMT notification (median, p90) | ≤ 20 s median, including the deliberate 8 s immobility window |
| Localization error | Distance between the pinned and true floor position | ≤ 1.5 m |
| Throughput | Camera streams at 5 fps per Graviton instance | ≥ 2 |
| Cost | $ per camera-hour, Graviton + COOL vs x86 | Report |

## 5. User stories and acceptance criteria

**US-1 (EMT): dispatch with location.** When someone collapses near me, my phone gets a dispatch with a map pin, a blurred snapshot, and a one-line description, so I can go straight there.
- Arrives with sound, vibration, and a visual alert.
- Shows:
  - zone name and nearest landmark;
  - distance from my post;
  - time since the collapse;
  - posture and moving/not-moving status;
  - bystander status.
- One-tap **Accept**.
- Readable in the dark, in sunlight, and with one hand.

**US-2 (EMT): status updates.** I can mark **On scene**, **Resolved**, or **False alarm**.
- One tap each. The control room sees it within 1 s, and the outcome is logged for evaluation.

**US-3 (Dispatcher): prioritized queue.** I see a prioritized incident queue with the evidence and the agent's reasoning, and I can confirm or override.
- Each incident shows:
  - the camera tile with overlay;
  - a timeline (fall onset, immobility, agent steps);
  - priority and assigned team.
- Confirm / dismiss / reassign buttons. Dismissing always requires a human click.

**US-4 (Dispatcher): escalation.** If no team acknowledges within 45 s, the system escalates to the next nearest team and flags me.
- The escalation shows in the timeline, and the second team gets the dispatch.

**US-5 (Dispatcher / safety manager): crowd-crush alarm.** If two or more people go down near each other, I get a "possible crowd crush" alarm.
- Trigger: 2 or more incidents within 10 m and 3 min.
- It's a distinct alarm that links both incidents and requires acknowledgement.

**US-6 (Dispatcher): system health.** If a camera feed drops or the vision worker stops, I know immediately.
- Warning on the dashboard within 30 s, plus a CloudWatch alarm notification.

**US-7 (Safety manager): camera setup.** I can set up a camera by clicking floor landmarks and drawing zones on a venue map, with no code.
- The tool shows reprojection error and saves the calibration and zones as JSON.
- Setup takes 15 minutes or less per camera.

**US-8 (Attendee): privacy.** My face is never stored or shown, and footage of me isn't kept.
- Every image leaving the vision worker has heads blurred.
- Raw frames exist only in an in-memory ring buffer.
- Incident clips expire after 7 days.
- No identity features are ever computed.

**US-9 (Judge): live demo.** I open the demo URL, scan a QR code to turn my phone into an EMT device, start a scenario, and receive the dispatch.
- No account needed (a scoped, expiring demo token).
- The dispatch reaches the phone within 30 s of the staged collapse.

## 6. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Ingest RTSP or file video at a configurable rate (default 5 fps), with a 20 s in-memory ring buffer per camera. "Replay as live" loops recorded footage for the demo. | P0 |
| FR-2 | Detect people on the full frame with a YOLO detector run by **OpenCV 5 DNN (ENGINE_NEW)**. Then estimate 17 COCO keypoints **top-down** on enlarged crops of each person, in one batched pass of a dynamic-shape pose model. Full-frame pose misses people under about 100 px (see the [dev log](DEVLOG.md)). High-resolution tiles run only on request. | P0 |
| FR-3 | Track people with a Kalman filter and Hungarian assignment on floor distance and box overlap. | P0 |
| FR-4 | Calibrate each camera:<br>• intrinsics from a ChArUco board (or a focal-length estimate);<br>• extrinsics from 6 or more floor landmarks via `solvePnP`;<br>• a floor homography;<br>• reprojection error reported. | P0 |
| FR-5 | Venue map: floor-plan image plus JSON with zones (polygons), landmarks, EMT posts, and scale. | P0 |
| FR-6 | Posture in world coordinates: upright / low / lying / unknown, with an explicit ambiguity flag (§7.2). | P0 |
| FR-7 | Down-event state machine using fall onset, immobility, and the help-ring cue, emitting HIGH / MEDIUM / LOW candidates (§7.3–7.5). | P0 |
| FR-8 | Incident agent with OpenCV tools and guardrails enforced in code (§8). | P0 |
| FR-9 | Dispatch to the nearest available team, with an acknowledgement timer, escalation, and EMT status actions. | P0 |
| FR-10 | Cluster escalation ("possible crowd crush") (§7.6). | P0 |
| FR-11 | Privacy controls: head blur, no identity features, retention limits, audit log (§11). | P0 |
| FR-12 | Control-room dashboard and EMT phone PWA. | P0 |
| FR-13 | Health monitoring: fps per camera, worker heartbeat, alarms. | P0 |
| FR-14 | Evaluation harness that produces every §4 metric from labelled footage. | P0 |
| FR-15 | Demo endpoint with QR-code pairing for the EMT phone and a scenario trigger. | P0 |
| FR-16 | Low-light enhancement (CLAHE) for night footage. | P1 |
| FR-17 | Upload-your-own-clip on the demo site. | P1 |
| FR-18 | Detect responder arrival to measure time-to-patient. | P1 |
| FR-19 | Cognito logins with roles. | P1 |
| FR-20 | Future work:<br>• drone, PTZ, and thermal sources;<br>• crowd density/pressure heatmap;<br>• edge deployment;<br>• SMS, radio, and CAD integration;<br>• a VLM verifier running inside OpenCV 5. | P2 |

**Scope rule:** nothing from P1 starts until the Fri Oct 16 end-to-end milestone is met. Feature freeze is Wed Oct 21.

## 7. Detection logic

### 7.1 Why calibrated geometry

A bounding box that is wider than it is tall does not mean "lying down." Perspective, occlusion, and camera tilt all change box shapes. Every camera is calibrated, so for any floor point we know two things:

- which image direction is "up" there;
- how tall a standing adult should appear there.

That lets us reason in metres, not pixels.

### 7.2 Posture estimate (per person, per frame)

Implemented in `moshspot/geometry/posture.py` and tested on synthetic people in `tests/test_posture_geometry.py`.

The **torso** (hips → head) drives the decision. Legs are unreliable: seated people stretch them out, and in a crowd the feet are usually hidden. From the keypoints and the camera model we compute:

- **Torso angle:** the angle between the image torso axis (hips → head) and the image's local "up" direction at the person's floor position.
  - 0° means the torso is vertical; 90° means it lies across the view.
  - Near 180° means the head is *below* the hips in the image, which is impossible for an upright person.
- **Torso floor length:** the hip-to-head distance after back-projecting both onto the plane 0.12 m above the floor, where a lying body's joints sit. A lying adult measures 0.35–1.3 m. An upright person's head lands metres away.
- **Head height** (only when the ankles are visible and under the hips): the height on the vertical line through the feet that best matches the head keypoint. It's the closest point between the head's viewing ray and that line.
- **Floor position:** the pin the EMT receives.
  - Lying: the hips on the floor plane.
  - Otherwise: the feet if visible, or else the hips at mid-height.

**Classification** (initial thresholds, tuned on dev footage):

| Condition | Posture |
|---|---|
| Torso angle ≥ 135° | LYING |
| Torso angle ≥ 45° and torso floor length plausible | LYING (LOW if the hips are ≥ 0.6 m above vertical legs, i.e. bending over) |
| Torso angle 30–45° (leaning) | LYING + ambiguous if the floor length is plausible, else LOW |
| Torso angle < 30°, feet visible, and head height < 1.25 m (or legs stretched out) | LOW |
| Torso angle < 30°, otherwise | UPRIGHT. With the feet hidden, sitting and standing can't be told apart, which is fine: neither is lying. |
| A lying-on-the-floor reading is *also* plausible | `ambiguous=True` |

**Known blind spot:** a person lying with their head pointing straight *away* from the camera projects onto the same image line as an upright torso. Single-frame geometry can't separate the two.

- The estimator reports LOW + ambiguous in every test position, so it is never confidently UPRIGHT.
- Fall motion, immobility, and a second camera settle the case.
- The worst case is a camera looking down at about 45°. There, even standing people are flagged ambiguous.

### 7.3 Down-event state machine (per track)

`UPRIGHT → FALL_ONSET → DOWN → DOWN_IMMOBILE → candidate`

- **Fall onset:** within 2 s, either
  - a burst of fast keypoint motion (normalized by the person's size) ends in LYING or ambiguous-LOW posture, or
  - head height drops from above 1.3 m to below 0.7 m.

  The motion burst matters for the blind spot (§7.2), where posture alone barely changes.
- **Immobility:** the mean DIS optical-flow magnitude inside the person's region, normalized by person scale, stays below a threshold for:
  - 8 s after an observed fall onset;
  - 20 s if the person was first seen already down.
- **Recovery:** being UPRIGHT again for more than 3 s cancels the candidate.

### 7.4 Help-ring cue

We look at everyone within 2.5 m of a person who is down or low, and count two things:

- stationary people who are crouching or kneeling;
- people with both wrists above their head for at least 1 s (waving for help).

The score rises with those counts. This catches collapses where the fallen person is hidden but the people helping them are visible.

### 7.5 Priority

| Priority | Initial rule | System action |
|---|---|---|
| HIGH | Fall onset + down + immobile for 8 s or more, **or** down + a help-ring of 2 or more people | Immediate dispatch; the agent adds detail in parallel |
| MEDIUM | Down or ambiguous + immobile for 20 s or more with no observed fall, **or** a help-ring alone | The agent verifies, then dispatches or sends to human review |
| LOW | Down but moving, or low posture for a long time | Dashboard watch list; the agent re-checks periodically |

### 7.6 Cluster escalation

If 2 or more incidents of MEDIUM priority or higher occur within 10 m and 3 min, the control room gets a "possible crowd crush" alarm that must be acknowledged.

## 8. Agent design (Agentic Vision)

### 8.1 Loop

1. **Perceive:** the OpenCV pipeline emits a candidate with its evidence.
2. **Decide:** the agent picks tools to gather more evidence, then chooses to dispatch, request review, or watch.
3. **Act:** dispatch, escalate, or update the incident.
4. **Observe:** acknowledgements, timeouts, and EMT feedback feed the next step.

### 8.2 Tools

| Tool | What it does | OpenCV 5 inside |
|---|---|---|
| `get_evidence(track_id)` | Returns the posture timeline, immobility, fall onset, help-ring, zone, and camera | Pipeline outputs |
| `look_closer(camera_id, bbox, seconds)` | Re-runs detection and pose on high-resolution tiles from the ring buffer; returns refined posture and motion. This is active perception without PTZ hardware. | `dnn`, `imgproc`, `DISOpticalFlow` |
| `cross_check_camera(floor_xy)` | Finds another calibrated camera covering the same floor point and analyses it there | `projectPoints`, `dnn` |
| `describe_crop(incident_id)` | Sends a **head-blurred** crop to a VLM; returns `{person_down, signs, bystanders_helping, confidence}` | Blur, crop |
| `dispatch_team(incident_id, team_id?)` | Notifies the nearest available team | — |
| `escalate(incident_id)` | Notifies the next team and the control room | — |
| `request_human_review(incident_id, reason)` | Adds the incident to the control-room queue | — |
| `close_incident(incident_id, outcome)` | Marks it resolved or a false alarm | — |

### 8.3 Guardrails (enforced in code, not in the prompt)

1. HIGH incidents are dispatched immediately, without waiting for the LLM.
2. The agent may raise priority, add evidence, or *recommend* dismissal. Only a human can dismiss.
3. An LLM error, a timeout over 8 s, or malformed output sends the incident to human review. The system fails safe, never silently.
4. Every tool call is validated against a schema. Dispatches go only to real teams, and calls are rate-limited.
5. Every step is logged to the incident trace: inputs, outputs, latency, and model version. The dashboard shows the trace as "why was I alerted."

### 8.4 Model

- Claude Haiku 4.5 on **Amazon Bedrock**, using the Converse API with tool use.
- Fallback: Amazon Nova Lite, if the account's credits don't cover third-party models.
- The VLM only ever sees blurred crops.

## 9. Architecture

```
Fixed crowd cameras (RTSP, or replayed footage for the demo)
  │  5 fps · 20 s RAM ring buffer per camera
  ▼
Vision worker ── OpenCV 5 (COOL build) on EC2 Graviton4 (c8g)
  detect (cv.dnn ENGINE_NEW) → pose on enlarged crops (batched) → track (KalmanFilter) → floor mapping
  → posture in world coordinates → fall onset + immobility (DISOpticalFlow) → help ring
  → candidate events (HIGH / MEDIUM / LOW)
  ▼
Incident service + agent ── FastAPI · Bedrock (Claude) · guardrails · traces
  ▼
Apps ── control-room dashboard · EMT phone PWA (WebSocket; sound + vibration)

AWS: CloudFront (HTTPS, WebSocket) · S3 (static web; blurred clips with 7-day expiry, SSE)
     DynamoDB (incidents, traces, teams) · CloudWatch (logs, metrics, alarms, dashboard)
     SSM Parameter Store (secrets) · AWS Budgets · CDK (infrastructure as code)
```

### 9.1 Data model (initial)

- **Camera:** `id`, `stream_url`, `K`, `dist`, `rvec`, `tvec`, `coverage_polygon`.
- **Venue:** `floor_plan`, `scale_m_per_px`, `zones[]`, `landmarks[]`, `emt_posts[]`.
- **Incident:**
  - `id`, `camera_id`, `track_id`, `floor_xy`, `zone`, `priority`, `state`;
  - timestamps: `onset`, `candidate`, `dispatched`, `acked`, `on_scene`, `resolved`;
  - `team_id`, `evidence`, `crop_key` (blurred), `outcome`.
- **TraceStep:** `incident_id`, `seq`, `tool`, `input`, `output`, `latency_ms`, `model`.
- **Team:** `id`, `name`, `post_xy`, `status`, `last_seen`.

## 10. Non-functional requirements

| Area | Requirement |
|---|---|
| Latency | Under 2 s of pipeline overhead per decision, not counting the deliberate immobility window. HIGH candidate → EMT notification in under 3 s. |
| Throughput | 2 or more cameras at 5 fps on one c8g instance (measured and reported) |
| Availability | Worker heartbeat every 5 s; alarm if it's missing for more than 30 s; per-feed health |
| Fail-safe | Internal errors send incidents to human review. Incidents are never silently dropped. |
| Security | HTTPS only, least-privilege IAM, secrets in SSM, scoped expiring demo tokens, audit log |
| Privacy | See §11 |
| Cost | AWS Budgets alarms; $ per camera-hour reported |
| Accessibility | EMT card works in darkness and sunlight: high contrast, large type, touch targets of 48 px or more, one-handed use, sound + vibration + visual alerts |
| Reproducibility | Pinned dependencies (`uv.lock`), CDK, a one-command deploy, scripted evaluation |

## 11. Privacy, safety, and responsible use

The competition rules prohibit entries that create "material safety, privacy, security, discrimination, or surveillance risks without appropriate safeguards." MoshSpot's safeguards:

- **Purpose limitation:** the system detects medical emergencies and nothing else.
- **No identity:**
  - No face recognition, no identity features, no tracking across sessions.
  - Track IDs are short-lived.
  - Cameras share only floor coordinates.
- **Blur at the source:** every image leaving the vision worker has heads blurred. The blur regions come from pose keypoints, which works even on faces too small for a face detector; a face detector is the backup.
- **Minimal retention:**
  - Raw video lives only in RAM.
  - Incident clips (about ±10 s) are blurred, encrypted, and expire after 7 days.
- **Access control:** role-based access, plus an audit log of every view of incident media.
- **Human control:** humans approve anything below HIGH priority, and only humans can dismiss an incident.
- **Honesty about limits:**
  - Failure modes are published.
  - "No alert" never means "no emergency."
  - Human spotters stay in place; MoshSpot supports them.
- **Fairness:** detection performance is reported across lighting, clothing, body size, and pose, and gaps are stated as limitations.
- **Data rights:** footage comes only from consenting participants or properly licensed datasets.

## 12. Evaluation plan

### 12.1 Data

| Source | Used for | Licence |
|---|---|---|
| Tier 1 team micro-shoot (2 sessions) | Collapses vs look-alikes. Session 1 = dev, session 2 = held-out test. | Own, consented |
| Tier 2 volunteer crowd shoot (optional) | Occlusion, help-ring, demo video | Own, consented |
| [Okutama-Action](http://okutama-action.org/) | Lying, sitting, and standing people seen from drones (10–45 m) | CC BY-NC-SA 3.0 |
| [SARD](https://ieee-dataport.org/documents/search-and-rescue-image-dataset-person-detection-sard) | Lying and "injured" poses from the air | IEEE Dataport terms |
| [MEVA](https://mevadata.org/) | False alerts and sit-down / stand-up look-alikes, from fixed elevated cameras | CC BY 4.0 |
| MOT20 | False alerts in very dense crowds | CC BY-NC-SA 3.0 |
| Multiple Cameras Fall, UR Fall, Le2i, CAUCAFall | Real falls (indoor) for posture unit metrics | Research licences; check each |
| Pexels / Pixabay / CC-BY clips | False alerts under concert lighting | Check licence per clip |

No public dataset shows a person collapsing inside a dense concert crowd. That gap is why the staged shoots exist, and the report will say so.

### 12.2 Metrics

- Every metric in §4.
- A per-stage latency breakdown: detection, verification, dispatch.
- Robustness slices: density, lighting, occlusion, distance, camera.

### 12.3 Baselines and ablations

| Variant | What it tests |
|---|---|
| B1: box aspect ratio + the same immobility timer | The common tutorial approach |
| B2: pose angle in pixel space, no calibration | Whether calibration adds value |
| **Ours:** posture in world coordinates | Full method |
| ± help-ring cue | Recall on occluded takes |
| ± agent verification, ± `look_closer` | Precision gained vs latency added |

### 12.4 COOL benchmark

- **Configurations:**
  - c8g + COOL;
  - c8g + stock `opencv-python` 5;
  - c7i (x86) + stock.
- **Workload:** the exact vision-worker pipeline on the same clips.
- **Reported:**
  - per-stage ms: resize/letterbox, DNN, post-processing, optical flow, blur;
  - end-to-end fps;
  - CPU utilization;
  - **$ per camera-hour**.
- **Evidence:** `cv2.getBuildInformation()` captured on each run; scripts and raw CSVs committed.

### 12.5 Failure analysis

A gallery of misses and false alerts, sorted into categories:

- occlusion;
- lying straight away from the camera;
- darkness or strobes;
- far distance;
- look-alikes (sitting, resting).

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Pose models miss small people | **Fixed on Day 1:** top-down crops raised coverage from 0.5 to 6.0 people per frame, 99% with pose, at 21 fps on a laptop CPU |
| People lying down score low (0.30–0.40 vs 0.86 standing); one mid-fall frame was missed | Tracking bridges short gaps; light fine-tune on dev-session frames if recall is under target |
| ENGINE_NEW can't load the chosen model | Fall back to YOLOv8n (validated by OpenCV) or ENGINE_CLASSIC, staying inside `cv.dnn` |
| Dense-crowd occlusion | Help-ring cue and a second camera; documented as a limitation |
| Too little data or overfitting | Held-out session 2; public datasets for false-alarm rate |
| Scope creep with 1–2 people | Only P0 until Oct 16; freeze Oct 21 |
| AWS cost through judging (to Nov 9) | Small instance, Budgets alarms, COOL and Bedrock fees checked on Day 1 |
| Consent and licensing | Signed releases; licensed datasets only; attribution in the report |
| Model licence (Ultralytics is AGPL-3.0) | Stated in the report; Apache-2.0 RTMO named as the production path |

## 14. Open questions

1. Final product name. ("MoshSpot" is the working name.)
2. Do the team's AWS credits cover Claude on Bedrock, or do we use Nova Lite?
3. What is the COOL Marketplace fee on the chosen c8g size after the 7-day trial?
4. Tier 2 volunteer shoot: go or no-go by **Wed Oct 7**.
5. Demo venue map: the shoot site itself, or a fictional arena map with the shoot area overlaid?
6. If the team is one person, apply the cuts in [STRATEGY.md §5](STRATEGY.md).

## 15. References

- Competition: [Devpost](https://opencv26.devpost.com/) · [opencv.org page](https://opencv.org/opencv-ai-competition-2026/) · [rules](https://opencv26.devpost.com/rules)
- OpenCV 5: [release deep dive](https://opencv.org/opencv-5/) · [COOL](https://opencv.org/cool/) · [COOL Graviton4 AMI](https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs)
- Problem: the sources in §2
- Data: the sources in §12.1
