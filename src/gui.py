#!/usr/bin/env python3
"""Web UI for the Producer-Consumer (bounded buffer) simulation.

Only the Python standard library is used: a small local HTTP server drives the
real threads in bounded_buffer.py, and the browser page (ui/index.html) draws
them as a mailbox: senders (producers) put letters into the mailbox (buffer),
receivers (consumers) take them out.

    python3 src/gui.py                 # opens http://127.0.0.1:8765
    python3 src/gui.py --port 9000 --no-browser
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bounded_buffer import Simulation  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "ui", "index.html")
MAX_EVENTS = 5000

# validate_params() speaks English; the UI speaks Mongolian.
FIELD_MN = {
    "Buffer size": "Хайрцгийн нүдний тоо (buffer size)",
    "Producers": "Илгээгчийн тоо (producers)",
    "Consumers": "Хүлээн авагчийн тоо (consumers)",
    "Producer max sleep": "Илгээгчийн амралт (producer sleep)",
    "Consumer max sleep": "Хүлээн авагчийн амралт (consumer sleep)",
}


def to_mongolian(msg):
    m = re.match(r"(.+?) must be (an integer|a number) \(got (.*)\)\.?$", msg)
    if m:
        name = FIELD_MN.get(m.group(1), m.group(1))
        kind = "бүхэл тоо" if m.group(2) == "an integer" else "тоо"
        return f"{name} {kind} байх ёстой. Оруулсан утга: {m.group(3)}"
    m = re.match(r"(.+?) must be between (\S+) and (\S+?)(?: seconds)? \(got (.*)\)\.?$", msg)
    if m:
        name = FIELD_MN.get(m.group(1), m.group(1))
        return f"{name} {m.group(2)}-{m.group(3)} хооронд байх ёстой. Оруулсан утга: {m.group(4)}"
    return msg


class Controller:
    """Owns the current Simulation and the list of buffer events for the page."""

    def __init__(self):
        self.lock = threading.Lock()     # guards sim / run bookkeeping
        self.ev_lock = threading.Lock()  # guards events (taken from worker threads)
        self.sim = None
        self.config = None
        self.events = []
        self.seq = 0
        self.run_id = 0
        self.stopped_at = None

    # called by worker threads (inside the buffer mutex) for every insert/remove
    def _push(self, sim, kind, who, slot, item):
        with self.ev_lock:
            if sim is not self.sim:
                return
            self.seq += 1
            t = time.monotonic() - (sim.t0 or time.monotonic())
            self.events.append(dict(seq=self.seq, kind=kind, who=who, slot=slot,
                                    item=item, t=round(t, 3)))
            if len(self.events) > MAX_EVENTS:
                del self.events[:-MAX_EVENTS]

    def start(self, cfg):
        with self.lock:
            if self.sim and not self.sim.stop.is_set():
                raise ValueError("Симуляци ажиллаж байна. Эхлээд «Зогсоох» дарна уу.")
            try:
                sim = Simulation(cfg.get("size"), cfg.get("prod"), cfg.get("cons"),
                                 cfg.get("psleep"), cfg.get("csleep"))
            except ValueError as e:
                raise ValueError(to_mongolian(str(e)))
            orig = sim.buf.listener

            def listener(kind, slot, item, _orig=orig, _sim=sim):
                _orig(kind, slot, item)
                self._push(_sim, kind, threading.current_thread().name, slot, item)

            sim.buf.listener = listener
            with self.ev_lock:
                self.events = []
                self.sim = sim
            self.run_id += 1
            self.stopped_at = None
            self.config = dict(size=sim.buffer_size, prod=sim.n_prod, cons=sim.n_cons,
                               psleep=sim.prod_sleep, csleep=sim.cons_sleep)
            if cfg.get("paused"):
                sim.pause()
            sim.start()

    def _current(self):
        with self.lock:
            return self.sim

    def pause(self):
        sim = self._current()
        if sim and not sim.stop.is_set():
            sim.pause()

    def resume(self):
        sim = self._current()
        if sim and not sim.stop.is_set():
            sim.resume()

    def step(self):
        sim = self._current()
        if sim and not sim.stop.is_set():
            sim.step()

    def stop(self):
        sim = self._current()
        if sim and not sim.stop.is_set():
            self.stopped_at = time.monotonic()
            sim.stop_all()          # joins threads; done outside self.lock on purpose

    def reset(self):
        self.stop()
        with self.lock:
            with self.ev_lock:
                self.sim = None
                self.events = []
            self.config = None
            self.run_id += 1

    def state(self, since=0):
        with self.lock:
            sim, run, cfg = self.sim, self.run_id, self.config
        if sim is None:
            return dict(run=run, seq=self.seq, sim=None, events=[], config=None)
        snap = sim.snapshot()
        snap.pop("log", None)
        end = self.stopped_at if snap["stopped"] and self.stopped_at else time.monotonic()
        snap["elapsed"] = round(end - sim.t0, 2) if sim.t0 else 0.0
        with self.ev_lock:
            events = [e for e in self.events if e["seq"] > since]
            seq = self.seq
        return dict(run=run, seq=seq, sim=snap, events=events, config=cfg)


def make_handler(ctl):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                with open(INDEX, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif path == "/api/state":
                try:
                    since = int(parse_qs(query).get("since", ["0"])[0])
                except ValueError:
                    since = 0
                self._json(200, ctl.state(since))
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            actions = {"/api/pause": ctl.pause, "/api/resume": ctl.resume,
                       "/api/step": ctl.step, "/api/stop": ctl.stop, "/api/reset": ctl.reset}
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if self.path == "/api/start":
                    ctl.start(data if isinstance(data, dict) else {})
                elif self.path in actions:
                    actions[self.path]()
                else:
                    return self._json(404, {"error": "not found"})
                self._json(200, {"ok": True})
            except ValueError as e:      # includes bad JSON
                self._json(400, {"error": str(e)})

    return Handler


def serve(host="127.0.0.1", port=8765, ctl=None):
    """Create the server; if the port is busy, try the next ones (port=0 → any free port)."""
    ctl = ctl or Controller()
    last = None
    for p in (range(port, port + 20) if port else [0]):
        try:
            srv = ThreadingHTTPServer((host, p), make_handler(ctl))
            srv.daemon_threads = True
            return srv, ctl
        except OSError as e:
            last = e
    raise last


def main(argv=None):
    ap = argparse.ArgumentParser(description="Producer-Consumer web UI (шуудангийн хайрцаг)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="браузер автоматаар нээхгүй")
    args = ap.parse_args(argv)

    srv, ctl = serve(args.host, args.port)
    url = f"http://{args.host}:{srv.server_address[1]}/"
    print(f"Шуудангийн хайрцаг ажиллаж байна: {url}")
    print("Браузер нээгдэхгүй бол дээрх хаягийг өөрөө нээнэ үү. Зогсоох: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nХаалаа.")
    finally:
        ctl.stop()
        srv.server_close()


if __name__ == "__main__":
    main()
