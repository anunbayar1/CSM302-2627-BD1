import os, sys, threading, unittest
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from bounded_buffer import BoundedBuffer, Simulation, validate_params


class TestBuffer(unittest.TestCase):
    def test_fifo_and_wraparound(self):
        b = BoundedBuffer(3)
        for i in (1, 2, 3):
            self.assertEqual(b.insert_item(i), 0)
        out = []
        self.assertEqual(b.remove_item(out), 0)
        self.assertEqual(b.insert_item(4), 0)  # wraps to slot 0
        for _ in range(3):
            b.remove_item(out)
        self.assertEqual(out, [1, 2, 3, 4])

    def test_insert_into_full_returns_minus1_on_stop(self):
        ev = threading.Event()
        b = BoundedBuffer(1, ev)
        b.insert_item(1)
        threading.Timer(0.2, ev.set).start()
        self.assertEqual(b.insert_item(2), -1)

    def test_remove_from_empty_returns_minus1_on_stop(self):
        ev = threading.Event()
        b = BoundedBuffer(2, ev)
        threading.Timer(0.2, ev.set).start()
        self.assertEqual(b.remove_item([]), -1)

    def test_bad_size(self):
        with self.assertRaises(ValueError):
            BoundedBuffer(0)


class TestValidation(unittest.TestCase):
    def test_bad_inputs(self):
        for args in [(0, 1, 1, 1, 1), (5, 0, 1, 1, 1), (5, 1, 99, 1, 1),
                     ("abc", 1, 1, 1, 1), (5, 1, 1, -1, 1), (5, 1, 1, "x", 1)]:
            with self.assertRaises(ValueError, msg=str(args)):
                validate_params(*args)

    def test_good(self):
        self.assertEqual(validate_params("5", "2", "3", "0.5", "1"), (5, 2, 3, 0.5, 1.0))


class TestConcurrency(unittest.TestCase):
    def run_sim(self, size, p, c, ps, cs, secs=1.5):
        sim = Simulation(size, p, c, ps, cs)
        sim.start()
        threading.Event().wait(secs)
        sim.stop_all()
        s = sim.snapshot()
        left = [x for x in s["slots"] if x is not None]
        self.assertEqual(s["produced"] - s["consumed"], len(left))
        self.assertGreater(s["produced"], 0)
        diff = Counter(sim.inserted_items) - Counter(sim.removed_items)  # nothing lost/duplicated
        self.assertEqual(sorted(diff.elements()), sorted(left))
        self.assertLessEqual(len(left), size)

    def test_balanced(self):       self.run_sim(5, 3, 3, 0.05, 0.05)
    def test_size_one(self):       self.run_sim(1, 4, 4, 0.02, 0.02)
    def test_fast_producers(self): self.run_sim(3, 8, 1, 0.0, 0.1)   # buffer fills
    def test_fast_consumers(self): self.run_sim(3, 1, 8, 0.1, 0.0)   # buffer empties


class TestLiveTuning(unittest.TestCase):
    def test_set_speeds_validates_and_applies(self):
        sim = Simulation(5, 1, 1, 1.0, 1.0)
        sim.set_speeds(prod_sleep=0.2, cons_sleep="3", speed=2)
        self.assertEqual((sim.prod_sleep, sim.cons_sleep, sim.speed), (0.2, 3.0, 2.0))
        for bad in [dict(prod_sleep=-1), dict(cons_sleep="x"), dict(speed=0), dict(speed=10)]:
            with self.assertRaises(ValueError, msg=str(bad)):
                sim.set_speeds(**bad)
        self.assertEqual((sim.prod_sleep, sim.cons_sleep, sim.speed), (0.2, 3.0, 2.0))

    def test_speed_change_takes_effect_while_running(self):
        sim = Simulation(5, 2, 2, 10, 10)   # very slow: ~nothing happens in 1 s
        sim.start()
        threading.Event().wait(1.0)
        slow = sim.snapshot()["produced"]
        sim.set_speeds(prod_sleep=0.01, cons_sleep=0.01, speed=4)
        threading.Event().wait(1.0)
        sim.stop_all()
        s = sim.snapshot()
        self.assertGreater(s["produced"], slow + 5)
        self.assertEqual(s["produced"] - s["consumed"], sum(x is not None for x in s["slots"]))


if __name__ == "__main__":
    unittest.main()