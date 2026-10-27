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

    def test_bad_arguments_rejected(self):
        for args in [(), (1, 2), (0, 1, 1), ("abc", 1, 1), (1, 0, 1), (1, 1, 101), (1, 1, 1, -1)]:
            r = self.run_bin(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
