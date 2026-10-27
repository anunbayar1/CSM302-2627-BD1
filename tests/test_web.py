"""Tests for the web UI server (src/gui.py): real HTTP calls against a local server."""
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import gui  # noqa: E402


class TestWebUI(unittest.TestCase):
    """Runs against the C/Pthreads engine (src/c), which the UI uses by default."""
    ENGINE = "c"
    PREFIX = "/api/c"

    @classmethod
    def make_ctl(cls):
        return gui.CController()

    @classmethod
    def setUpClass(cls):
        if cls.ENGINE == "c":
            try:
                gui.build_c_engine()
            except RuntimeError as e:
                raise unittest.SkipTest(str(e))
        cls.ctl = cls.make_ctl()
        ctls = {"py": None, "c": None}
        ctls["c" if cls.ENGINE == "c" else "py"] = cls.ctl
        cls.srv, _ = gui.serve("127.0.0.1", 0, ctls)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.ctl.stop()
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, path, body=None):
        path = path.replace("/api", self.PREFIX, 1)
        req = urllib.request.Request(self.base + path, data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def state(self, since=0):
        with urllib.request.urlopen(f"{self.base}{self.PREFIX}/state?since={since}") as r:
            return json.loads(r.read())

    def tearDown(self):
        self.post("/api/reset")

    def test_pages_served(self):
        for path, text in [("/", "Producer–Consumer"), ("/mail", "Шуудангийн хайрцаг"),
                           ("/raw", "Pthreads")]:
            with urllib.request.urlopen(self.base + path) as r:
                self.assertEqual(r.status, 200)
                self.assertIn(text.encode(), r.read(), path)

    def test_other_engine_missing_is_503(self):
        other = "/api/py" if self.ENGINE == "c" else "/api/c"
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + other + "/state")
        self.assertEqual(cm.exception.code, 503)

    def test_run_events_and_consistency(self):
        code, _ = self.post("/api/start", dict(size=3, prod=3, cons=2, psleep=0.05, csleep=0.05))
        self.assertEqual(code, 200)
        time.sleep(1.5)
        self.post("/api/stop")
        s = self.state()
        sim = s["sim"]
        self.assertTrue(sim["stopped"])
        left = sum(x is not None for x in sim["slots"])
        self.assertEqual(sim["produced"] - sim["consumed"], left)
        ins = sum(e["kind"] == "insert" for e in s["events"])
        rem = sum(e["kind"] == "remove" for e in s["events"])
        self.assertEqual((ins, rem), (sim["produced"], sim["consumed"]))

    def test_since_returns_only_new_events(self):
        self.post("/api/start", dict(size=2, prod=2, cons=2, psleep=0.02, csleep=0.02))
        time.sleep(0.6)
        first = self.state()
        later = self.state(first["seq"])
        self.assertTrue(all(e["seq"] > first["seq"] for e in later["events"]))

    def test_invalid_input_rejected_in_mongolian(self):
        for body in [dict(size=0, prod=1, cons=1, psleep=1, csleep=1),
                     dict(size="abc", prod=1, cons=1, psleep=1, csleep=1),
                     dict(size=5, prod=1, cons=99, psleep=1, csleep=1),
                     dict(size=5, prod=1, cons=1, psleep=-1, csleep=1)]:
            code, d = self.post("/api/start", body)
            self.assertEqual(code, 400, body)
            self.assertIn("байх ёстой", d["error"])

    def test_cannot_start_twice(self):
        self.post("/api/start", dict(size=5, prod=1, cons=1, psleep=1, csleep=1))
        code, _ = self.post("/api/start", dict(size=5, prod=1, cons=1, psleep=1, csleep=1))
        self.assertEqual(code, 400)

    def test_pause_step_resume(self):
        self.post("/api/start", dict(size=5, prod=2, cons=2, psleep=0, csleep=0, paused=True))
        time.sleep(0.4)
        s = self.state()["sim"]
        self.assertTrue(s["paused"])
        before = s["produced"] + s["consumed"]
        for _ in range(4):
            self.post("/api/step")
            time.sleep(0.5)
        s = self.state()["sim"]
        self.assertGreater(s["produced"] + s["consumed"], before)
        self.post("/api/resume")
        self.assertFalse(self.state()["sim"]["paused"])

    def test_mutex_off(self):
        if self.ENGINE != "c":
            self.skipTest("mutex switch is in the C engine only")
        self.post("/api/start", dict(size=4, prod=4, cons=2, psleep=0.1, csleep=0.1, mutex=False))
        time.sleep(0.5)
        s = self.state()["sim"]
        self.assertIs(s["mutex_on"], False)
        self.assertIn("lost", s)
        self.post("/api/stop")
        time.sleep(0.3)
        self.post("/api/reset")
        self.post("/api/start", dict(size=3, prod=1, cons=2, psleep=1, csleep=0.1, bug="order"))
        deadline = time.time() + 6
        while time.time() < deadline and not self.state()["sim"].get("deadlock"):
            time.sleep(0.2)
        self.assertTrue(self.state()["sim"]["deadlock"])
        self.post("/api/stop")
        time.sleep(0.3)
        self.post("/api/reset")
        code, body = self.post("/api/start", dict(size=3, prod=1, cons=1, psleep=1, csleep=1, bug="bogus"))
        self.assertEqual(code, 400)
        self.assertIn("Алдааны төрөл", body["error"])

    def test_live_tune(self):
        code, _ = self.post("/api/tune", dict(speed=2))
        self.assertEqual(code, 400)                      # nothing running yet
        self.post("/api/start", dict(size=5, prod=2, cons=2, psleep=1, csleep=1, speed=0.5))
        self.assertEqual(self.state()["sim"]["speed"], 0.5)
        code, _ = self.post("/api/tune", dict(speed=4, psleep=0.2, csleep=0.3))
        self.assertEqual(code, 200)
        sim = self.state()["sim"]
        self.assertEqual((sim["speed"], sim["prod_sleep"], sim["cons_sleep"]), (4.0, 0.2, 0.3))
        code, d = self.post("/api/tune", dict(speed=99))
        self.assertEqual(code, 400)
        self.assertIn("Хурд", d["error"])
        code, _ = self.post("/api/tune", dict(psleep=-5))
        self.assertEqual(code, 400)

    def test_tour_and_voice_files(self):
        with urllib.request.urlopen(self.base + "/tour.json") as r:
            tour = json.loads(r.read())
        for ex in tour["themes"]:
            steps = tour["themes"][ex]
            self.assertGreater(len(steps), 10)
            self.assertTrue(all(st["text"] for st in steps))
        self.assertEqual(list(tour["themes"]), ["mail"])
        with urllib.request.urlopen(self.base + "/voice/manifest.json") as r:
            self.assertIsInstance(json.loads(r.read()), dict)
        for bad in ("/voice/../gui.py", "/voice/%2e%2e/gui.py", "/voice/x.py"):
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as cm:
                urllib.request.urlopen(self.base + bad)
            self.assertEqual(cm.exception.code, 404)

    def test_reset_clears(self):
        self.post("/api/start", dict(size=5, prod=1, cons=1, psleep=0.1, csleep=0.1))
        self.post("/api/reset")
        self.assertIsNone(self.state()["sim"])


    def test_engine_reported(self):
        self.post("/api/start", dict(size=4, prod=1, cons=1, psleep=0.1, csleep=0.1))
        time.sleep(0.3)
        sim = self.state()["sim"]
        self.assertEqual(sim["engine"], self.ENGINE)
        self.assertEqual(len(sim["slots"]), 4)
        self.assertEqual(set(sim["states"]), {"P1", "C1"})


class TestWebUIPython(TestWebUI):
    """The same API tests against the Python port (python3 src/gui.py --engine python)."""
    ENGINE = "python"
    PREFIX = "/api/py"

    @classmethod
    def make_ctl(cls):
        return gui.Controller()


if __name__ == "__main__":
    unittest.main()
