"""Builds and runs the textbook Pthreads version (src/c). Skipped if gcc/make are missing."""
import os, shutil, subprocess, unittest

C_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "c")
BIN = os.path.join(C_DIR, "producer_consumer")


@unittest.skipUnless(shutil.which("make") and shutil.which("gcc"), "gcc/make not installed")
class TestPthreadsVersion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["make", "-s", "-B"], cwd=C_DIR, check=True)

    def run_bin(self, *args):
        return subprocess.run([BIN, *map(str, args)], capture_output=True, text=True, timeout=30)

    def test_consistent_runs(self):
        for p, c in [(1, 1), (3, 3), (6, 1), (1, 6)]:
            r = self.run_bin("-q", 1, p, c, 0.02)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("CONSISTENT", r.stdout)

    def test_log_shows_produce_and_consume(self):
        r = self.run_bin(1, 2, 2, 0.05)
        self.assertIn("produced", r.stdout)
        self.assertIn("consumed", r.stdout)

    def test_with_mutex_no_race(self):
        r = self.run_bin("-q", 1, 8, 8, 0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("errors:", r.stdout)

    def test_without_mutex_race_detected(self):
        r = self.run_bin("-q", "--no-mutex", 1, 8, 8, 0)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("INCONSISTENT", r.stdout)
        self.assertIn("errors: lost_items=", r.stdout)

    def test_other_bugs(self):
        r = self.run_bin("-q", "--bug", "no-empty", 1, 4, 1, 0.01)      # producers outrun: overflow
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"lost_items=[1-9]")
        r = self.run_bin("-q", "--bug", "no-full", 1, 1, 4, 0.01)       # consumers outrun: underflow
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"bad_reads=[1-9]")
        r = self.run_bin("-q", "--bug", "order", 2, 2, 2, 0.05)         # lock before wait: deadlock
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("DEADLOCK", r.stdout)
        r = self.run_bin("--bug", "nonsense", 1, 1, 1)
        self.assertEqual(r.returncode, 1)

    def test_bad_arguments_rejected(self):
        for args in [(), (1, 2), (0, 1, 1), ("abc", 1, 1), (1, 0, 1), (1, 1, 101), (1, 1, 1, -1)]:
            r = self.run_bin(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
