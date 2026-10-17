"""段階1の法律の額は参考だけで、合計・公開・議員への配分に使わないことを、保存済みの出力で確かめる。"""
import csv
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Stage1ReferenceTest(unittest.TestCase):
    def setUp(self):
        self.loss = rows(DERIVED / "loss-v1-triage-v2" / "loss.csv")
        self.publish = {r["id"]: r for r in rows(DERIVED / "publish-v1-triage-v2" / "publish.csv")}
        self.stage1 = [r for r in self.loss if r["段階"] == "段階1"]

    def test_stage1_rows_exist_and_some_have_an_amount(self):
        self.assertTrue(self.stage1)
        self.assertTrue(any(r["損失または便益の額"] for r in self.stage1))

    def test_every_stage1_row_is_marked_reference_with_reason(self):
        for r in self.stage1:
            self.assertEqual(r["参考フラグ"], "参考", r["id"])
            self.assertTrue(r["理由"].startswith("参考（段階1）："), r["id"])

    def test_stage1_rows_are_never_publishable(self):
        for r in self.stage1:
            self.assertEqual(self.publish[r["id"]]["公開可否"], "公開不可", r["id"])
            self.assertEqual(self.publish[r["id"]]["判定表の行"], "R1", r["id"])

    def test_reference_rows_are_not_counted_as_amounted(self):
        amounted = [r for r in self.loss if r["損失または便益の額"] and r["参考フラグ"] != "参考"]
        self.assertTrue(all(r["段階"] in ("段階2", "段階3") for r in amounted))

    def test_v1_outputs_have_no_stage1_rows(self):
        v1 = rows(DERIVED / "loss-v1" / "loss.csv")
        self.assertFalse([r for r in v1 if r["段階"] == "段階1"])

    def test_allocation_skips_reference_rows_in_script(self):
        script = (ROOT / "app" / "scripts" / "run-allocation-v1.mjs").read_text(encoding="utf-8")
        self.assertIn("A.allocatable(", script)
        self.assertTrue(re.search(r"参考フラグ'\] === '参考'", script))


if __name__ == "__main__":
    unittest.main()
