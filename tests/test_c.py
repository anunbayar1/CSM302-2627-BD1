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

    def test_count_race_one_producer_one_consumer(self):
        # 1P/1C without the mutex: in/out are touched by one thread each, so no slot is lost,
        # but count++ / count-- race. That must be reported, not called CONSISTENT (review C1).
        r = self.run_bin("-q", "--bug", "no-mutex", 1, 1, 1, 0)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("INCONSISTENT", r.stdout)
        self.assertRegex(r.stdout, r"count_errors=[1-9]")

    def test_short_deadlock_found(self):
        # a run shorter than any timeout must still be reported as DEADLOCK (review C2)
        # A deadlock that has formed is always reported (exit 3). In a few % of 0.25 s runs it
        # has not formed yet; then the program must say so instead of hiding it.
        codes = []
        for _ in range(12):
            r = self.run_bin("-q", "--bug", "order", 0.25, 2, 2, 0.05)
            codes.append(r.returncode)
            if r.returncode == 3:
                self.assertIn("DEADLOCK", r.stdout)
            else:
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("no deadlock in this run yet", r.stdout)
            if codes.count(3) >= 3:
                break
        self.assertGreaterEqual(codes.count(3), 3, codes)

    def test_count_matches_items(self):
        r = self.run_bin("-q", 1, 4, 4, 0)
        self.assertRegex(r.stdout, r"in_buffer=(\d+) count=\1 -> CONSISTENT")

    def test_buffer_size_rebuild(self):
        # make BUFFER_SIZE=N must rebuild by itself (review M1); restore the default afterwards
        try:
            subprocess.run(["make", "-s", "BUFFER_SIZE=7"], cwd=C_DIR, check=True)
            self.assertIn("BUFFER_SIZE=7", self.run_bin("-q", 0.1, 1, 1).stdout)
        finally:
            subprocess.run(["make", "-s"], cwd=C_DIR, check=True)
        self.assertIn("BUFFER_SIZE=5", self.run_bin("-q", 0.1, 1, 1).stdout)
        r = subprocess.run(["make", "-s", "BUFFER_SIZE=0", "BIN=/tmp/pc_bad_size"], cwd=C_DIR,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("BUFFER_SIZE must be 1..20", r.stderr)

    def test_bad_arguments_rejected(self):
        for args in [(), (1, 2), (0, 1, 1), ("abc", 1, 1), (1, 0, 1), (1, 1, 101), (1, 1, 1, -1)]:
            r = self.run_bin(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
