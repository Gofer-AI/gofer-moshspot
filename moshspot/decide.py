"""Decision logic: from per-frame people to incidents an EMT should be sent to.

What crowd cameras show (measured on MoshSpot Sim runs; see docs/DEVLOG.md):

- A collapse is visible for about a second. The person's height ratio drops from about 1.1 to under 0.8,
  then they vanish behind the crowd. In a crowd this dense the tracker then hands their identity to a
  neighbour, so "did the same person stand up again?" can't be answered from a track.
- What lasts is the reaction. Within 3-15 s, two to four bystanders crouch around the person about a metre
  away, often one with an arm up, and stay. That help ring is the trigger. The fall, when it was seen,
  gives the onset time and the explanation.
- Low scenery near the floor can look like crouching people. Each camera learns those spots from its first
  seconds of video and ignores them (StaticClutter), like a calibration pass at install time.

The IncidentAgent decides each incident no earlier than 13 s after onset, by which time someone who fell
and got straight back up is standing again. It checks the centre of the ring, can look closer at the real
pixels, then closes the incident or alerts. Every step goes to the incident's trace. Guardrail: it closes
an incident only on visual evidence of someone standing at the centre; otherwise it alerts.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

TRACK_GATE = 0.9          # m between a track and a detection in consecutive frames
TRACK_TTL = 3.0           # s a lost track is kept
UPRIGHT_HR = 0.9          # height ratio of someone standing
FALL_HR = 0.8             # a fall ends below this
FALL_WINDOW = 1.0         # s from standing to below FALL_HR
LOW_HR = (0.35, 0.85)     # crouching or kneeling
LOW_MAX_ASPECT = 1.3
RING_PAIR = 2.4           # m; helpers on opposite sides of a person are up to ~2 m apart
RING_RADIUS = 1.8         # m around a ring's centre
RING_PERSIST = (10, 16)   # a ring seen in >= 10 of the last 16 frames (about 3 s at 5 fps)
CLUTTER_SECONDS = 20.0    # s of video each camera uses to learn static clutter
CLUTTER_CELL = 0.75       # m
CLUTTER_RATE = 0.3        # low detections in at least this share of warm-up frames: scenery
FALL_LOOKBACK = 40.0      # s before a ring to look for the fall that started it
FALL_NEAR_RING = 2.5      # m
DECIDE_AFTER_ONSET = 13.0
UNSEEN_ONSET = 10.0       # s before the ring, as the onset estimate when no fall was seen
INCIDENT_RADIUS = 3.0     # m; rings this close belong to one incident
INCIDENT_MEMORY = 600.0   # s an alerted incident keeps absorbing rings (helpers, then EMTs, kneel there)
CENTRE_STANDING = 0.6     # m; someone upright this close to the centre is the person, back on their feet
CLUSTER_RADIUS, CLUSTER_TIME = 10.0, 180.0
ZOOM_DROP = 0.4           # a fall this deep makes the agent look closer at the spot on its own
ZOOM_AFTER = 8.0          # s after the fall: helpers have usually gathered by then
ZOOM_CONFIRM = 3.0        # s later, a second look must agree: helpers stay, occlusion artifacts don't


@dataclass
class Sample:
    t: float
    X: float
    Y: float
    hr: float


@dataclass
class Track:
    id: int
    samples: deque = field(default_factory=lambda: deque(maxlen=60))
    fell: bool = False

    @property
    def last(self):
        return self.samples[-1]

    def between(self, t0, t1):
        return [s for s in self.samples if t0 <= s.t <= t1]


@dataclass
class FallCandidate:
    t: float
    X: float
    Y: float
    camera: str
    track: int
    drop: float  # height ratio lost in the fall


class CameraTracker:
    """Associates detections frame to frame by floor position and reports fast drops (possible falls)."""

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.tracks = []
        self._next_id = 0

    def update(self, t, people):
        samples = [Sample(t, p["X"], p["Y"], p["hr"]) for p in people]
        live = [tr for tr in self.tracks if t - tr.last.t <= TRACK_TTL]
        existing = len(live)
        matched_tracks, matched_samples = set(), set()
        if live and samples:
            cost = np.hypot(np.array([[tr.last.X] for tr in live]) - [[s.X for s in samples]],
                            np.array([[tr.last.Y] for tr in live]) - [[s.Y for s in samples]])
            for i, j in zip(*linear_sum_assignment(np.where(cost <= TRACK_GATE, cost, 1e6))):
                if cost[i, j] <= TRACK_GATE:
                    live[i].samples.append(samples[j])
                    matched_tracks.add(i)
                    matched_samples.add(j)
        for j, sample in enumerate(samples):
            if j not in matched_samples:
                track = Track(self._next_id)
                self._next_id += 1
                track.samples.append(sample)
                live.append(track)
        self.tracks = live
        falls = []
        for i, track in enumerate(live):
            fall = self._check(track, t, lost_now=i < existing and i not in matched_tracks)
            if fall:
                falls.append(fall)
        return falls

    def _check(self, track, t, lost_now):
        if track.fell or (lost_now and t - track.last.t > 0.5):
            return None  # one report per track; "vanished" only counts right after the track disappears
        before = track.between(t - FALL_WINDOW - 2.0, t - FALL_WINDOW + 0.2)
        recent = track.between(t - FALL_WINDOW, t)
        if len(before) < 3 or not recent or np.median([s.hr for s in before]) < UPRIGHT_HR:
            return None
        low = min(s.hr for s in recent)
        drop = np.median([s.hr for s in before]) - low
        if low < FALL_HR and drop >= 0.25 and (lost_now or track.last.hr < FALL_HR + 0.05):
            track.fell = True
            return FallCandidate(t, before[-1].X, before[-1].Y, self.camera_id, track.id, round(float(drop), 2))
        return None


def barricade_shadow(camera, venue, depth=4.0):
    """For a camera on the stage side of the front barricade: the rows right behind it, whose legs it hides."""
    barricade = venue.get("barricade_y")
    if barricade is None or camera.center[1] <= barricade:
        return None
    return lambda x, y: barricade - depth <= y <= barricade


class StaticClutter:
    """Floor cells where "crouching people" keep appearing during a camera's first seconds: scenery."""

    def __init__(self, seconds=CLUTTER_SECONDS):
        self.seconds = seconds
        self.counts = defaultdict(int)
        self.frames = 0
        self.start = None
        self.masked = None

    def observe(self, t, points):
        if self.masked is not None:
            return
        self.start = t if self.start is None else self.start
        self.frames += 1
        for cell in {self._cell(x, y) for x, y in points}:
            self.counts[cell] += 1
        if t - self.start >= self.seconds:
            self.masked = {cell for cell, n in self.counts.items() if n >= CLUTTER_RATE * self.frames}

    @property
    def ready(self):
        return self.masked is not None

    def blocked(self, x, y):
        cx, cy = self._cell(x, y)
        return any((cx + dx, cy + dy) in self.masked for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    @staticmethod
    def _cell(x, y):
        return int(np.floor(x / CLUTTER_CELL)), int(np.floor(y / CLUTTER_CELL))


class RingDetector:
    """Persistent groups of crouching people in one camera: bystanders around someone on the ground.

    `hidden_legs(x, y)` marks floor spots where this camera can't see people's legs, such as the front
    rows behind a barricade seen from the stage: everyone there looks short.
    """

    def __init__(self, camera_id, hidden_legs=None):
        self.camera_id = camera_id
        self.hidden_legs = hidden_legs
        self.clutter = StaticClutter()
        self.history = deque(maxlen=RING_PERSIST[1])

    def update(self, t, people):
        low = [p for p in people if LOW_HR[0] < p["hr"] < LOW_HR[1] and p["aspect"] < LOW_MAX_ASPECT
               and not (self.hidden_legs and self.hidden_legs(p["X"], p["Y"]))]
        self.clutter.observe(t, [(p["X"], p["Y"]) for p in low])
        if not self.clutter.ready:
            return []
        low = [p for p in low if not self.clutter.blocked(p["X"], p["Y"])]
        points = np.array([[p["X"], p["Y"]] for p in low]).reshape(-1, 2)
        rings = []
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                if np.hypot(*(points[i] - points[j])) > RING_PAIR:
                    continue
                members = np.hypot(*(points - (points[i] + points[j]) / 2).T) <= RING_RADIUS
                centre = points[members].mean(axis=0)
                if all(np.hypot(*(centre - c)) > 1.0 for c, _, _ in rings):
                    rings.append((centre, int(members.sum()), any(low[k].get("arm_up") for k in np.flatnonzero(members))))
        self.history.append([c for c, _, _ in rings])
        persistent = []
        for centre, helpers, arm_up in rings:
            seen = sum(any(np.hypot(*(centre - c)) < 1.2 for c in frame) for frame in self.history)
            if seen >= RING_PERSIST[0]:
                persistent.append((centre, helpers, arm_up))
        return persistent


@dataclass
class Incident:
    id: str
    onset: float
    ring_t: float
    X: float
    Y: float
    decide_at: float
    cameras: set
    fall: FallCandidate | None
    helpers: int
    arm_up: bool
    source: str = "ring"     # what opened it: a persistent help ring, or the agent's own zoomed looks
    state: str = "watching"  # watching -> alerted | closed | review
    priority: str | None = None
    cluster: str | None = None
    trace: list = field(default_factory=list)

    def log(self, t, step, **detail):
        self.trace.append({"t": round(t, 2), "step": step, **detail})


class SpotEvidence:
    """Recent detections from every camera, queried around a floor spot: the agent's perception tool."""

    def __init__(self, cameras, horizon=40.0, image_size=(1280, 720)):
        self.cameras = cameras  # id -> Camera
        self.frames = {cid: deque() for cid in cameras}
        self.horizon = horizon
        self.image_size = image_size

    def add(self, camera_id, t, people):
        rows = np.array([[p["X"], p["Y"], p["hr"], p["aspect"], p.get("posture") == "lying"] for p in people],
                        dtype=float).reshape(-1, 5)
        frames = self.frames[camera_id]
        frames.append((t, rows))
        while frames and frames[0][0] < t - self.horizon:
            frames.popleft()

    def best_cameras(self, X, Y):
        """Cameras that see the spot, closest view (tallest person in pixels) first."""
        views = []
        for cid, camera in self.cameras.items():
            point = np.array([X, Y, 0.9])
            pixel = camera.project([point])[0]
            in_front = (camera.R @ (point - camera.center))[2] > 0
            if in_front and 0 <= pixel[0] < self.image_size[0] and 0 <= pixel[1] < self.image_size[1]:
                views.append((camera.pixel_height((X, Y), 1.8), cid))
        return [cid for _, cid in sorted(views, reverse=True)]

    def around(self, camera_id, X, Y, t0, t1):
        """Share of frames in [t0, t1] with someone standing, or someone lying, at the spot."""
        frames = [rows for t, rows in self.frames[camera_id] if t0 <= t <= t1]
        if not frames:
            return None
        standing = lying = 0
        for rows in frames:
            d = np.hypot(rows[:, 0] - X, rows[:, 1] - Y)
            standing += bool(((d < CENTRE_STANDING) & (rows[:, 2] >= UPRIGHT_HR)).any())
            lying += bool(((d < 1.0) & ((rows[:, 2] < LOW_HR[0]) | (rows[:, 3] >= LOW_MAX_ASPECT) | (rows[:, 4] > 0))).any())
        return {"frames": len(frames), "standing": round(standing / len(frames), 2), "lying": round(lying / len(frames), 2)}


class IncidentAgent:
    """Turns rings and falls into incidents, decides each one, and logs every step.

    `look_closer(camera_id, X, Y, t)` is optional. It re-runs detection on a zoomed crop of the real frame;
    a person seen lying up close overrides "standing" evidence, and a person seen standing can close it.
    """

    def __init__(self, evidence, look_closer=None, on_alert=None, dispatch_zoom=False):
        self.evidence = evidence
        self.look_closer = look_closer
        self.on_alert = on_alert
        self.dispatch_zoom = dispatch_zoom  # zoom-opened incidents go to a dispatcher for review unless set
        self.incidents = []
        self.falls = deque()
        self.zoom_queue = deque()  # (fall, when) checks the agent scheduled itself
        self.zooms = 0
        self._seq = 0

    def add_fall(self, fall):
        self.falls.append(fall)
        while self.falls and self.falls[0].t < fall.t - FALL_LOOKBACK - 5:
            self.falls.popleft()
        if self.look_closer and fall.drop >= ZOOM_DROP:
            self.zoom_queue.append((fall, fall.t + ZOOM_AFTER, None))

    def _covered(self, X, Y, t):
        return any(np.hypot(inc.X - X, inc.Y - Y) <= INCIDENT_RADIUS
                   and t - inc.ring_t <= (INCIDENT_MEMORY if inc.state == "alerted" else 120.0) for inc in self.incidents)

    def _check_fall_up_close(self, fall, t, first_look):
        """Active perception: after a deep fall, zoom in on the spot twice, a few seconds apart.

        Two looks that both show helpers crouching around the spot (or someone lying there) open an incident.
        """
        if self._covered(fall.X, fall.Y, t):
            return
        cams = self.evidence.best_cameras(fall.X, fall.Y)
        if not cams:
            return
        self.zooms += 1
        closer = self.look_closer(cams[0], fall.X, fall.Y, t)
        if not closer or not (closer["crouching_around"] >= 2 or closer["lying"]):
            return
        look = {"t": round(t, 2), "step": "look_closer", "camera": cams[0], "found": closer}
        if first_look is None:
            self.zoom_queue.append((fall, t + ZOOM_CONFIRM, {**look, "why": "deep fall seen; checking the spot up close"}))
            return
        inc = self._open(t, fall.X, fall.Y, cams[0], fall, closer["crouching_around"], False)
        inc.source = "zoom"
        inc.trace[1:1] = [first_look, {**look, "why": "second look, to rule out a passing occlusion"}]

    def add_ring(self, camera_id, t, centre, helpers, arm_up):
        X, Y = float(centre[0]), float(centre[1])
        for inc in self.incidents:
            memory = INCIDENT_MEMORY if inc.state == "alerted" else 120.0
            if np.hypot(inc.X - X, inc.Y - Y) <= INCIDENT_RADIUS and t - inc.ring_t <= memory:
                if camera_id not in inc.cameras and inc.state == "watching":
                    inc.log(t, "corroborated", camera=camera_id, helpers=helpers)
                inc.cameras.add(camera_id)
                inc.helpers, inc.arm_up = max(inc.helpers, helpers), inc.arm_up or arm_up
                return inc
        nearby = [f for f in self.falls if t - FALL_LOOKBACK <= f.t <= t and np.hypot(f.X - X, f.Y - Y) <= FALL_NEAR_RING]
        fall = min(nearby, key=lambda f: np.hypot(f.X - X, f.Y - Y)) if nearby else None
        inc = self._open(t, X, Y, camera_id, fall, helpers, arm_up)
        inc.log(t, "help_ring", camera=camera_id, helpers=helpers, arm_up=arm_up, X=round(X, 2), Y=round(Y, 2))
        return inc

    def _open(self, t, X, Y, camera_id, fall, helpers, arm_up):
        onset = fall.t if fall else t - UNSEEN_ONSET
        self._seq += 1
        inc = Incident(f"ms-{self._seq}", onset, t, X, Y, max(t, onset + DECIDE_AFTER_ONSET), {camera_id}, fall,
                       helpers, arm_up)
        if fall:
            inc.log(fall.t, "fall_seen", camera=fall.camera, track=fall.track, height_drop=fall.drop,
                    X=round(fall.X, 2), Y=round(fall.Y, 2))
        self.incidents.append(inc)
        return inc

    def step(self, t):
        due = [item for item in self.zoom_queue if item[1] <= t]
        self.zoom_queue = deque(item for item in self.zoom_queue if item[1] > t)
        for fall, _, first_look in due:
            self._check_fall_up_close(fall, t, first_look)
        alerts = []
        for inc in self.incidents:
            if inc.state == "watching" and t >= inc.decide_at:
                alert = self._decide(inc, t)
                if alert:
                    alerts.append(alert)
        return alerts

    def _decide(self, inc, t):
        cams = self.evidence.best_cameras(inc.X, inc.Y)
        views = {cid: ev for cid in cams[:2] if (ev := self.evidence.around(cid, inc.X, inc.Y, t - 2.0, t))}
        inc.log(t, "spot_evidence", cameras=cams[:2], views=views)
        seen_standing = views.get(cams[0], {}).get("standing", 0) if cams else 0
        standing, lying = seen_standing >= 0.5, False
        if self.look_closer and cams:
            closer = self.look_closer(cams[0], inc.X, inc.Y, t)
            inc.log(t, "look_closer", camera=cams[0], found=closer)
            if closer:
                # one zoomed frame can confirm what the last 2 s suggest, or reveal someone lying,
                # but it can't dismiss a patient on its own
                lying = closer["lying"]
                if closer["standing"] and not standing and seen_standing < 0.25:
                    inc.log(t, "guardrail", rule="one zoomed frame can't dismiss a patient",
                            detail=f"the zoom showed someone standing, but they stood there in only {seen_standing:.0%} of the last 2 s")
                standing = standing or (closer["standing"] and seen_standing >= 0.25)
        if standing and not lying:
            inc.state = "closed"
            inc.log(t, "close", reason="someone is standing at the centre of the group: the person got back up")
            return None
        if inc.source == "zoom" and not self.dispatch_zoom:
            # Measured on the dev run: zoom-opened incidents were mostly occlusion artifacts, so a person decides.
            inc.state, inc.priority = "review", "REVIEW"
            inc.log(t, "request_human_review", reason="deep fall and people crouching up close, but no persistent help ring")
            return None
        return self._alert(inc, t, lying)

    def _alert(self, inc, t, seen_lying):
        inc.state, inc.priority = "alerted", "HIGH"
        nearby = [o for o in self.incidents if o is not inc and o.state == "alerted" and t - o.onset <= CLUSTER_TIME
                  and np.hypot(o.X - inc.X, o.Y - inc.Y) <= CLUSTER_RADIUS]
        if nearby:
            inc.cluster = nearby[0].cluster or f"cluster-{nearby[0].id}"
            for other in nearby:
                other.cluster = inc.cluster
            inc.log(t, "cluster", with_incidents=[o.id for o in nearby], note="several people down close together: possible crowd crush")
        inc.log(t, "alert", priority=inc.priority, helpers=inc.helpers, fall_seen=inc.fall is not None, seen_lying=seen_lying)
        alert = {"t": round(t, 2), "X": round(inc.X, 2), "Y": round(inc.Y, 2), "priority": inc.priority,
                 "camera": sorted(inc.cameras)[0], "incident_id": inc.id, "onset": round(inc.onset, 2),
                 "helpers": inc.helpers, "fall_seen": inc.fall is not None, "cluster": inc.cluster}
        if self.on_alert:
            self.on_alert(inc, alert)
        return alert
