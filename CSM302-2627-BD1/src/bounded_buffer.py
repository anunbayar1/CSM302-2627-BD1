#!/usr/bin/env python3
"""Producer-Consumer (bounded buffer) core. OS Concepts, ch.7 programming project.

CLI (textbook style):
    python src/bounded_buffer.py <run_seconds> <producers> <consumers> [buffer_size] [max_sleep]
"""
import random
import sys
import threading
import time


# ---------------------------------------------------------------- validation
def validate_params(buffer_size, producers, consumers, prod_sleep, cons_sleep):
    """Return normalized params or raise ValueError with a readable message."""
    def to_int(v, name, lo, hi):
        try:
            n = int(str(v).strip())
        except ValueError:
            raise ValueError(f"{name} must be an integer (got {v!r}).")
        if not lo <= n <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi} (got {n}).")
        return n

    def to_float(v, name, lo, hi):
        try:
            x = float(str(v).strip())
        except ValueError:
            raise ValueError(f"{name} must be a number (got {v!r}).")
        if not lo <= x <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi} seconds (got {x}).")
        return x

    return (to_int(buffer_size, "Buffer size", 1, 20),
            to_int(producers, "Producers", 1, 10),
            to_int(consumers, "Consumers", 1, 10),
            to_float(prod_sleep, "Producer max sleep", 0, 10),
            to_float(cons_sleep, "Consumer max sleep", 0, 10))


# ------------------------------------------------------------ bounded buffer
class BoundedBuffer:
    """Circular buffer guarded by empty/full semaphores and a mutex."""

    def __init__(self, size, stop_event=None, listener=None):
        if not isinstance(size, int) or size <= 0:
            raise ValueError("buffer size must be a positive integer")
        self.size = size
        self.slots = [None] * size
        self.in_idx = 0
        self.out_idx = 0
        self.last_slot = None
        self.empty = threading.Semaphore(size)   # free slots
        self.full = threading.Semaphore(0)       # used slots
        self.mutex = threading.Lock()
        self.stop = stop_event or threading.Event()
        self.listener = listener or (lambda kind, slot, item: None)
        # shadow counters, only for display (Semaphore has no public value)
        self._cnt = threading.Lock()
        self.empty_value = size
        self.full_value = 0

    def _acquire(self, sem):
        # timeout loop so blocked threads can exit when the run is stopped
        while not self.stop.is_set():
            if sem.acquire(timeout=0.05):
                return True
        return False

    def insert_item(self, item):
        """Return 0 on success, -1 on error/stop."""
        if not self._acquire(self.empty):
            return -1
        with self._cnt:
            self.empty_value -= 1
        with self.mutex:
            slot = self.in_idx
            self.slots[slot] = item
            self.in_idx = (slot + 1) % self.size
            self.last_slot = slot
            self.listener("insert", slot, item)
        with self._cnt:
            self.full_value += 1
        self.full.release()
        return 0

    def remove_item(self, out):
        """Append removed item to list `out`. Return 0 on success, -1 on error/stop."""
        if not self._acquire(self.full):
            return -1
        with self._cnt:
            self.full_value -= 1
        with self.mutex:
            slot = self.out_idx
            item = self.slots[slot]
            self.slots[slot] = None
            self.out_idx = (slot + 1) % self.size
            self.last_slot = slot
            out.append(item)
            self.listener("remove", slot, item)
        with self._cnt:
            self.empty_value += 1
        self.empty.release()
        return 0


# ------------------------------------------------------------------- workers
class Worker(threading.Thread):
    HOLD = 0.3  # seconds a "producing"/"consuming" state stays visible

    def __init__(self, sim, name, kind):
        super().__init__(name=name, daemon=True)
        self.sim, self.kind = sim, kind

    def run(self):
        s = self.sim
        while not s.stop.is_set():
            # read the limits every round so they can be tuned while running
            limit = s.prod_sleep if self.kind == "producer" else s.cons_sleep
            s.set_state(self.name, "sleeping")
            cap = (lambda: s.prod_sleep) if self.kind == "producer" else (lambda: s.cons_sleep)
            if not s.sleep(random.uniform(0, limit), cap):
                break
            if self.kind == "producer":
                item = random.randint(1, 99)
                s.set_state(self.name, "producing")
                if not s.sleep(self.HOLD) or not s.checkpoint(self.name):
                    break
                s.set_state(self.name, "waiting")
                if s.buf.insert_item(item) != 0:
                    break
            else:
                if not s.checkpoint(self.name):
                    break
                s.set_state(self.name, "waiting")
                if s.buf.remove_item([]) != 0:
                    break
                s.set_state(self.name, "consuming")
                if not s.sleep(self.HOLD):
                    break
        s.set_state(self.name, "stopped")


class Simulation:
    def __init__(self, buffer_size=5, producers=2, consumers=2,
                 prod_sleep=1.0, cons_sleep=1.0, verbose=False):
        (self.buffer_size, self.n_prod, self.n_cons,
         self.prod_sleep, self.cons_sleep) = validate_params(
            buffer_size, producers, consumers, prod_sleep, cons_sleep)
        self.verbose = verbose
        self.speed = 1.0          # global time multiplier (2.0 = twice as fast)
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.step_sem = threading.Semaphore(0)
        self.lock = threading.Lock()
        self.log_lines, self.states = [], {}
        self.produced = self.consumed = 0
        self.inserted_items, self.removed_items = [], []
        self.t0 = None
        self.buf = BoundedBuffer(self.buffer_size, self.stop, self._on_buffer)
        self.workers = ([Worker(self, f"P{i+1}", "producer") for i in range(self.n_prod)] +
                        [Worker(self, f"C{i+1}", "consumer") for i in range(self.n_cons)])
        for w in self.workers:
            self.states[w.name] = "idle"

    # called by the buffer while holding its mutex
    def _on_buffer(self, kind, slot, item):
        who = threading.current_thread().name
        with self.lock:
            if kind == "insert":
                self.produced += 1
                self.inserted_items.append(item)
                self._log(f"{who} inserted {item} at slot {slot}")
            else:
                self.consumed += 1
                self.removed_items.append(item)
                self._log(f"{who} removed {item} from slot {slot}")

    def _log(self, msg):  # caller holds self.lock
        t = time.monotonic() - (self.t0 or time.monotonic())
        line = f"[{t:6.2f}s] {msg}"
        self.log_lines.append(line)
        if self.verbose:
            print(line, flush=True)

    def set_state(self, name, state):
        with self.lock:
            self.states[name] = state

    def sleep(self, t, cap=None):
        """Sleep `t` simulated seconds; returns False if the run was stopped.

        Time runs `self.speed` times faster than real time, and `cap()` (the current
        max sleep) shortens the remaining wait, so tuning applies immediately.
        """
        left, last = t, time.monotonic()
        while left > 0:
            if self.stop.wait(min(left / self.speed, 0.05)):
                return False
            now = time.monotonic()
            left -= (now - last) * self.speed
            last = now
            if cap is not None:
                left = min(left, cap())
        return not self.stop.is_set()

    def checkpoint(self, name):
        """Gate used for Pause / Step. Returns False if the run was stopped."""
        if not self.paused.is_set():
            return not self.stop.is_set()
        self.set_state(name, "paused")
        while not self.stop.is_set():
            if not self.paused.is_set() or self.step_sem.acquire(timeout=0.05):
                return True
        return False

    # controls
    SPEED_MIN, SPEED_MAX = 0.25, 4.0

    def set_speeds(self, prod_sleep=None, cons_sleep=None, speed=None):
        """Change timing while the simulation runs. Raises ValueError on bad input."""
        _, _, _, ps, cs = validate_params(
            self.buffer_size, self.n_prod, self.n_cons,
            self.prod_sleep if prod_sleep is None else prod_sleep,
            self.cons_sleep if cons_sleep is None else cons_sleep)
        if speed is not None:
            try:
                sp = float(str(speed).strip())
            except ValueError:
                raise ValueError(f"Speed must be a number (got {speed!r}).")
            if not self.SPEED_MIN <= sp <= self.SPEED_MAX:
                raise ValueError(f"Speed must be between {self.SPEED_MIN} and {self.SPEED_MAX} "
                                 f"(got {sp}).")
            self.speed = sp
        self.prod_sleep, self.cons_sleep = ps, cs

    def start(self):
        self.t0 = time.monotonic()
        for w in self.workers:
            w.start()

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    def step(self):
        self.paused.set()
        self.step_sem.release()

    def stop_all(self):
        self.stop.set()
        for w in self.workers:
            if w.is_alive():
                w.join(timeout=1.0)

    def snapshot(self):
        b = self.buf
        with b.mutex:
            slots, in_idx, out_idx, last = list(b.slots), b.in_idx, b.out_idx, b.last_slot
        with b._cnt:
            empty_v, full_v = b.empty_value, b.full_value
        with self.lock:
            return dict(slots=slots, in_idx=in_idx, out_idx=out_idx, last=last,
                        empty=empty_v, full=full_v, mutex_locked=b.mutex.locked(),
                        states=dict(self.states), produced=self.produced,
                        consumed=self.consumed, log=list(self.log_lines),
                        paused=self.paused.is_set(), stopped=self.stop.is_set(),
                        speed=self.speed, prod_sleep=self.prod_sleep,
                        cons_sleep=self.cons_sleep)


# ----------------------------------------------------------------------- CLI
def main(argv):
    usage = ("usage: python src/bounded_buffer.py <run_seconds> <producers> "
             "<consumers> [buffer_size=5] [max_sleep=1.0]")
    if not 4 <= len(argv) <= 6:
        print(usage)
        return 1
    try:
        run_s = float(argv[1])
        if run_s <= 0:
            raise ValueError("run_seconds must be > 0.")
        size = argv[4] if len(argv) > 4 else 5
        slp = argv[5] if len(argv) > 5 else 1.0
        sim = Simulation(size, argv[2], argv[3], slp, slp, verbose=True)
    except ValueError as e:
        print(f"Error: {e}\n{usage}")
        return 1
    sim.start()
    time.sleep(run_s)
    sim.stop_all()
    snap = sim.snapshot()
    left = sum(x is not None for x in snap["slots"])
    ok = snap["produced"] - snap["consumed"] == left
    print(f"\nproduced={snap['produced']} consumed={snap['consumed']} in_buffer={left} "
          f"-> {'CONSISTENT' if ok else 'INCONSISTENT'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))