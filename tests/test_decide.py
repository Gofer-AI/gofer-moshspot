"""Decision logic on synthetic per-frame people: falls, help rings, clutter, and the agent's calls."""

import numpy as np

from moshspot.decide import (CLUTTER_SECONDS, DECIDE_AFTER_ONSET, CameraTracker, IncidentAgent, RingDetector,
                             SpotEvidence, barricade_shadow)
from moshspot.geometry.camera import Camera

FPS = 5
K = [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]]
CAMERA = Camera.look_at(K, position=(0, -6, 8), target=(0, 14, 0))


def person(x, y, hr=1.1, aspect=0.4):
    return {"X": x, "Y": y, "hr": hr, "aspect": aspect}


def crowd(t):
    """A few people dancing in place far from the action."""
    return [person(-8 + 0.05 * np.sin(t + k), 20 + 2 * k) for k in range(4)]


def frames(seconds, start=0.0):
    return [round(start + k / FPS, 2) for k in range(int(seconds * FPS))]


def test_fast_drop_is_a_fall_and_slow_crouch_is_not():
    tracker = CameraTracker("cam")
    falls = []
    for t in frames(6):
        hr = 1.1 if t < 3 else 0.6  # collapse: standing, then down within one frame
        falls += tracker.update(t, [person(2, 10, hr)])
    assert len(falls) == 1 and abs(falls[0].X - 2) < 0.01 and falls[0].drop > 0.4

    tracker, falls = CameraTracker("cam"), []
    for t in frames(10):
        falls += tracker.update(t, [person(2, 10, max(0.7, 1.1 - 0.06 * max(0, t - 3)))])  # crouching slowly
    assert falls == []


def test_track_vanishing_right_after_a_drop_is_a_fall():
    tracker, falls = CameraTracker("cam"), []
    for t in frames(5):
        people = [person(2, 10, 1.1 if t < 3 else 0.75)] if t < 3.4 else []  # drops, then hidden by the crowd
        falls += tracker.update(t, people)
    assert len(falls) == 1


def helpers_around(x, y, n=3, hr=0.7):
    return [person(x + np.cos(a), y + np.sin(a), hr, 0.8) for a in np.linspace(0, 2 * np.pi, n, endpoint=False)]


def test_ring_is_found_after_warmup_and_clutter_is_ignored():
    detector = RingDetector("cam")
    found = []
    for t in frames(CLUTTER_SECONDS + 10):
        people = crowd(t) + [person(-3, 30, 0.6, 0.9)]  # a low "person" that is really scenery
        if t >= CLUTTER_SECONDS + 2:
            people += helpers_around(4, 12)
        people += [person(-3.8, 30, 0.6, 0.9)] if t >= CLUTTER_SECONDS + 2 else []  # ...pairing with scenery
        found += [(t, centre) for centre, helpers, _ in detector.update(t, people)]
    assert found, "persistent helpers should form a ring"
    first_t, centre = found[0]
    assert CLUTTER_SECONDS + 2 + 1.5 <= first_t <= CLUTTER_SECONDS + 6
    assert np.hypot(centre[0] - 4, centre[1] - 12) < 0.5
    assert all(np.hypot(c[0] + 3, c[1] - 30) > 2 for _, c in found), "scenery learned during warm-up is ignored"


def test_barricade_hides_front_rows_from_stage_cameras_only():
    venue = {"barricade_y": 48.8}
    stage_cam = Camera.look_at(K, position=(-12, 50.6, 9.5), target=(-6, 36, 0))
    hidden = barricade_shadow(stage_cam, venue)
    assert hidden(0, 46) and not hidden(0, 40)
    assert barricade_shadow(CAMERA, venue) is None


def run_agent(people_at_centre, look_closer=None, ring_at=(0.0, 14.0)):
    evidence = SpotEvidence({"cam": CAMERA})
    agent = IncidentAgent(evidence, look_closer)
    alerts = []
    for t in frames(30):
        people = crowd(t) + people_at_centre(t)
        evidence.add("cam", t, people)
        if t == 5.0:
            agent.add_ring("cam", t, np.array(ring_at), 3, True)
        alerts += agent.step(t)
    return agent, alerts


def test_agent_alerts_when_nobody_stands_at_the_centre():
    agent, alerts = run_agent(lambda t: helpers_around(0, 14))
    assert len(alerts) == 1 and alerts[0]["priority"] == "HIGH"
    inc = agent.incidents[0]
    assert alerts[0]["t"] >= inc.onset + DECIDE_AFTER_ONSET
    assert [s["step"] for s in inc.trace] == ["help_ring", "spot_evidence", "alert"]


def test_agent_closes_when_the_person_got_back_up():
    agent, alerts = run_agent(lambda t: helpers_around(0, 14) + [person(0.1, 14.0, 1.1)])
    assert alerts == [] and agent.incidents[0].state == "closed"


def test_one_zoomed_frame_cannot_dismiss_a_patient():
    zoom = lambda camera_id, x, y, t: {"standing": True, "lying": False}  # a neighbour in the zoomed crop
    agent, alerts = run_agent(lambda t: helpers_around(0, 14), look_closer=zoom)
    assert len(alerts) == 1
    trace = agent.incidents[0].trace
    assert [s["step"] for s in trace][-3:] == ["look_closer", "guardrail", "alert"]
    assert "can't dismiss" in trace[-2]["rule"]


def test_second_nearby_alert_is_flagged_as_a_cluster():
    evidence = SpotEvidence({"cam": CAMERA})
    agent = IncidentAgent(evidence)
    alerts = []
    for t in frames(60):
        evidence.add("cam", t, crowd(t))
        if t == 5.0:
            agent.add_ring("cam", t, np.array([0.0, 14.0]), 2, False)
        if t == 20.0:
            agent.add_ring("cam", t, np.array([5.0, 14.0]), 2, False)
        alerts += agent.step(t)
    assert [a["cluster"] is not None for a in alerts] == [False, True]


def test_help_ring_upgrades_a_review_incident_to_an_alert():
    evidence = SpotEvidence({"cam": CAMERA})
    agent = IncidentAgent(evidence)
    inc = agent.add_ring("cam", 5.0, np.array([0.0, 14.0]), 2, False)
    inc.state, inc.source = "review", "zoom"  # as if the agent's zoomed looks had opened it
    alerts = []
    for t in frames(30, start=6.0):
        evidence.add("cam", t, crowd(t) + helpers_around(0, 14))
        if t == 10.0:
            agent.add_ring("cam", t, np.array([0.2, 14.1]), 3, True)
        alerts += agent.step(t)
    assert len(alerts) == 1 and inc.state == "alerted"
    assert "no longer just a review item" in [s for s in inc.trace if s["step"] == "help_ring"][-1]["note"]
