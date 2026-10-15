import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hoi4dbg.server import TOKEN_HEADER, make_server

from helpers import TempDirMixin, make_service

TOKEN = "test-token"
BACKEND_DIR = Path(__file__).resolve().parents[1]


class ServerTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = make_server(make_service(self.tmp), TOKEN)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path, method="GET", body=None, token=TOKEN):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if token is not None:
            req.add_header(TOKEN_HEADER, token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_token_required(self):
        self.assertEqual(self.call("/api/health", token=None)[0], 401)
        self.assertEqual(self.call("/api/health", token="wrong")[0], 401)
        self.assertEqual(self.call("/api/health"), (200, {"ok": True}))

    def test_all_get_endpoints(self):
        for path in ("/api/status", "/api/countries", "/api/countries/GER", "/api/states?owner=SOV",
                     "/api/focus/GER", "/api/equipment/GER", "/api/tools",
                     "/api/logs/app?limit=5&level=info", "/api/logs/game", "/api/reports"):
            with self.subTest(path=path):
                status, payload = self.call(path)
                self.assertEqual(status, 200, payload)

    def test_errors(self):
        self.assertEqual(self.call("/api/countries/NOPE")[0], 404)
        self.assertEqual(self.call("/api/nothing")[0], 404)
        self.assertEqual(self.call("/api/status", method="POST", body={})[0], 405)
        self.assertEqual(self.call("/api/reports", method="POST", body={"title": ""})[0], 400)
        self.assertEqual(self.call("/api/logs/game/missing.log")[1]["source"], "unavailable")

    def test_report_roundtrip(self):
        status, created = self.call("/api/reports", method="POST", body={"title": "Roundtrip", "severity": "minor"})
        self.assertEqual(status, 200)
        rid = created["data"]["id"]
        self.assertEqual(self.call(f"/api/reports/{rid}")[1]["data"]["title"], "Roundtrip")
        self.assertEqual(self.call("/api/reports")[1]["data"][0]["id"], rid)

    def test_background_image_roundtrip_with_a_large_body(self):   # Options: images above the usual 256 KB
        import base64
        png = b"\x89PNG\r\n\x1a\n" + bytes(600_000)
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        status, added = self.call("/api/backgrounds", method="POST", body={"name": "map.png", "data": uri})
        self.assertEqual(status, 200, added)
        bid = added["data"]["id"]
        self.assertEqual(self.call(f"/api/backgrounds/{bid}")[1]["data"]["uri"], uri)
        self.assertEqual(self.call(f"/api/backgrounds/{bid}/delete", method="POST", body={})[1]["data"], [])
        self.assertEqual(self.call("/api/reports", method="POST", body={"title": "x" * 300_000})[0], 413)

    def test_invalid_json_body(self):
        req = urllib.request.Request(self.base + "/api/reports", data=b"{not json", method="POST")
        req.add_header(TOKEN_HEADER, TOKEN)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        ctx.exception.close()
        self.assertEqual(ctx.exception.code, 400)


class EntryPointTests(TempDirMixin, unittest.TestCase):
    def test_process_prints_ready_and_exits_when_stdin_closes(self):
        env = {**os.environ, "HOI4DBG_DATA_DIR": str(self.tmp), "HOI4DBG_TOKEN": TOKEN,
               "PYTHONPATH": str(BACKEND_DIR)}
        proc = subprocess.Popen([sys.executable, "-m", "hoi4dbg", "--no-game", "--watch-stdin"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
        try:
            ready = json.loads(proc.stdout.readline())
            self.assertEqual(ready["event"], "ready")
            self.assertNotIn("token", ready)  # token supplied by parent is never echoed
            req = urllib.request.Request(f"http://127.0.0.1:{ready['port']}/api/status")
            req.add_header(TOKEN_HEADER, TOKEN)
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertFalse(json.loads(resp.read())["game"]["detected"])
            proc.stdin.close()
            self.assertEqual(proc.wait(timeout=10), 0)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
