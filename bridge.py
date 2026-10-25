#!/usr/bin/env python3
"""MoshSpot sim bridge: serves the simulator and turns its camera frames into
inputs the MoshSpot worker can ingest. Standard library only.

  python3 bridge.py                 # open http://localhost:8780

Live (real time, MJPEG over HTTP — cv.VideoCapture reads it like a camera):
  cv.VideoCapture("http://localhost:8780/mjpeg/CAM-1")

Recorded runs (deterministic; frame k is at t = k / fps of sim time):
  runs/<run>/CAM-1/000000.jpg ...   cv.VideoCapture("runs/<run>/CAM-1/%06d.jpg")
  runs/<run>/gt.json                calibration + venue + incident ground truth
  runs/<run>/gt_frames.jsonl        per-frame boxes/keypoints of non-upright people

Dispatch loop (MoshSpot -> sim EMT teams walk to the patient):
  POST /dispatch {"action":"dispatch","team":"EMT-1","X":-6.2,"Y":40.1,"incident_id":"ms-42"}
       action: dispatch | accept | resolve | false_alarm | cancel  (team optional on dispatch = nearest free)
  GET  /emt?after=N   team status events from the sim: dispatched, accepted, en_route, on_scene, resolved, ...
"""
import argparse
import json
import os
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

latest: dict[str, bytes] = {}  # camera id -> most recent JPEG
cond = threading.Condition()

# dispatch loop: MoshSpot -> /dispatch -> commands (sim polls) ; sim -> /emt-events -> MoshSpot polls /emt
ACTIONS = {"dispatch", "accept", "resolve", "false_alarm", "cancel"}
commands: list[dict] = []
emt_events: list[dict] = []
emt_teams: dict[str, dict] = {}
lock = threading.Lock()


def _json(body):
    try:
        obj = json.loads(body or b"{}")
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _validate_dispatch(cmd):
    action = cmd.get("action", "dispatch")
    if action not in ACTIONS:
        return f"action must be one of {sorted(ACTIONS)}"
    team = cmd.get("team")
    if team is not None and not (isinstance(team, str) and SAFE.match(team)):
        return "bad team id"
    ext = cmd.get("incident_id")
    if ext is not None and not (isinstance(ext, str) and len(ext) <= 80):
        return "bad incident_id"
    if action == "dispatch":
        try:
            float(cmd["X"]), float(cmd["Y"])
        except (KeyError, TypeError, ValueError):
            return "dispatch needs numeric X and Y (venue metres)"
    elif team is None and ext is None:
        return f"{action} needs team or incident_id"
    return None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT / "web"), **k)

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        parts = u.path.strip("/").split("/")
        run = q.get("run")
        if run is not None and not SAFE.match(run):
            return self._send(400, b'{"error":"bad run name"}')

        if parts[0] == "frame" and len(parts) == 2 and SAFE.match(parts[1]):
            cam = parts[1]
            with cond:
                latest[cam] = body
                cond.notify_all()
            if run:
                d = RUNS / run / cam
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{int(q.get('idx', 0)):06d}.jpg").write_bytes(body)
            return self._send(204)

        if u.path == "/dispatch":
            cmd = _json(body)
            err = "body must be a JSON object" if cmd is None else _validate_dispatch(cmd)
            if err:
                return self._send(400, json.dumps({"error": err}).encode())
            keep = {k: cmd[k] for k in ("action", "team", "incident_id", "X", "Y") if k in cmd}
            keep.setdefault("action", "dispatch")
            with lock:
                keep["id"] = len(commands) + 1
                commands.append(keep)
            return self._send(202, json.dumps({"ok": True, "id": keep["id"]}).encode())

        if u.path == "/emt-events":
            ev = _json(body)
            if ev is None or not SAFE.match(str(ev.get("team", ""))):
                return self._send(400, b'{"error":"bad event"}')
            with lock:
                ev["seq"] = len(emt_events) + 1
                emt_events.append(ev)
                emt_teams[ev["team"]] = ev
            return self._send(204)

        if parts[0] in ("gt", "gt-frames") and run:
            d = RUNS / run
            d.mkdir(parents=True, exist_ok=True)
            if parts[0] == "gt":
                (d / "gt.json").write_bytes(body)
                print(f"saved run -> {d}")
            else:
                with open(d / "gt_frames.jsonl", "ab") as f:
                    f.write(body.rstrip(b"\n") + b"\n")
            return self._send(204)

        self._send(404, b'{"error":"not found"}')

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/status":
            return self._send(200, json.dumps({"ok": True, "cams": sorted(latest)}).encode())
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        after = int(q["after"]) if q.get("after", "").isdigit() else 0
        if u.path == "/commands":
            with lock:
                return self._send(200, json.dumps({"commands": commands[after:], "last": len(commands)}).encode())
        if u.path == "/emt":
            with lock:
                return self._send(200, json.dumps({"teams": emt_teams, "events": emt_events[after:], "last": len(emt_events)}).encode())
        m = re.match(r"^/mjpeg/([A-Za-z0-9_.-]+)$", u.path)
        if m:
            return self._mjpeg(m.group(1))
        m = re.match(r"^/snapshot/([A-Za-z0-9_.-]+)\.jpg$", u.path)
        if m:
            frame = latest.get(m.group(1))
            return self._send(200, frame, "image/jpeg") if frame else self._send(404)
        return super().do_GET()

    def _mjpeg(self, cam):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = None
        try:
            while True:
                with cond:
                    cond.wait_for(lambda: latest.get(cam) is not last, timeout=10)
                    frame = latest.get(cam)
                if frame is None or frame is last:
                    continue
                last = frame
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame))
                self.wfile.write(frame + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8780)))
    a = p.parse_args()
    print(f"MoshSpot sim on http://{a.host}:{a.port}  (MJPEG: /mjpeg/CAM-1..4, runs -> {RUNS})")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
