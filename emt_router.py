#!/usr/bin/env python3
"""Pick the EMT team with the shortest *walking time* to a patient (Dijkstra).
Standard library only; drop this file into the MoshSpot dispatcher.

Same model as the simulator (web/index.html, "navigation"), so MoshSpot and the
sim agree on which team is nearest:
  - floor grid at 0.5 m over the venue bounds, 8-connected, no cutting obstacle corners
  - obstacles (inflated 0.5 m) are walls
  - cost = seconds per metre = (1 + 0.45 * crowd density [people/m², capped at 12]) / 1.5 m/s
    with density from the people MoshSpot is tracking (3x3-cell window); a person lying
    down counts as 40, so routes go around patients instead of over them

    router = EmtRouter.from_venue_json("moshspot-venue.json")      # sim export or gt.json
    best = router.pick(x, y, people=tracked_xy, lying=down_xy, busy={"EMT-2"})
    best.team, best.eta_s, best.path                                # path: venue-metre waypoints

CLI:  python3 emt_router.py moshspot-venue.json X Y [--people people.json] [--busy EMT-2,EMT-3]
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

CELL = 0.5            # m
SQRT2 = math.sqrt(2)
EMT_SPEED = 1.5       # m/s in the clear
DENSITY_SLOWDOWN = 0.45
DENSITY_CAP = 12.0    # people / m²
LYING_WEIGHT = 40     # a person on the ground counts as this many people
OBSTACLE_PAD = 0.5    # m
_STEPS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
          (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2)]

Point = Sequence[float]


@dataclass
class TeamETA:
    team: str
    eta_s: float          # walking time from the team's post (inf if unreachable)
    straight_m: float     # straight-line distance, for comparison/logging
    available: bool
    path: list = field(default_factory=list)  # post → patient waypoints (venue metres), best team only


@dataclass
class Field:
    """Shortest-path tree rooted at the patient: walking time from every cell to them."""
    dist: list
    prev: list
    src: int


class EmtRouter:
    def __init__(self, bounds: dict, obstacles: list[dict], emt_posts: list[dict]):
        self.x0, self.y0 = bounds["xmin"], bounds["ymin"]
        self.W = math.ceil((bounds["xmax"] - bounds["xmin"]) / CELL) + 1
        self.H = math.ceil((bounds["ymax"] - bounds["ymin"]) / CELL) + 1
        self.posts = {p["id"]: (p["X"], p["Y"]) for p in emt_posts}
        self.wall = [False] * (self.W * self.H)
        for i in range(self.W * self.H):
            x, y = self.xy(i)
            self.wall[i] = any(o["xmin"] - OBSTACLE_PAD < x < o["xmax"] + OBSTACLE_PAD and
                               o["ymin"] - OBSTACLE_PAD < y < o["ymax"] + OBSTACLE_PAD for o in obstacles)

    @classmethod
    def from_venue_json(cls, path_or_obj) -> "EmtRouter":
        obj = json.load(open(path_or_obj, encoding="utf-8")) if isinstance(path_or_obj, str) else path_or_obj
        v = obj.get("venue", obj)  # sim exports nest it under "venue"; a bare venue map works too
        return cls(v["bounds"], v.get("obstacles", []), v["emt_posts"])

    # ---- grid helpers (same rounding/clamping as the sim)
    def idx(self, x: float, y: float) -> int:
        cx = min(self.W - 1, max(0, round_half_up((x - self.x0) / CELL)))
        cy = min(self.H - 1, max(0, round_half_up((y - self.y0) / CELL)))
        return cx + cy * self.W

    def xy(self, i: int) -> tuple[float, float]:
        return self.x0 + (i % self.W) * CELL, self.y0 + (i // self.W) * CELL

    def costs(self, people: Iterable[Point] = (), lying: Iterable[Point] = ()) -> list[float]:
        W, H = self.W, self.H
        cnt = [0.0] * (W * H)
        for x, y in people:
            cnt[self.idx(x, y)] += 1
        for x, y in lying:
            cnt[self.idx(x, y)] += LYING_WEIGHT
        cost = [0.0] * (W * H)
        area = 9 * CELL * CELL
        for cy in range(H):
            for cx in range(W):
                i = cx + cy * W
                if self.wall[i]:
                    cost[i] = math.inf
                    continue
                n = 0.0
                for dy in (-1, 0, 1):
                    Y = cy + dy
                    if 0 <= Y < H:
                        for dx in (-1, 0, 1):
                            X = cx + dx
                            if 0 <= X < W:
                                n += cnt[X + Y * W]
                cost[i] = (1 + DENSITY_SLOWDOWN * min(n / area, DENSITY_CAP)) / EMT_SPEED
        return cost

    def field(self, x: float, y: float, cost: list[float]) -> Field:
        """Dijkstra from the patient at (x, y) over the given per-cell costs."""
        W, H = self.W, self.H
        dist = [math.inf] * (W * H)
        prev = [-1] * (W * H)
        src = self.idx(x, y)
        dist[src] = 0.0
        heap = [(0.0, src)]
        while heap:
            d, i = heapq.heappop(heap)
            if d > dist[i]:
                continue  # stale heap entry
            cx, cy = i % W, i // W
            ci = min(cost[i], 20.0)  # the patient's own cell is expensive; don't let it dominate
            for dx, dy, l in _STEPS:
                X, Y = cx + dx, cy + dy
                if not (0 <= X < W and 0 <= Y < H):
                    continue
                j = X + Y * W
                if cost[j] == math.inf:
                    continue
                if dx and dy and (cost[X + cy * W] == math.inf or cost[cx + Y * W] == math.inf):
                    continue  # no cutting obstacle corners
                nd = d + l * CELL * (ci + cost[j]) / 2
                if nd < dist[j]:
                    dist[j] = nd
                    prev[j] = i
                    heapq.heappush(heap, (nd, j))
        return Field(dist, prev, src)

    def path(self, f: Field, x: float, y: float, every: int = 4) -> list[tuple[float, float]]:
        """Waypoints from (x, y) to the patient along the shortest-path tree (one every ~2 m)."""
        i = self.idx(x, y)
        if f.dist[i] == math.inf:
            return []
        pts, k = [], 0
        while i != f.src and i != -1:
            i = f.prev[i]
            k += 1
            if k % every == 0 or i == f.src:
                pts.append(self.xy(i))
        return pts

    def rank(self, x: float, y: float, people: Iterable[Point] = (), lying: Iterable[Point] = (),
             busy: Iterable[str] = ()) -> list[TeamETA]:
        """All teams, fastest walk first. The patient's own position should be in `lying` if known."""
        busy = set(busy)
        f = self.field(x, y, self.costs(people, lying))
        out = [TeamETA(t, f.dist[self.idx(px, py)], math.hypot(px - x, py - y), t not in busy)
               for t, (px, py) in self.posts.items()]
        out.sort(key=lambda r: r.eta_s)
        best = next((r for r in out if r.available and r.eta_s < math.inf), None)
        if best:
            best.path = self.path(f, *self.posts[best.team])
        self.last_field = f  # reuse for paths from other points (e.g. a second team on escalation)
        return out

    def pick(self, x: float, y: float, people: Iterable[Point] = (), lying: Iterable[Point] = (),
             busy: Iterable[str] = ()) -> TeamETA | None:
        """The free team with the shortest walking time, or None if every team is busy/unreachable."""
        return next((r for r in self.rank(x, y, people, lying, busy) if r.available and r.eta_s < math.inf), None)


def round_half_up(v: float) -> int:
    # JavaScript Math.round semantics (Python's round() is banker's rounding)
    return math.floor(v + 0.5)


def main():
    ap = argparse.ArgumentParser(description="Nearest EMT team by walking time (Dijkstra).")
    ap.add_argument("venue", help="moshspot-venue.json or gt.json from the sim")
    ap.add_argument("X", type=float)
    ap.add_argument("Y", type=float)
    ap.add_argument("--people", help='JSON: [[x,y],...] or {"people":[[x,y],...],"lying":[[x,y],...]}')
    ap.add_argument("--busy", default="", help="comma-separated team ids")
    a = ap.parse_args()
    people, lying = [], []
    if a.people:
        d = json.load(open(a.people, encoding="utf-8"))
        people, lying = (d, []) if isinstance(d, list) else (d.get("people", []), d.get("lying", []))
    router = EmtRouter.from_venue_json(a.venue)
    ranking = router.rank(a.X, a.Y, people, lying, [b for b in a.busy.split(",") if b])
    for r in ranking:
        tag = "" if r.available else " (busy)"
        print(f"{r.team:8} walk {r.eta_s:6.1f}s   straight {r.straight_m:5.1f}m{tag}")
    best = next((r for r in ranking if r.path), None)
    print(f"-> dispatch {best.team} ({len(best.path)} waypoints)" if best else "-> no team available")


if __name__ == "__main__":
    main()
