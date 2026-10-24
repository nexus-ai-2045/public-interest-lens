"""段階1の法律の額は「確かさ：低」の額として数え、貸出残高だけが参考。議員への配分には使わないことを、保存済みの出力で確かめる。"""
import csv
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"

LOW = "低（段階1：経済全体の指標で未確認）"
LOAN = "参考（貸出残高を多いほど良いとみなす機械的仮定）"
PROXY = "参考（代理の指標）"
BY_STAGE = {"段階1": LOW, "段階2": "中（段階2）", "段階3": "高（段階3）"}


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Stage1LowConfidenceTest(unittest.TestCase):
    def setUp(self):
        self.loss = rows(DERIVED / "loss-v1-triage-v2" / "loss.csv")
        self.publish = {r["id"]: r for r in rows(DERIVED / "publish-v1-triage-v2" / "publish.csv")}
        self.stage1 = [r for r in self.loss if r["段階"] == "段階1"]
        self.low = [r for r in self.stage1 if r["確かさ"] == LOW]

    def test_every_row_has_a_confidence_label_in_loss_and_publish(self):
        for r in self.loss:
            self.assertIn(r["確かさ"], (*BY_STAGE.values(), LOAN, PROXY), r["id"])
            self.assertEqual(self.publish[r["id"]]["確かさ"], r["確かさ"], r["id"])

    def test_confidence_follows_stage_except_loan_reference(self):
        for r in self.loss:
            reference = PROXY if "（代理）" in r["指標"] else LOAN
            expected = reference if r["参考フラグ"] == "参考" else BY_STAGE[r["段階"]]
            self.assertEqual(r["確かさ"], expected, r["id"])

    def test_stage1_low_rows_exist_and_some_have_an_amount(self):
        self.assertTrue(self.low)
        self.assertTrue(any(r["損失または便益の額"] for r in self.low))

    def test_stage1_low_rows_are_amounts_not_reference(self):
        for r in self.low:
            self.assertEqual(r["参考フラグ"], "", r["id"])
            self.assertTrue(r["理由"].startswith("確かさ低（段階1）："), r["id"])

    def test_only_loan_and_proxy_rows_are_reference(self):
        for r in self.loss:
            if r["参考フラグ"] == "参考":
                self.assertEqual(r["確かさ"], PROXY if "（代理）" in r["指標"] else LOAN, r["id"])
                self.assertEqual(self.publish[r["id"]]["公開可否"], "公開不可", r["id"])
                self.assertEqual(self.publish[r["id"]]["判定表の行"], "R1", r["id"])
            else:
                self.assertNotIn(r["確かさ"], (LOAN, PROXY), r["id"])

    def test_stage1_low_rows_go_through_the_publish_table_like_other_amounts(self):
        # 参考ではないので R1（参考）では止まらない。止まるなら loss-v1 の保留か、他の行（R4 など）の理由による。
        for r in self.low:
            p = self.publish[r["id"]]
            if r["損失または便益の額"]:
                self.assertNotEqual(p["判定表の行"], "R1", r["id"])
            if p["公開可否"] == "公開可":
                self.assertIn("確かさ低（段階1", p["理由"], r["id"])

    def test_amounted_rows_include_stage1_low_but_not_loan_reference(self):
        amounted = [r for r in self.loss if r["損失または便益の額"] and r["参考フラグ"] != "参考"]
        self.assertTrue(any(r["段階"] == "段階1" for r in amounted))
        self.assertTrue(all(r["確かさ"] != LOAN for r in amounted))

    def test_v1_outputs_have_no_stage1_rows(self):
        v1 = rows(DERIVED / "loss-v1" / "loss.csv")
        self.assertFalse([r for r in v1 if r["段階"] == "段階1"])

    def test_allocation_skips_reference_and_low_confidence_rows_in_script(self):
        script = (ROOT / "app" / "scripts" / "run-allocation-v1.mjs").read_text(encoding="utf-8")
        self.assertIn("A.allocatable(", script)
        self.assertTrue(re.search(r"参考フラグ'\] === '参考'", script))
        self.assertIn("'確かさ'", script)
        src = (ROOT / "app" / "src" / "allocation-batch.ts").read_text(encoding="utf-8")
        self.assertIn("!l.reference && !l.lowConfidence", src)


if __name__ == "__main__":
    unittest.main()
