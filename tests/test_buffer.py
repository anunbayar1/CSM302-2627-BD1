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


if __name__ == "__main__":
    unittest.main()