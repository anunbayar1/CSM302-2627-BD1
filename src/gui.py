#!/usr/bin/env python3
"""Web UI for the Producer-Consumer (bounded buffer) simulation.

A small standard-library HTTP server with three pages:

    /       home page: choose one of the two views
    /mail   Python engine (bounded_buffer.py) drawn as a mailbox, with voice tour
    /raw    C/Pthreads engine (src/c, `producer_consumer --ui`) shown plainly:
            buffer, semaphore values, thread states and the program's own log

API: /api/py/<action> and /api/c/<action>  (state, start, pause, resume, step,
tune, stop, reset). Both engines can run at the same time.

    python3 src/gui.py                  # opens http://127.0.0.1:8765
    python3 src/gui.py --port 9000 --no-browser
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bounded_buffer import Simulation, validate_params  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.realpath(os.path.join(HERE, "ui"))
PAGES = {"/": "home.html", "/index.html": "home.html", "/mail": "mail.html", "/raw": "raw.html"}
MAX_EVENTS = 5000
C_DIR = os.path.join(HERE, "c")
C_BIN = os.path.join(C_DIR, "producer_consumer")
C_SOURCES = ("main.c", "buffer.c", "ui.c", "buffer.h", "sim.h", "Makefile")

# validate_params() speaks English; the UI speaks Mongolian.
FIELD_MN = {
    "Buffer size": "Буферийн хэмжээ (buffer size)",
    "Producers": "Producer-ийн тоо",
    "Consumers": "Consumer-ийн тоо",
    "Producer max sleep": "Producer-ийн амралт (sleep)",
    "Consumer max sleep": "Consumer-ийн амралт (sleep)",
    "Speed": "Хурд",
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


def build_c_engine(force=False):
    """Compile src/c with make when the binary is missing or older than the sources.
    force=True (server start) always rebuilds: files unpacked from a zip or a git checkout can
    carry old timestamps, and an old binary would not understand the new options."""
    srcs = [os.path.join(C_DIR, f) for f in C_SOURCES]
    have = os.path.isfile(C_BIN)
    if have and not force and os.path.getmtime(C_BIN) >= max(map(os.path.getmtime, srcs)):
        return C_BIN
    if not shutil.which("make") or not (shutil.which("gcc") or shutil.which("cc")):
        if have:
            return C_BIN
        raise RuntimeError("gcc/make олдсонгүй (sudo apt install build-essential)")
    r = subprocess.run(["make", "-s"] + (["-B"] if force else []), cwd=C_DIR, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(C_BIN):
        raise RuntimeError("C программыг хөрвүүлж чадсангүй:\n" + r.stderr.strip())
    return C_BIN


def check_params(cfg):
    """Validate the form values (Mongolian messages); returns the cleaned numbers."""
    try:
        size, p, c, ps, cs = validate_params(cfg.get("size"), cfg.get("prod"), cfg.get("cons"),
                                             cfg.get("psleep"), cfg.get("csleep"))
        sp = check_speed(cfg.get("speed", 1))
    except ValueError as e:
        raise ValueError(to_mongolian(str(e)))
    return size, p, c, ps, cs, sp


def check_speed(v):
    try:
        sp = float(str(v).strip())
    except ValueError:
        raise ValueError(f"Speed must be a number (got {v!r}).")
    if not 0.25 <= sp <= 4:
        raise ValueError(f"Speed must be between 0.25 and 4.0 (got {sp}).")
    return sp


BUGS = ["none", "no_mutex", "no_empty", "no_full", "order"]   # C experiments (buffer.h BUG_*)


class CController:
    """Runs the C/Pthreads program in --ui mode and relays its output to the page."""

    def __init__(self):
        self.lock = threading.Lock()      # guards proc / run bookkeeping
        self.ev_lock = threading.Lock()   # guards snap / events (written by the reader thread)
        self.proc = None
        self.reader = None
        self.snap = None
        self.events = []
        self.seq = 0
        self.run_id = 0
        self.config = None
        self.error = ""

    def _alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, cfg):
        with self.lock:
            if self._alive():
                raise ValueError("Симуляци ажиллаж байна. Эхлээд «Зогсоох» дарна уу.")
            size, p, c, ps, cs, sp = check_params(cfg)
            paused = bool(cfg.get("paused"))
            bug = str(cfg.get("bug", "none")).replace("-", "_")
            if cfg.get("mutex", True) in (False, 0, "0", "false", "off"):
                bug = "no_mutex"
            if bug not in BUGS:
                raise ValueError("Алдааны төрөл буруу: " + ", ".join(BUGS))
            mutex = bug != "no_mutex"
            build_c_engine()
            proc = subprocess.Popen(
                [C_BIN, "--ui", str(size), str(p), str(c), repr(ps), repr(cs), repr(sp),
                 "1" if paused else "0", str(BUGS.index(bug))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1)
            names = [f"P{i + 1}" for i in range(p)] + [f"C{i + 1}" for i in range(c)]
            with self.ev_lock:
                self.events = []
                self.snap = dict(engine="c", slots=[None] * size, in_idx=0, out_idx=0, last=None,
                                 empty=size, full=0, mutex_locked=False,
                                 states={n: "idle" for n in names}, produced=0, consumed=0,
                                 mutex_on=mutex, lost=0, bad_reads=0, bug=bug, deadlock=False,
                                 owner=None, waits={n: "" for n in names}, paused=paused, stopped=False, speed=sp, prod_sleep=ps,
                                 cons_sleep=cs, elapsed=0.0)
                self.proc = proc
            self.run_id += 1
            self.config = dict(size=size, prod=p, cons=c, psleep=ps, csleep=cs, bug=bug)
            self.error = ""
            self.reader = threading.Thread(target=self._read, args=(proc,), daemon=True)
            self.reader.start()

    def _read(self, proc):
        """Parse the C program's stdout: E (event), S (state), END."""
        for line in proc.stdout:
            if line.startswith("E "):
                parts = line.split()
                if len(parts) not in (6, 7, 8):
                    continue
                _, kind, who, slot, item, t = parts[:6]
                count = int(parts[6]) if len(parts) >= 7 else None
                err = int(parts[7]) if len(parts) == 8 else 0
                with self.ev_lock:
                    if proc is not self.proc:
                        continue
                    self.seq += 1
                    self.events.append(dict(seq=self.seq, kind="insert" if kind == "I" else "remove",
                                            who=who, slot=int(slot), item=int(item), t=float(t),
                                            count=count, err=err))
                    if len(self.events) > MAX_EVENTS:
                        del self.events[:-MAX_EVENTS]
            elif line.startswith("S "):
                try:
                    snap = json.loads(line[2:])
                except ValueError:
                    continue
                with self.ev_lock:
                    if proc is self.proc:
                        self.snap = snap

        if proc is self.proc and proc.wait() > 0:       # ended by itself with an error
            msg = (proc.stderr.read() or "").strip().splitlines()
            self.error = "C программ алдаатай зогслоо: " + (msg[0] if msg else f"exit {proc.returncode}")

    def _send(self, cmd):
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.write(cmd + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def _patch(self, **kw):           # show the change at once; the next S line confirms it
        with self.ev_lock:
            if self.snap is not None and not self.snap.get("stopped"):
                self.snap.update(kw)

    def pause(self):
        self._send("pause"); self._patch(paused=True)

    def resume(self):
        self._send("resume"); self._patch(paused=False)

    def step(self):
        self._send("step"); self._patch(paused=True)

    def tune(self, cfg):
        if not self._alive():
            raise ValueError("Симуляци ажиллаагүй байна.")
        cur = self.config
        ps, cs, sp = cfg.get("psleep"), cfg.get("csleep"), cfg.get("speed")
        try:
            _, _, _, ps2, cs2 = validate_params(cur["size"], cur["prod"], cur["cons"],
                                                cur["psleep"] if ps is None else ps,
                                                cur["csleep"] if cs is None else cs)
            sp2 = None if sp is None else check_speed(sp)
        except ValueError as e:
            raise ValueError(to_mongolian(str(e)))
        self._send(f"tune {ps2!r} {cs2!r} {'-' if sp2 is None else repr(sp2)}")
        cur.update(psleep=ps2, csleep=cs2)
        patch = dict(prod_sleep=ps2, cons_sleep=cs2)
        if sp2 is not None:
            patch["speed"] = sp2
        self._patch(**patch)

    def stop(self):
        proc, reader = self.proc, self.reader
        if proc is None or proc.poll() is not None:
            return
        self._send("stop")
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if reader:
            reader.join(timeout=2)    # make sure the final snapshot has been read
        self._patch(stopped=True)

    def reset(self):
        self.stop()
        with self.lock:
            with self.ev_lock:
                self.proc = None
                self.snap = None
                self.events = []
            self.config = None
            self.run_id += 1

    def state(self, since=0):
        with self.lock:
            run, cfg = self.run_id, self.config
        with self.ev_lock:
            if self.proc is None or self.snap is None:
                return dict(run=run, seq=self.seq, sim=None, events=[], config=None)
            snap = dict(self.snap)
            if self.proc.poll() is not None:
                snap["stopped"] = True
            events = [e for e in self.events if e["seq"] > since]
            seq = self.seq
        out = dict(run=run, seq=seq, sim=snap, events=events, config=cfg)
        if self.error:
            out["error"] = self.error
        return out


class Controller:
    """Same interface, but runs the Python port of the algorithm (bounded_buffer.py)."""

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
                if cfg.get("speed") is not None:
                    sim.set_speeds(speed=cfg.get("speed"))
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

    def tune(self, cfg):
        """Change speed / sleep limits of the running simulation."""
        sim = self._current()
        if not sim or sim.stop.is_set():
            raise ValueError("Симуляци ажиллаагүй байна.")
        try:
            sim.set_speeds(cfg.get("psleep"), cfg.get("csleep"), cfg.get("speed"))
        except ValueError as e:
            raise ValueError(to_mongolian(str(e)))
        with self.lock:
            if self.config is not None:
                self.config.update(psleep=sim.prod_sleep, csleep=sim.cons_sleep)

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
        snap["engine"] = "python"
        end = self.stopped_at if snap["stopped"] and self.stopped_at else time.monotonic()
        snap["elapsed"] = round(end - sim.t0, 2) if sim.t0 else 0.0
        with self.ev_lock:
            events = [e for e in self.events if e["seq"] > since]
            seq = self.seq
        return dict(run=run, seq=seq, sim=snap, events=events, config=cfg)


API = re.compile(r"^/api/(py|c)/(\w+)$")


def make_handler(ctls, c_error=""):
    """ctls = {"py": Controller, "c": CController or None}."""
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

        def _static(self, path):
            """Serve tour.json and the generated voice files (ui/voice/...) only."""
            types = {".json": "application/json; charset=utf-8", ".mp3": "audio/mpeg"}
            full = os.path.realpath(os.path.join(UI_DIR, path.lstrip("/")))
            ext = os.path.splitext(full)[1]
            if path == "/voice/manifest.json" and not os.path.isfile(full):
                return self._json(200, {})          # no voice generated yet
            if not full.startswith(UI_DIR + os.sep) or ext not in types or not os.path.isfile(full):
                return self._json(404, {"error": "not found"})
            with open(full, "rb") as f:
                self._send(200, f.read(), types[ext])

        def _ctl(self, engine):
            ctl = ctls.get(engine)
            if ctl is None:
                self._json(503, {"error": c_error or "C хөдөлгүүр бэлэн биш байна."})
            return ctl

        def do_GET(self):
            path, _, query = self.path.partition("?")
            m = API.match(path)
            if path in PAGES:
                with open(os.path.join(UI_DIR, PAGES[path]), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif path == "/tour.json" or path.startswith("/voice/"):
                self._static(path)
            elif m and m.group(2) == "state":
                ctl = self._ctl(m.group(1))
                if ctl is None:
                    return
                try:
                    since = int(parse_qs(query).get("since", ["0"])[0])
                except ValueError:
                    since = 0
                self._json(200, ctl.state(since))
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            m = API.match(self.path)
            if not m:
                return self._json(404, {"error": "not found"})
            ctl = self._ctl(m.group(1))
            if ctl is None:
                return
            action = m.group(2)
            simple = {"pause": ctl.pause, "resume": ctl.resume, "step": ctl.step,
                      "stop": ctl.stop, "reset": ctl.reset}
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}") if n else {}
                data = data if isinstance(data, dict) else {}
                if action == "start":
                    ctl.start(data)
                elif action == "tune":
                    ctl.tune(data)
                elif action in simple:
                    simple[action]()
                else:
                    return self._json(404, {"error": "not found"})
                self._json(200, {"ok": True})
            except ValueError as e:      # includes bad JSON
                self._json(400, {"error": str(e)})
            except RuntimeError as e:    # C program could not be built / started
                self._json(503, {"error": str(e)})

    return Handler


def make_controllers():
    """Python engine always; C engine if it can be built (else None + the reason)."""
    ctls, err = {"py": Controller(), "c": None}, ""
    try:
        build_c_engine(force=True)
        ctls["c"] = CController()
    except RuntimeError as e:
        err = str(e)
    return ctls, err


def serve(host="127.0.0.1", port=8765, ctls=None, c_error=""):
    """Create the server; if the port is busy, try the next ones (port=0 → any free port)."""
    if ctls is None:
        ctls, c_error = make_controllers()
    last = None
    for p in (range(port, port + 20) if port else [0]):
        try:
            srv = ThreadingHTTPServer((host, p), make_handler(ctls, c_error))
            srv.daemon_threads = True
            return srv, ctls
        except OSError as e:
            last = e
    raise last


def main(argv=None):
    ap = argparse.ArgumentParser(description="Producer-Consumer web UI (шуудангийн хайрцаг)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="браузер автоматаар нээхгүй")
    args = ap.parse_args(argv)

    ctls, c_error = make_controllers()
    srv, _ = serve(args.host, args.port, ctls, c_error)
    url = f"http://{args.host}:{srv.server_address[1]}/"
    print(f"Нүүр хуудас:            {url}")
    print(f"  Python · шуудан:      {url}mail")
    print(f"  C · Pthreads · шууд:  {url}raw" + ("" if ctls["c"] else f"   (ажиллахгүй: {c_error})"))
    print("Браузер нээгдэхгүй бол дээрх хаягийг өөрөө нээнэ үү. Зогсоох: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nХаалаа.")
    finally:
        for ctl in ctls.values():
            if ctl:
                ctl.stop()
        srv.server_close()


if __name__ == "__main__":
    main()
