"""Bridge hardening: auth, body caps, bounded queues, recording switch, public-host guard."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bridge  # noqa: E402

TOKEN = "t" * 32


class BridgeCase(unittest.TestCase):
    cfg_kwargs = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = bridge.Config(runs_dir=Path(self.tmp.name), **self.cfg_kwargs)
        self.srv = bridge.make_server("127.0.0.1", 0, cfg)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None, token=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data


class WithToken(BridgeCase):
    cfg_kwargs = {"token": TOKEN}

    def test_page_and_status_are_public(self):
        self.assertEqual(self.req("GET", "/")[0], 200)
        code, body = self.req("GET", "/status")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"ok": True, "auth_required": True, "record": False, "authorized": False})

    def test_api_needs_token(self):
        for method, path, body in [("POST", "/dispatch", {"X": 1, "Y": 2}), ("GET", "/emt", None), ("GET", "/commands", None),
                                   ("POST", "/frame/CAM-1", b"jpeg"), ("GET", "/snapshot/CAM-1.jpg", None), ("GET", "/cams", None)]:
            self.assertEqual(self.req(method, path, body)[0], 401, path)
        self.assertEqual(self.req("POST", "/dispatch", {"X": 1, "Y": 2}, token="wrong" * 8)[0], 401)

    def test_token_via_header_bearer_or_query(self):
        self.assertEqual(self.req("POST", "/dispatch", {"X": 1, "Y": 2}, token=TOKEN)[0], 202)
        self.assertEqual(self.req("GET", "/emt", headers={"X-MoshSpot-Token": TOKEN})[0], 200)
        self.assertEqual(self.req("GET", f"/commands?token={TOKEN}")[0], 200)
        self.assertTrue(json.loads(self.req("GET", f"/status?token={TOKEN}")[1])["authorized"])

    def test_no_directory_listing_or_other_files(self):
        self.assertEqual(self.req("GET", "/web/")[0], 401)  # no token: refused before any path lookup
        self.assertEqual(self.req("GET", "/web/", token=TOKEN)[0], 404)
        self.assertEqual(self.req("GET", "/../bridge.py", token=TOKEN)[0], 404)


class Incidents(BridgeCase):
    cfg_kwargs = {"token": TOKEN}

    def test_worker_publishes_and_page_reads_incidents(self):
        self.assertEqual(self.req("GET", "/incidents")[0], 401)
        self.assertEqual(self.req("POST", "/incidents", {"incidents": []})[0], 401)
        snapshot = {"incidents": [{"id": "ms-1", "state": "alerted", "X": 1.5, "Y": 30.2, "trace": []}]}
        self.assertEqual(self.req("POST", "/incidents", snapshot, token=TOKEN)[0], 204)
        code, body = self.req("GET", "/incidents", token=TOKEN)
        self.assertEqual((code, json.loads(body)), (200, snapshot))
        self.assertEqual(self.req("POST", "/incidents", {"incidents": "nope"}, token=TOKEN)[0], 400)


class Limits(BridgeCase):
    cfg_kwargs = {"queue_len": 5, "max_frame_bytes": 1000, "max_cams": 2}

    def test_body_caps(self):
        self.assertEqual(self.req("POST", "/frame/CAM-1", b"x" * 1001)[0], 413)
        self.assertEqual(self.req("POST", "/frame/CAM-1", b"x" * 1000)[0], 204)
        self.assertEqual(self.req("POST", "/dispatch", b"{" + b" " * (70 << 10) + b"}")[0], 413)

    def test_camera_count_capped(self):
        for cam in ("A", "B"):
            self.assertEqual(self.req("POST", f"/frame/{cam}", b"x")[0], 204)
        self.assertEqual(self.req("POST", "/frame/C", b"x")[0], 400)
        self.assertEqual(self.req("POST", "/frame/A", b"y")[0], 204)  # existing camera still updates

    def test_queues_are_bounded_and_ids_keep_counting(self):
        for i in range(12):
            self.assertEqual(self.req("POST", "/dispatch", {"X": i, "Y": 0})[0], 202)
        d = json.loads(self.req("GET", "/commands?after=0")[1])
        self.assertEqual(d["last"], 12)
        self.assertEqual([c["id"] for c in d["commands"]], [8, 9, 10, 11, 12])
        self.assertEqual([c["id"] for c in json.loads(self.req("GET", "/commands?after=10")[1])["commands"]], [11, 12])
        for i in range(8):
            self.req("POST", "/emt-events", {"team": "EMT-1", "status": f"s{i}"})
        e = json.loads(self.req("GET", "/emt")[1])
        self.assertEqual((len(e["events"]), e["last"], e["teams"]["EMT-1"]["status"]), (5, 8, "s7"))

    def test_bad_input(self):
        self.assertEqual(self.req("POST", "/dispatch", {"action": "warp"})[0], 400)
        self.assertEqual(self.req("POST", "/dispatch", b"[1,2]")[0], 400)
        self.assertEqual(self.req("POST", "/emt-events", {"team": "../etc"})[0], 400)


class RecordingSwitch(BridgeCase):
    def test_recording_off_by_default(self):
        self.assertEqual(self.req("POST", "/frame/CAM-1?run=r1&idx=0", b"jpeg")[0], 403)
        self.assertEqual(self.req("POST", "/gt?run=r1", {"a": 1})[0], 403)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.assertEqual(self.req("POST", "/frame/CAM-1", b"jpeg")[0], 204)  # live streaming still works


class RecordingOn(BridgeCase):
    cfg_kwargs = {"record": True}

    def test_records_frames_and_gt(self):
        self.assertEqual(self.req("POST", "/frame/CAM-1?run=r1&idx=7", b"jpeg")[0], 204)
        self.assertEqual(self.req("POST", "/gt?run=r1", {"a": 1})[0], 204)
        run = Path(self.tmp.name) / "r1"
        self.assertEqual((run / "CAM-1" / "000007.jpg").read_bytes(), b"jpeg")
        self.assertEqual(json.loads((run / "gt.json").read_text()), {"a": 1})

    def test_rejects_bad_run_and_idx(self):
        self.assertEqual(self.req("POST", "/frame/CAM-1?run=../x&idx=0", b"j")[0], 400)
        self.assertEqual(self.req("POST", "/frame/CAM-1?run=r1&idx=-1", b"j")[0], 400)
        self.assertEqual(self.req("POST", "/frame/CAM-1?run=r1&idx=1000000", b"j")[0], 400)


class StartupGuard(unittest.TestCase):
    def test_public_host_needs_token(self):
        with self.assertRaises(SystemExit) as e:
            bridge.main(["--host", "0.0.0.0", "--port", "0"])
        self.assertIn("MOSHSPOT_TOKEN", str(e.exception))


if __name__ == "__main__":
    unittest.main()
