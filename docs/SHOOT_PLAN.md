# MoshSpot — Footage Plan

**Companion docs:** [PRD.md](PRD.md) · [STRATEGY.md](STRATEGY.md)

No public dataset shows a person collapsing *inside a dense concert crowd*. So we combine free public data with short staged shoots that we control.

| Tier | What | Who | When | Required? |
|---|---|---|---|---|
| **0** | Public datasets | — | Now | Yes: development and false-alarm rate |
| **1** | Team micro-shoot | The two of you | **Sat Oct 10** (daylight, dev set) and **Sat Oct 17** (dusk/night, held-out test set) | **Yes** |
| **2** | Volunteer crowd shoot | 10–25 volunteers | Sat Oct 17 afternoon | Optional. **Go/no-go Wed Oct 7.** |

---

## 1. Tier 0: public datasets (no shoot needed)

| Dataset | What it gives us | Licence | Where |
|---|---|---|---|
| **Okutama-Action** | Drone video (10–45 m, 45°/90° camera angles) of people **lying**, sitting, and standing among others. The best public match for an elevated view of someone lying down. Start with the test set (720p frames + labels, ~1.5 GB). | CC BY-NC-SA 3.0 | [okutama-action.org](http://okutama-action.org/) |
| **MEVA** | Fixed elevated outdoor cameras plus some UAV footage. Includes sit-down / stand-up activities, which are look-alikes for false-alarm tests. | CC BY 4.0 | [mevadata.org](https://mevadata.org/) |
| **MOT20** | Very dense crowds from elevated cameras, for false-alarm tests | CC BY-NC-SA 3.0 | motchallenge.net |
| **Multiple Cameras Fall Dataset** | Real falls and look-alikes from 8 cameras mounted high in room corners | Research use | Université de Montréal |
| **UR Fall / Le2i / CAUCAFall** | Real falls (indoor), for posture unit metrics | Research licences; check each | Dataset sites |
| **SARD** | Drone images of lying and "injured" poses | IEEE Dataport terms | [IEEE Dataport](https://ieee-dataport.org/documents/search-and-rescue-image-dataset-person-detection-sard) |
| **Pexels / Pixabay / CC-BY clips** | Crowds under real concert lighting, for false-alarm tests | Check the licence per clip | Search with licence filters |

**Rules for Tier 0:**

- Log every source in `data/SOURCES.csv` (name, URL, licence, date downloaded).
- Raw data never goes into git (`data/` is gitignored).
- Credit every source in the report appendix.
- **No regular YouTube concert footage.** The rules require rights to all media.

## 2. Tier 1: team micro-shoot (required)

Two people, one phone each, and about two hours per session. One person "collapses" while the other plays a bystander. Both cameras record continuously from tripods.

### 2.1 Location

- An elevated spot **4–10 m above open, flat ground**. Examples:
  - a 2nd–3rd floor balcony or window;
  - a parking-garage top deck overlooking a lot;
  - bleachers above a field.
- **Grass is best** for safe falls.
- Ask permission if the space isn't public. Pick quiet times so no members of the public end up on camera.
- Bonus: a second vantage point with an overlapping view enables the `cross_check_camera` scenarios.

### 2.2 Equipment checklist

- [ ] 2 phones with tripods or clamps, plus power banks
- [ ] ChArUco board, printed A3 or larger and mounted flat on foam board (`tools/make_charuco.py`, to be written)
- [ ] Measuring tape (20 m or longer), plus tape, chalk, or small cones for 8–12 floor markers
- [ ] Gym or yoga mats if the ground is hard
- [ ] A take sign (whiteboard or paper and a marker); clapping is enough for sync
- [ ] Session 2 only: coloured LED lights or a party light with batteries
- [ ] Printed release forms (§5) and pens
- [ ] First-aid kit and water

### 2.3 Camera settings (consistent geometry matters more than resolution)

- 1080p or 4K at 30 fps, landscape.
- **Lock focus and exposure** (AE/AF lock).
- **Keep zoom at 1×** and never change it after calibrating.
- **Turn off video stabilization** if the phone allows it. Stabilization warps the geometry.
- HDR off.
- Mark each tripod spot; cameras must not move during a session. If one gets bumped, re-record the calibration.
- **Calibration video per camera**, at the start and again at the end: 30–60 s of the ChArUco board moved through the whole frame at different tilts and distances.

### 2.4 Floor markers (feeds both calibration and ground truth)

1. Lay out **8–12 markers** at measured positions on the ground. Put the origin at one corner, with x running across the view and y running away from the cameras. Spread them across near, mid, and far distances.
2. Write the positions to `markers.csv` (`id,x_m,y_m`). Photograph the layout.
3. Check that every marker is visible from both cameras.
4. Sketch the zones on paper: "Stage", "Front barrier", "Section A/B/C", "EMT post 1", "EMT post 2". This becomes `venue.json`.

### 2.5 Scenario matrix: session 1 (Sat Oct 10, daylight, dev set)

**Distance bands** (from the point on the ground below the camera): near = 5–10 m, mid = 10–20 m, far = 20–35 m.

**Orientation** (where the fallen body points, relative to the camera):

| Term | Meaning |
|---|---|
| Across | The body lies sideways across the view |
| Away | Head points away from the camera. **This is the hard case.** |
| Toward | Head points toward the camera |

**Collapses (expected: alert)**

| Take | Event | Orientation | Distance | Bystander |
|---|---|---|---|---|
| C01–C03 | Sudden collapse | Across | Near / mid / far | None |
| C04–C06 | Sudden collapse | **Away** | Near / mid / far | None |
| C07–C08 | Sudden collapse | Toward | Mid / far | None |
| C09–C10 | Slow slump (knees → sitting → lying) | Across | Mid / far | None |
| C11–C12 | Collapse face-down | Diagonal | Near / far | None |
| C13–C14 | Collapse | Any | Mid / far | Kneels beside them within 10 s |
| C15–C16 | Collapse | Any | Mid / far | Waves both arms overhead |
| C17–C18 | Collapse **partly hidden** behind the standing bystander | Any | Mid / far | Stands between the camera and the person |

**Look-alikes (expected: no auto-dispatch)**

| Take | Event | Distance | Expected priority |
|---|---|---|---|
| N01–N02 | Sits on the ground and keeps moving (talking, phone) | Mid / far | LOW |
| N03 | Lies on their back using a phone (hands moving), 30 s | Mid | LOW |
| N04 | Crouches to tie shoes, 15 s | Mid | None / LOW |
| N05 | Picks something up | Near | None |
| N06 | Kneels for 20 s | Far | None / LOW |
| N07 | Stretches on the ground | Mid | LOW |
| N08 | Jumps or dances in place, 20 s | Mid | None |
| N09 | Bends over with hands on knees, 15 s | Far | None |
| N10 | Lies down **deliberately still**, 30 s, no fall | Mid | MEDIUM → human review. This is the correct outcome, not a miss. |
| N11 | Both sit together and chat | Mid | LOW |

That's 29 takes × 2 cameras = 58 clips. At about 60 s per take plus resets, budget roughly 75 minutes.

### 2.6 Scenario matrix: session 2 (Sat Oct 17, dusk → dark, held-out test set)

- Repeat **C01, C02, C04, C05, C09, C13, C15, C17, N01, N03, N04, N08, N10** twice:
  1. at dusk;
  2. in the dark with coloured lights.
- Optional: a strobe pass, only if nobody present is photosensitive.
- Session 2 is **never used for tuning**. It exists only for the final numbers.

## 3. Tier 2: volunteer crowd shoot (optional)

- **Go/no-go on Wed Oct 7:** go only if 10 or more volunteers are confirmed and the location is booked.
- 90 minutes, with snacks and thanks.
- **Densities:**
  - loose: about 1 person per 2 m²;
  - packed: shoulder to shoulder, standing still. **No pushing, ever.**
- **Scenarios:**
  - collapse inside the group (occluded);
  - the crowd keeps "dancing" and doesn't help;
  - a help ring forms;
  - **two people go down near each other** (cluster alarm);
  - look-alikes: groups sitting down.
- **Never:** crowd surfing, lifting people, pushing, or real crushing.

## 4. Safety

- One person is the **safety lead** and doesn't act in that take.
- Every fall is controlled: knees, then hip, then roll onto the side or back, onto grass or a mat. **No backward falls and no head impacts.** Practise each fall slowly first.
- Use a stop word. Anyone can stop any take.
- Nobody holds their breath or simulates a seizure.
- Take water and breaks, and watch the weather.
- If a member of the public gets worried, stop and explain. Carry a note: "Staged safety-research filming."

## 5. Consent and release

Everyone on camera signs **before** filming. Don't film minors. The competition rules give OpenCV and AWS a licence to submitted materials, including the video, so the release must cover that.

> *Template only, not legal advice. Adapt it as needed.*
>
> **Video Participation Release — MoshSpot (OpenCV AI Competition 2026)**
>
> I, ______________, agree to be filmed by Team MoshSpot on ____/____/2026 acting in staged scenarios, including pretending to collapse, for a computer-vision research project.
>
> I understand and agree that the footage and images of me may be:
> (a) used to develop and evaluate the MoshSpot system;
> (b) included in the team's competition submission (report, demo, and a publicly viewable video) for the OpenCV AI Competition 2026, whose rules grant OpenCV and Amazon Web Services a perpetual, worldwide licence to submitted materials;
> (c) posted publicly by the team (for example on YouTube, Devpost, or GitHub) in connection with the project.
>
> Faces will be blurred in published dataset images where practical, but I understand I may be recognizable in the demo video. I am 18 or older. I confirm the scenarios are staged, that I can stop at any time, and that I may withdraw consent for future use by notifying the team before **Oct 20, 2026**.
>
> Signature: ______________ Date: ________ Contact: ______________

## 6. Run of show (each session)

| Time | Step |
|---|---|
| 0:00 | Set up markers, measure and record `markers.csv`, mount cameras, lock settings |
| 0:30 | Record calibration videos (ChArUco) on each camera |
| 0:40 | Safety briefing, sign releases, practise falls |
| 0:50 | Takes (§2.5 / §2.6) |
| 2:05 | Record end-of-session calibration videos |
| 2:10 | Tear down; **copy footage to two places before leaving** |

## 7. Per-take procedure

1. Hold the **take sign** (e.g., `S1-C04`) up to both cameras.
2. **Clap** once, visible to both cameras. This syncs them.
3. **"Action":** 10 s of normal activity (standing, chatting, swaying).
4. The director calls the event. The logger notes the clock time.
5. **Hold for 30 s.** For collapses, stay still. For look-alikes, behave naturally.
6. **"Cut":** the actor gets up. The logger records the landing spot: nearest marker plus dx/dy in metres.

## 8. Ground-truth log (`data/shoots/<session>/takes.csv`)

`take_id, session, cam_a_file, cam_b_file, event, expected, orientation, distance_band, nearest_marker, dx_m, dy_m, occluded, bystander, lighting, onset_tc_a, onset_tc_b, notes`

The `onset_tc_*` columns (collapse-onset timecodes) are filled in during labelling (`tools/label_events.py`, to be written). Everything else is filled in on site.

## 9. Data handling

- File names: `<session>_<cam>_<take>.mp4`. Alternatively, keep continuous recordings and cut them later at the clap times.
- Back up to two locations the same day. Raw footage never goes into git.
- Published stills, clips, and dataset samples get heads blurred, unless the person agreed otherwise and the clip is for the demo video.

## 10. After each shoot

1. Calibrate each camera from its ChArUco video, then fix its pose from the floor markers (`tools/calibrate.py`, to be written). Check the reprojection error.
2. Label the collapse onsets.
3. Session 1 → `dev`. Session 2 → `test`. Never tune on `test`.
