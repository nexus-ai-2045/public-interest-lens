"""scripts/run_tests_parallel.py の skip の歯止め：一覧に無い skip を見つけ、一覧の skip は通す。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_tests_parallel as runner

OUT = """test_a (test_x.A.test_a)
説明の行 ... skipped 'x'
test_b (test_x.A.test_b) ... skipped 'y'
test_c (test_x.A.test_c) ... ok
"""


class SkipGuardTest(unittest.TestCase):
    def test_reads_skip_lines_with_and_without_docstring(self):
        self.assertEqual(runner.skipped_ids(OUT), {"test_x.A.test_a", "test_x.A.test_b"})

    def test_listed_skips_are_known(self):
        allowed = runner.allowed_skips()
        self.assertIn("test_io_ripple.TestAgainstOfficial.test_matches_official_inverse", allowed)
        self.assertIn("unittest.loader.ModuleSkipped.test_io_ripple", allowed)
        self.assertNotIn("test_x.A.test_a", allowed)

    def test_every_listed_id_has_a_reason(self):
        path = runner.TESTS / "allowed_skips.txt"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^\S+\t\S", line)


if __name__ == "__main__":
    unittest.main()
