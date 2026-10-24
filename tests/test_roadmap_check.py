import tempfile
import unittest
from pathlib import Path

from scripts import roadmap_check

GOOD = """# x
## 残りの項目
最後の番号：R2
| # | 項目 | 担当 | 状態 | 根拠 |
|---|---|---|---|---|
| R1 | a | 甲 | 済 | PR #1 |
| R2 | b | 乙 | 進行中 | |
## 進め方
"""


class RoadmapCheckTest(unittest.TestCase):
    def test_repository_roadmap_and_adrs_pass(self):
        text = roadmap_check.ROADMAP.read_text(encoding="utf-8")
        self.assertEqual([], roadmap_check.check_roadmap(text))
        self.assertEqual([], roadmap_check.check_adrs(roadmap_check.ADR_DIR))

    def test_good_table(self):
        self.assertEqual(2, len(roadmap_check.roadmap_rows(GOOD)))
        self.assertEqual([], roadmap_check.check_roadmap(GOOD))

    def test_done_without_evidence_fails(self):
        bad = GOOD.replace("| R1 | a | 甲 | 済 | PR #1 |", "| R1 | a | 甲 | 済 | |")
        self.assertIn("R1：済なのに根拠が空", roadmap_check.check_roadmap(bad))

    def test_unknown_state_and_missing_owner_fail(self):
        bad = GOOD.replace("| R2 | b | 乙 | 進行中 | |", "| R2 | b |  | ブロック | |")
        problems = roadmap_check.check_roadmap(bad)
        self.assertIn("R2：担当が空", problems)
        self.assertTrue(any("ブロック" in p for p in problems))

    def test_malformed_rows_are_reported_not_skipped(self):
        for bad_line in ("| Rone | a | 甲 | 済 | PR #1 |", "| R1 | a | 甲 | 済 |", "| R1 | a | 甲 | 済 | PR | #1 |", "R1 | a | 甲 | 済 | PR #1 |"):
            bad = GOOD.replace("| R1 | a | 甲 | 済 | PR #1 |", bad_line)
            self.assertTrue(any("形の崩れた行" in p for p in roadmap_check.check_roadmap(bad)), bad_line)

    def test_adr_needs_dedicated_metadata_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr = Path(tmp) / "0001-x.md"
            adr.write_text("# 題\n\n入力の日付と実装状態を保存する。\n", encoding="utf-8")
            self.assertTrue(any("日付" in p for p in roadmap_check.check_adrs(Path(tmp))))
            for empty in ("日付：。状態：。", "日付：2026-10-17。状態：", "日付：2026-10-17。"):
                adr.write_text(f"# 題\n\n{empty}\n", encoding="utf-8")
                self.assertTrue(roadmap_check.check_adrs(Path(tmp)), empty)
            adr.write_text("# 題\n\n日付：2026-10-17。状態：採用。\n", encoding="utf-8")
            self.assertEqual([], roadmap_check.check_adrs(Path(tmp)))
            (Path(tmp) / "0002_bad.md").write_text("# 題\n\n日付：2026-10-17。状態：採用。\n", encoding="utf-8")
            self.assertTrue(any("0002_bad.md" in p for p in roadmap_check.check_adrs(Path(tmp))))

    def test_rows_after_blank_line_are_checked(self):
        bad = GOOD.replace("| R2 |", "\n| R3 |")
        self.assertIn("欠番（消えた行）：R2", roadmap_check.check_roadmap(bad))
        self.assertEqual(2, len(roadmap_check.roadmap_rows(bad)))

    def test_removed_last_row_is_detected(self):
        bad = GOOD.replace("| R2 | b | 乙 | 進行中 | |\n", "")
        self.assertIn("欠番（消えた行）：R2", roadmap_check.check_roadmap(bad))
        self.assertTrue(any("最後の番号" in p for p in roadmap_check.check_roadmap(GOOD.replace("最後の番号：R2\n", ""))))

    def test_no_adr_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("ADR が1件も無い", roadmap_check.check_adrs(Path(tmp)))

    def test_missing_id_fails(self):
        bad = GOOD.replace("| R2 |", "| R3 |")
        self.assertIn("欠番（消えた行）：R2", roadmap_check.check_roadmap(bad))

    def test_duplicate_id_fails(self):
        bad = GOOD.replace("| R2 |", "| R1 |")
        self.assertIn("R1：番号が重複", roadmap_check.check_roadmap(bad))


if __name__ == "__main__":
    unittest.main()
