#!/usr/bin/env python3
"""MoshSpot sim bridge: serves the simulator and turns its camera frames into
inputs the MoshSpot worker can ingest. Standard library only.

  python3 bridge.py                      # local dev: http://localhost:8780
  python3 bridge.py --record             # also allow saving recorded runs to runs/
  MOSHSPOT_TOKEN=... python3 bridge.py   # require a token (mandatory off-localhost)

Live (real time, MJPEG over HTTP; cv.VideoCapture reads it like a camera):
  cv.VideoCapture("http://localhost:8780/mjpeg/CAM-1")            # add ?token=... when auth is on

Recorded runs (needs --record; frame k is at t = k / fps of sim time):
  runs/<run>/CAM-1/000000.jpg ...   cv.VideoCapture("runs/<run>/CAM-1/%06d.jpg")
  runs/<run>/gt.json                calibration + venue + incident ground truth
  runs/<run>/gt_frames.jsonl        per-frame boxes/keypoints of non-upright people

Dispatch loop (MoshSpot -> sim EMT teams walk to the patient):
  POST /dispatch {"action":"dispatch","team":"EMT-1","X":-6.2,"Y":40.1,"incident_id":"ms-42"}
       action: dispatch | accept | resolve | false_alarm | cancel  (team optional on dispatch = nearest free)
  GET  /emt?after=N   team status events from the sim: dispatched, accepted, en_route, on_scene, resolved, ...

MoshSpot's incidents (shown in the page's "MoshSpot incidents" panel and on the map):
  POST /incidents {"incidents": [...]}   the worker publishes its current incidents and agent traces
  GET  /incidents                         the page reads them

Auth: when a token is set, every endpoint except the page itself and /status needs it, as
"Authorization: Bearer <token>", "X-MoshSpot-Token: <token>", or "?token=<token>" (for MJPEG URLs).
The page picks it up from its URL fragment: https://host/#token=<token>.
"""
import argparse
import base64
import hashlib
import hmac
import math
import json
import os
import re
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
SAFE = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9_.-]{1,80}$")  # ids, run and camera names; never "." or ".."
DIGITS = re.compile(r"^[0-9]{1,9}$")  # ASCII only: str.isdigit() also accepts "²" etc.
EMT_STATUSES = {"dispatched", "accepted", "en_route", "on_scene", "resolved", "false_alarm", "cancelled",
                "no_patient_found", "available", "rejected"}
TEAM_STATUSES = {"available", "dispatched", "en_route", "on_scene", "returning"}
ACTIONS = {"dispatch", "accept", "resolve", "false_alarm", "cancel"}
PUBLIC_GET = {"/", "/index.html", "/status"}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@dataclass
class Config:
    token: Optional[str] = None
    record: bool = False
    runs_dir: Path = ROOT / "runs"
    max_frame_bytes: int = 4 << 20       # one JPEG (1280x720 at q=0.85 is ~200 KB)
    max_gt_bytes: int = 32 << 20         # gt.json at the end of a run
    max_gt_frame_bytes: int = 1 << 20    # one line of gt_frames.jsonl
    max_json_bytes: int = 64 << 10       # dispatch commands, EMT events
    max_run_gt_frames_bytes: int = 256 << 20  # per recorded run
    stream_idle_s: float = 30.0          # end an MJPEG stream after this long with no new frame
    max_incidents_bytes: int = 1 << 20   # the worker's incident snapshot, traces included
    max_cams: int = 16
    max_teams: int = 64
    max_streams: int = 32                # concurrent MJPEG viewers
    queue_len: int = 1000                # commands / EMT events kept for polling


@dataclass
class State:
    cfg: Config
    latest: dict = field(default_factory=dict)  # camera id -> most recent JPEG
    cond: threading.Condition = field(default_factory=threading.Condition)
    lock: threading.Lock = field(default_factory=threading.Lock)
    commands: deque = None
    events: deque = None
    teams: dict = field(default_factory=dict)
    incidents: bytes = b'{"incidents": []}'
    last_cmd: int = 0
    last_event: int = 0
    streams: threading.BoundedSemaphore = None

    def __post_init__(self):
        self.commands = deque(maxlen=self.cfg.queue_len)
        self.events = deque(maxlen=self.cfg.queue_len)
        self.streams = threading.BoundedSemaphore(self.cfg.max_streams)


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
    if ext is not None and not (isinstance(ext, str) and SAFE.match(ext)):
        return "incident_id must match [A-Za-z0-9_.-]{1,80}"
    if action == "dispatch":
        try:
            float(cmd["X"]), float(cmd["Y"])
        except (KeyError, TypeError, ValueError):
            return "dispatch needs numeric X and Y (venue metres)"
    elif team is None and ext is None:
        return f"{action} needs team or incident_id"
    return None


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _clean_event(ev):
    """Keep only known EMT-event fields with checked types, so nothing a token holder posts can crash the
    worker or inject markup into a judge's page (incident_id is rendered there)."""
    if not isinstance(ev, dict) or not (isinstance(ev.get("team"), str) and SAFE.match(ev["team"])):
        return None
    if ev.get("status") not in EMT_STATUSES:
        return None
    out = {"team": ev["team"], "status": ev["status"]}
    for k in ("incident_id", "sim_incident"):
        v = ev.get(k)
        if v is not None:
            if not (isinstance(v, str) and SAFE.match(v)):
                return None
            out[k] = v
    for k in ("t", "X", "Y", "eta_s", "response_s"):
        if _num(ev.get(k)):
            out[k] = ev[k]
    if isinstance(ev.get("clock"), str) and re.fullmatch(r"[0-9:]{1,8}", ev["clock"]):
        out["clock"] = ev["clock"]
    if isinstance(ev.get("patient_found"), bool):
        out["patient_found"] = ev["patient_found"]
    if ev.get("chosen_by") in ("dijkstra", "moshspot"):
        out["chosen_by"] = ev["chosen_by"]
    if isinstance(ev.get("reason"), str):
        out["reason"] = re.sub(r"[^A-Za-z0-9 _().,-]", "", ev["reason"])[:80]
    if isinstance(ev.get("ranking"), list):
        out["ranking"] = [{"team": r["team"], "status": r.get("status") if r.get("status") in TEAM_STATUSES else None,
                           "eta_s": r.get("eta_s") if _num(r.get("eta_s")) else None,
                           "straight_m": r.get("straight_m") if _num(r.get("straight_m")) else None}
                          for r in ev["ranking"][:16]
                          if isinstance(r, dict) and isinstance(r.get("team"), str) and SAFE.match(r["team"])]
    return out


def _inline_script_hashes(html_path):
    html = Path(html_path).read_text(encoding="utf-8")
    bodies = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    return " ".join("'sha256-%s'" % base64.b64encode(hashlib.sha256(b.encode()).digest()).decode() for b in bodies)


# Only the page's own inline scripts (by hash) and the pinned three.js may run; the page talks only to us.
CSP = ("default-src 'none'; script-src %s https://cdn.jsdelivr.net; connect-src 'self'; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
       % _inline_script_hashes(ROOT / "web" / "index.html"))


class Handler(SimpleHTTPRequestHandler):
    timeout = 30  # seconds; stops idle/slow clients from pinning threads

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT / "web"), **k)

    @property
    def st(self) -> State:
        return self.server.state

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self.close_connection = True  # the request body may be unread; never reuse this connection
        return self._send(code, json.dumps({"error": msg}).encode())

    def _authorized(self, q):
        tok = self.st.cfg.token
        if not tok:
            return True
        auth = self.headers.get("Authorization", "")
        given = auth[7:] if auth.startswith("Bearer ") else self.headers.get("X-MoshSpot-Token") or q.get("token", "")
        return hmac.compare_digest(given.encode(), tok.encode())

    def _body(self, cap):
        """Read the request body, refusing anything without a length or over `cap` bytes."""
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            self._err(411, "Content-Length required")
            return None
        if n < 0 or n > cap:
            self.close_connection = True  # don't read it; drop the connection after replying
            self._err(413, f"body too large (max {cap} bytes)")
            return None
        return self.rfile.read(n)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self._authorized(q):
            self.close_connection = True
            return self._err(401, "token required")
        cfg, st = self.st.cfg, self.st
        parts = u.path.strip("/").split("/")
        run = q.get("run")
        if run is not None:
            if not cfg.record:
                self.close_connection = True
                return self._err(403, "recording is disabled; start the bridge with --record")
            if not SAFE.match(run):
                return self._err(400, "bad run name")

        if parts[0] == "frame" and len(parts) == 2 and SAFE.match(parts[1]):
            cam = parts[1]
            body = self._body(cfg.max_frame_bytes)
            if body is None:
                return
            with st.cond:
                if cam not in st.latest and len(st.latest) >= cfg.max_cams:
                    return self._err(400, "too many cameras")
                st.latest[cam] = body
                st.cond.notify_all()
            if run:
                idx = q.get("idx", "")
                if not (DIGITS.match(idx) and int(idx) < 1_000_000):
                    return self._err(400, "idx must be 0..999999")
                d = cfg.runs_dir / run / cam
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{int(idx):06d}.jpg").write_bytes(body)
            return self._send(204)

        if u.path == "/dispatch":
            body = self._body(cfg.max_json_bytes)
            if body is None:
                return
            cmd = _json(body)
            err = "body must be a JSON object" if cmd is None else _validate_dispatch(cmd)
            if err:
                return self._err(400, err)
            keep = {k: cmd[k] for k in ("action", "team", "incident_id", "X", "Y") if k in cmd}
            keep.setdefault("action", "dispatch")
            with st.lock:
                st.last_cmd += 1
                keep["id"] = st.last_cmd
                st.commands.append(keep)
            return self._send(202, json.dumps({"ok": True, "id": keep["id"]}).encode())

        if u.path == "/emt-events":
            body = self._body(cfg.max_json_bytes)
            if body is None:
                return
            ev = _clean_event(_json(body))
            if ev is None:
                return self._err(400, "bad event")
            with st.lock:
                if ev["team"] not in st.teams and len(st.teams) >= cfg.max_teams:
                    return self._err(400, "too many teams")
                st.last_event += 1
                ev["seq"] = st.last_event
                st.events.append(ev)
                st.teams[ev["team"]] = ev
            return self._send(204)

        if u.path == "/incidents":
            body = self._body(cfg.max_incidents_bytes)
            if body is None:
                return
            snapshot = _json(body)
            if snapshot is None or not isinstance(snapshot.get("incidents"), list) \
                    or not all(isinstance(i, dict) for i in snapshot["incidents"]):
                return self._err(400, 'body must be {"incidents": [{...}, ...]}')
            st.incidents = body
            return self._send(204)

        if parts[0] in ("gt", "gt-frames") and len(parts) == 1:
            if not run:
                return self._err(400 if cfg.record else 403, "run required" if cfg.record else "recording is disabled; start the bridge with --record")
            body = self._body(cfg.max_gt_bytes if parts[0] == "gt" else cfg.max_gt_frame_bytes)
            if body is None:
                return
            d = cfg.runs_dir / run
            d.mkdir(parents=True, exist_ok=True)
            if parts[0] == "gt":
                (d / "gt.json").write_bytes(body)
                print(f"saved run -> {d}")
            else:
                gtf = d / "gt_frames.jsonl"
                if gtf.exists() and gtf.stat().st_size > cfg.max_run_gt_frames_bytes:
                    return self._err(413, "gt_frames.jsonl is full for this run")
                with open(gtf, "ab") as f:
                    f.write(body.rstrip(b"\n") + b"\n")
            return self._send(204)

        self._err(404, "not found")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        cfg, st = self.st.cfg, self.st
        if u.path == "/status":  # public health check; says what the page needs to know, nothing more
            return self._send(200, json.dumps({"ok": True, "auth_required": bool(cfg.token), "record": cfg.record,
                                               "authorized": self._authorized(q)}).encode())
        if u.path not in PUBLIC_GET and not self._authorized(q):
            self.close_connection = True
            return self._err(401, "token required")
        after = int(q["after"]) if DIGITS.match(q.get("after", "")) else 0
        if u.path == "/commands":
            with st.lock:
                return self._send(200, json.dumps({"commands": [c for c in st.commands if c["id"] > after],
                                                   "last": st.last_cmd}).encode())
        if u.path == "/emt":
            with st.lock:
                return self._send(200, json.dumps({"teams": st.teams, "events": [e for e in st.events if e["seq"] > after],
                                                   "last": st.last_event}).encode())
        if u.path == "/incidents":
            return self._send(200, st.incidents)
        if u.path == "/cams":
            return self._send(200, json.dumps({"cams": sorted(st.latest)}).encode())
        m = re.match(r"^/mjpeg/([A-Za-z0-9_.-]+)$", u.path)
        if m:
            return self._mjpeg(m.group(1))
        m = re.match(r"^/snapshot/([A-Za-z0-9_.-]+)\.jpg$", u.path)
        if m:
            frame = st.latest.get(m.group(1))
            return self._send(200, frame, "image/jpeg") if frame else self._err(404, "no frame yet")
        if u.path not in PUBLIC_GET:
            return self._err(404, "not found")
        return super().do_GET()

    def _mjpeg(self, cam):
        st = self.st
        if not st.streams.acquire(blocking=False):
            return self._err(503, "too many streams")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last, idle = None, 0
            while True:
                with st.cond:
                    st.cond.wait_for(lambda: st.latest.get(cam) is not last, timeout=st.cfg.stream_idle_s / 3)
                    frame = st.latest.get(cam)
                if frame is None or frame is last:
                    idle += 1
                    if idle >= 3:  # no frame for stream_idle_s: end the stream so a gone client can't hold a slot
                        break
                    continue
                last, idle = frame, 0
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame))
                self.wfile.write(frame + b"\r\n")
        except OSError:  # client went away or stalled past the socket timeout
            pass
        finally:
            st.streams.release()


def make_server(host: str, port: int, cfg: Config) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.state = State(cfg)
    return srv


def main(argv=None):
    p = argparse.ArgumentParser(description="MoshSpot sim bridge")
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 only behind an HTTPS proxy/load balancer")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8780)))
    p.add_argument("--record", action="store_true", default=os.environ.get("MOSHSPOT_RECORD") == "1",
                   help="allow the page to save recorded runs to --runs-dir (off by default)")
    p.add_argument("--runs-dir", type=Path, default=Path(os.environ.get("MOSHSPOT_RUNS_DIR", ROOT / "runs")))
    p.add_argument("--insecure-no-token", action="store_true", help="allow a non-loopback host without a token")
    a = p.parse_args(argv)
    token = os.environ.get("MOSHSPOT_TOKEN") or None  # env only: a CLI flag would show up in `ps`
    if token is not None and len(token) < 16:
        sys.exit("MOSHSPOT_TOKEN must be at least 16 characters (try: openssl rand -hex 24)")
    if a.host not in LOOPBACK and not token and not a.insecure_no_token:
        sys.exit(f"refusing to listen on {a.host} without MOSHSPOT_TOKEN (anyone could dispatch or upload)")
    cfg = Config(token=token, record=a.record, runs_dir=a.runs_dir)
    print(f"MoshSpot sim on http://{a.host}:{a.port}  auth={'on' if token else 'off'}  "
          f"record={'on -> ' + str(cfg.runs_dir) if cfg.record else 'off'}")
    make_server(a.host, a.port, cfg).serve_forever()


if __name__ == "__main__":
    main()
