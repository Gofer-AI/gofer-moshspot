"""python3 -m unittest discover -s tests   (from the moshspot-sim folder)"""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from emt_router import EmtRouter  # noqa: E402

SNAP = json.load(open(ROOT / "tests" / "fixtures" / "sim_snapshot.json"))
EMPTY_VENUE = {"bounds": {"xmin": -30, "xmax": 30, "ymin": 0, "ymax": 48.2},
               "obstacles": [{"id": "FOH", "xmin": -4, "xmax": 4, "ymin": 13, "ymax": 19}],
               "emt_posts": [{"id": "SOUTH", "X": 0, "Y": 11.5}, {"id": "WEST", "X": -14, "Y": 22}]}


class SimParity(unittest.TestCase):
    """Crowd snapshot + walking times exported from the browser sim (same Dijkstra, same costs)."""

    def test_walking_times_match_sim(self):
        r = EmtRouter.from_venue_json(SNAP)
        cost = r.costs(SNAP["people"], SNAP["lying"])
        for q in SNAP["queries"]:
            f = r.field(q["X"], q["Y"], cost)
            for team, (px, py) in r.posts.items():
                self.assertAlmostEqual(f.dist[r.idx(px, py)], q["eta"][team], places=3, msg=f"{team} @ {q['X']},{q['Y']}")

    def test_pick_matches_sim_fastest(self):
        r = EmtRouter.from_venue_json(SNAP)
        for q in SNAP["queries"]:
            best = r.pick(q["X"], q["Y"], SNAP["people"], SNAP["lying"])
            self.assertEqual(best.team, min(q["eta"], key=q["eta"].get))


class Routing(unittest.TestCase):
    def setUp(self):
        self.r = EmtRouter.from_venue_json(EMPTY_VENUE)

    def test_obstacle_beats_straight_line(self):
        # patient just behind the FOH tent: SOUTH is 9.5 m away in a straight line but must walk around;
        # WEST is 14 m away with a clear line → WEST arrives first
        ranking = self.r.rank(0, 21)
        south = next(t for t in ranking if t.team == "SOUTH")
        west = next(t for t in ranking if t.team == "WEST")
        self.assertLess(south.straight_m, west.straight_m)
        self.assertEqual(ranking[0].team, "WEST")
        self.assertGreater(south.eta_s, south.straight_m / 1.5 + 1)

    def test_path_avoids_obstacle_and_ends_at_patient(self):
        self.r.pick(0, 21)
        f = self.r.last_field
        path = self.r.path(f, 0, 11.5)
        self.assertEqual(path[-1], self.r.xy(f.src))
        for x, y in path:
            self.assertFalse(-4 < x < 4 and 13 < y < 19, (x, y))

    def test_busy_team_skipped(self):
        self.assertEqual(self.r.pick(0, 21, busy={"WEST"}).team, "SOUTH")
        self.assertIsNone(self.r.pick(0, 21, busy={"WEST", "SOUTH"}))

    def test_crowd_slows_the_walk(self):
        clear = self.r.pick(-14, 30).eta_s
        crowd = [(-14 + dx * 0.5, 23 + dy * 0.5) for dx in range(-3, 4) for dy in range(0, 12)]  # wall of people
        packed = next(t for t in self.r.rank(-14, 30, people=crowd) if t.team == "WEST").eta_s
        self.assertGreater(packed, clear)

    def test_straight_corridor_time(self):
        # empty floor, no obstacle in the way: walking time ≈ distance / 1.5 m/s
        eta = next(t for t in self.r.rank(-14, 32) if t.team == "WEST").eta_s
        self.assertAlmostEqual(eta, 10 / 1.5, delta=0.05)


if __name__ == "__main__":
    unittest.main()
