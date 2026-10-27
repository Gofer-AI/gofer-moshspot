"""Regression tests for the pre-submission security review (XSS, poisoned events, traversal, stream slots, CSP)."""
import http.client
import json
import socket
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_bridge import BridgeCase  # noqa: E402

from moshspot.dispatch import Dispatcher  # noqa: E402

VENUE = json.load(open(ROOT / "tests" / "fixtures" / "sim_snapshot.json", encoding="utf-8"))


class Injection(BridgeCase):
    def test_markup_in_incident_id_rejected(self):
        code, _ = self.req("POST", "/dispatch", {"X": 0, "Y": 0, "incident_id": '<img src=x onerror="alert(1)">'})
        self.assertEqual(code, 400)
        self.assertEqual(self.req("POST", "/dispatch", {"X": 0, "Y": 0, "incident_id": "manual-INC-001"})[0], 202)

    def test_emt_events_are_whitelisted(self):
        bad = [{"team": "EMT-1", "status": "on_scene", "incident_id": [1]},
               {"team": "EMT-1", "status": "<b>x</b>"},
               {"team": "EMT-1", "status": "on_scene", "incident_id": "<img>"},
               {"team": "..", "status": "on_scene"}]
        for ev in bad:
            self.assertEqual(self.req("POST", "/emt-events", ev)[0], 400, ev)
        ok = {"team": "EMT-1", "status": "on_scene", "incident_id": "ms-3", "response_s": 18.5,
              "evil": "<script>", "clock": "<i>", "ranking": [{"team": "EMT-2", "eta_s": 3, "status": "<x>"}, "junk"]}
        self.assertEqual(self.req("POST", "/emt-events", ok)[0], 204)
        ev = json.loads(self.req("GET", "/emt")[1])["events"][-1]
        self.assertNotIn("evil", ev)
        self.assertNotIn("clock", ev)
        self.assertEqual(ev["ranking"], [{"team": "EMT-2", "status": None, "eta_s": 3, "straight_m": None}])

    def test_incident_items_must_be_objects(self):
        self.assertEqual(self.req("POST", "/incidents", {"incidents": [None]})[0], 400)
        self.assertEqual(self.req("POST", "/incidents", {"incidents": [{"id": "ms-1"}]})[0], 204)

    def test_non_ascii_digits_do_not_crash(self):
        self.assertEqual(self.req("GET", "/commands?after=%C2%B2")[0], 200)

    def test_page_has_csp_and_frame_denial(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("'sha256-", csp)
        self.assertNotIn("unsafe-inline' https", csp.split("script-src")[1].split(";")[0])
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")


class Traversal(BridgeCase):
    cfg_kwargs = {"record": True}

    def test_dot_names_rejected(self):
        for path in ("/frame/CAM-1?run=..&idx=0", "/frame/CAM-1?run=.&idx=0", "/frame/..?run=r1&idx=0"):
            self.assertIn(self.req("POST", path, b"j")[0], (400, 404), path)
        self.assertEqual(self.req("POST", "/gt-frames?run=..", {"a": 1})[0], 400)
        self.assertFalse((Path(self.tmp.name).parent / "gt_frames.jsonl").exists())


class StreamSlots(BridgeCase):
    cfg_kwargs = {"max_streams": 1, "stream_idle_s": 0.3}

    def test_idle_stream_releases_its_slot(self):
        s = socket.create_connection(("127.0.0.1", self.port))
        s.sendall(b"GET /mjpeg/NOPE HTTP/1.1\r\nHost: x\r\n\r\n")
        s.close()
        time.sleep(0.6)  # > stream_idle_s: the server ends the idle stream and frees the slot
        self.req("POST", "/frame/CAM-1", b"jpeg")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/mjpeg/CAM-1")
        self.assertEqual(c.getresponse().status, 200)
        c.close()


class WorkerSurvivesPoisonedEvents(unittest.TestCase):
    def test_poll_ignores_non_string_incident_ids(self):
        d = Dispatcher("http://127.0.0.1:1", VENUE)
        d._get = lambda path: {"events": [{"seq": 1, "team": "EMT-1", "status": "on_scene", "incident_id": [1]},
                                          {"seq": 2, "team": "EMT-1", "status": "on_scene", "incident_id": {"a": 1}}]}
        d.poll()  # must not raise
        self.assertEqual(d._last_event, 2)


if __name__ == "__main__":
    unittest.main()
