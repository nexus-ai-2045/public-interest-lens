"""CI が使う並列実行 scripts/run_tests_parallel.py が、試験を1本も落とさないことを確かめる。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import run_tests_parallel as rtp  # noqa: E402


class RunTestsParallelTest(unittest.TestCase):
    def test_every_test_file_is_listed(self):
        on_disk = {p.stem for p in (ROOT / "tests").glob("test_*.py")}
        self.assertEqual(set(rtp.modules()), on_disk)
        self.assertIn("test_evaluation_logic", on_disk)

    def test_per_test_split_keeps_every_test_of_the_module(self):
        for name in rtp.PER_TEST:
            direct = unittest.defaultTestLoader.loadTestsFromName(name).countTestCases()
            self.assertEqual(len(rtp.targets([name])), direct, name)
            self.assertTrue(all(t.startswith(name + ".") for t in rtp.targets([name])))

    def test_other_modules_stay_whole(self):
        self.assertEqual(rtp.targets(["test_evaluation_logic"]), ["test_evaluation_logic"])


if __name__ == "__main__":
    unittest.main()
