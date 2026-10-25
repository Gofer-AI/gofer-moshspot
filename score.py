#!/usr/bin/env python3
"""Score MoshSpot alerts against simulator ground truth.

  python3 score.py runs/<run>/gt.json alerts.jsonl

alerts.jsonl — one JSON object per line, emitted by the MoshSpot worker:
  {"t": 41.2, "X": -6.3, "Y": 40.1, "priority": "HIGH", "camera": "CAM-1"}
  t = sim seconds (frame_idx / fps for recorded runs), X/Y = venue metres.

An alert matches a ground-truth incident if it is within --radius metres and
fires between t_down - 2 s and t_down + --window s. Alerts matching a
distractor (sit / crouch / collapse_recover) count as distractor false alarms.
"""
import argparse
import json
import math
import statistics


def main():
    p = argparse.ArgumentParser()
    p.add_argument("gt")
    p.add_argument("alerts")
    p.add_argument("--radius", type=float, default=3.0)
    p.add_argument("--window", type=float, default=90.0)
    a = p.parse_args()

    gt = json.load(open(a.gt, encoding="utf-8"))
    alerts = [json.loads(l) for l in open(a.alerts, encoding="utf-8") if l.strip()]
    incs = [i for i in gt["incidents"] if i["type"] != "crush_cluster" and i.get("t_down") is not None]
    pos = [i for i in incs if i["should_alert"]]
    neg = [i for i in incs if not i["should_alert"]]

    def match(inc, al):
        return math.hypot(al["X"] - inc["X"], al["Y"] - inc["Y"]) <= a.radius and inc["t_down"] - 2 <= al["t"] <= inc["t_down"] + a.window

    # one alert credits at most one incident (crush victims lie within metres of each other);
    # extra alerts on an already-detected incident are duplicates, not false positives
    used, rows, latencies, claimed, tp_cov = set(), [], [], set(), 0
    for inc in sorted(pos, key=lambda i: i["t_down"]):
        hits = sorted((al["t"], math.hypot(al["X"] - inc["X"], al["Y"] - inc["Y"]), k) for k, al in enumerate(alerts) if match(inc, al))
        free = [h for h in hits if h[2] not in claimed]
        used.update(h[2] for h in hits)
        if free:
            t, _, k = free[0]
            claimed.add(k)
            lat = t - inc["t_down"]
            latencies.append(lat)
            tp_cov += bool(inc["visible_in"])
            pr = alerts[k].get("priority")
            rows.append((inc["id"], inc["type"], "TP", f"{lat:+.1f}s", f"{pr} (exp {inc['expected_priority']})", ",".join(inc["visible_in"]) or "no cam"))
        else:
            rows.append((inc["id"], inc["type"], "MISS", "", "", ",".join(inc["visible_in"]) or "no cam"))
    distractor_fa = 0
    for inc in neg:
        ks = [k for k, al in enumerate(alerts) if match(inc, al)]
        if ks:
            distractor_fa += 1
            used.update(ks)
            rows.append((inc["id"], inc["type"], "FALSE ALARM", "", "", ",".join(inc["visible_in"])))
    other_fp = [al for k, al in enumerate(alerts) if k not in used]

    print(f"{'incident':10} {'type':18} {'result':12} {'latency':9} {'priority':22} cams")
    for r in rows:
        print(f"{r[0]:10} {r[1]:18} {r[2]:12} {r[3]:9} {r[4]:22} {r[5]}")
    tp = sum(r[2] == "TP" for r in rows)
    covered = [i for i in pos if i["visible_in"]]
    print()
    print(f"recall            {tp}/{len(pos)}  (on camera-covered incidents: {tp_cov}/{len(covered)})")
    print(f"distractor FAs    {distractor_fa}/{len(neg)}")
    print(f"unmatched alerts  {len(other_fp)}  ({len(other_fp) / max(gt['duration_s'] / 3600, 1e-9):.1f} per hour)")
    if latencies:
        print(f"time to alert     median {statistics.median(latencies):.1f}s, max {max(latencies):.1f}s after the person is down")

    # closed loop: EMT teams dispatched into the sim through the bridge's /dispatch
    disp = gt.get("dispatches") or []
    if disp:
        by_id = {i["id"]: i for i in incs}
        on_scene = [d for d in disp if d.get("t_arrive") is not None and d.get("sim_incident") in by_id]
        wrong = [d for d in disp if d.get("sim_incident") is None]
        print(f"dispatches        {len(disp)} ({len(wrong)} found no patient, "
              f"{sum(d.get('outcome') == 'cancelled' for d in disp)} cancelled/escalated)")
        if on_scene:
            down_to_scene = [d["t_arrive"] - by_id[d["sim_incident"]]["t_down"] for d in on_scene]
            print(f"down -> EMT on scene  median {statistics.median(down_to_scene):.1f}s, max {max(down_to_scene):.1f}s "
                  f"(n={len(on_scene)})")


if __name__ == "__main__":
    main()
