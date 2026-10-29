import unittest
from datetime import date

from scripts import local_verify, loop_status

TABLE = """| 段 | 周期 | 回すもの | 記録 | 直す対象 |
|---|---|---|---|---|
| L1 変更 | 分 | a | b | c |
| L2 PR | 時間 | a | b |  |
"""


class LoopStatusTest(unittest.TestCase):
    def test_rows_are_parsed_and_incomplete_row_is_visible(self):
        rows = loop_status.loop_rows(TABLE)
        self.assertEqual(set(rows), {"L1", "L2"})
        self.assertTrue(all(rows["L1"]))
        self.assertFalse(all(rows["L2"]))

    def test_latest_improvement_date(self):
        text = "## 改善の記録\n| 日付 | 段 |\n|---|---|\n| 2026-10-17 | L1 |\n| 2026-10-29 | L5 |\n"
        self.assertEqual(loop_status.latest_improvement(text), date(2026, 10, 29))

    def test_repository_loops_have_no_failure(self):
        failed = [r for r in loop_status.check() if r[1] == "失敗"]
        self.assertEqual(failed, [])


class LocalVerifyTest(unittest.TestCase):
    def test_steps_come_from_the_ci_workflow(self):
        runs = [s["run"] for s in local_verify.load_steps()]
        self.assertTrue(any("unittest" in r for r in runs))
        self.assertTrue(any("npm test" in r for r in runs))

    def test_browser_download_is_skipped_locally(self):
        steps = local_verify.select(local_verify.load_steps(), local_verify.ALWAYS_SKIP)
        self.assertFalse(any("playwright install" in s["run"] for s in steps))


if __name__ == "__main__":
    unittest.main()
