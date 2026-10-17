"""bill-triage-v2 の2つの実装（app/src/indicator-pick.ts と scripts/triage_v2_line2.py）の出力が全題名で同じことと、
派生データの形（170本・語彙・一致表）を確かめる。規則の中身の正しさではなく、書き起こしの写し間違いと出力の食い違いを拾う。"""
import csv
import unittest
from pathlib import Path

from scripts import triage_v2_line2 as py

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "data" / "derived" / "bill-triage-v2"


def read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TriageV2Test(unittest.TestCase):
    def test_python_implementation_reproduces_the_typescript_line1_output(self):
        # 系統1のラベルは TypeScript の実装の出力。同じ入力（系統1のAIの種類・分野）をPython実装に通して、全行で同じになる。
        rows = read(V2 / "labels-line1.csv")
        self.assertEqual(len(rows), 170)
        for r in rows:
            out = py.triage(r["題名"], r["系統1_入力種類"], r["系統1_入力分野"])
            self.assertEqual(
                (out["verdict"], out["kind"], out["field"], out["indicator"], "／".join(out["rules"]), out["reason"]),
                (r["結果"], r["種類"], r["分野"], r["指標"], r["規則"], r["理由"]), r["id"])

    def test_line2_labels_are_what_the_script_produces(self):
        src = {r["id"]: r for r in read(ROOT / "data" / "derived" / "bill-triage-v1-line2" / "labels.csv")}
        rows = read(V2 / "labels-line2.csv")
        self.assertEqual([r["id"] for r in rows], list(src))
        for r in rows:
            out = py.triage(r["題名"], src[r["id"]]["系統2_種類"], src[r["id"]]["系統2_分野"])
            self.assertEqual((r["系統2_判定"], r["系統2_種類"], r["系統2_分野"], r["系統2_指標"]),
                             (out["verdict"], out["kind"], out["field"], out["indicator"]), r["id"])

    def test_both_lines_use_known_vocabulary(self):
        pick_indicators = {i for rows, default in py._PICK.values() for _, _, i in rows} | {d for _, d in py._PICK.values()}
        for name, cols in (("labels-line1.csv", ("結果", "種類", "分野", "指標")), ("labels-line2.csv", ("系統2_判定", "系統2_種類", "系統2_分野", "系統2_指標"))):
            for r in read(V2 / name):
                verdict, kind, field, indicator = (r[c] for c in cols)
                self.assertIn(verdict, {"評価対象", "評価対象外"}, r["id"])
                self.assertIn(kind, py.KINDS, r["id"])
                if field == py.NO_FIELD:
                    self.assertEqual(indicator, "", r["id"])
                else:
                    self.assertIn(field, py._PICK, r["id"])
                    self.assertIn(indicator, pick_indicators, r["id"])

    def test_agreement_csv_matches_the_two_label_files(self):
        l1 = {r["id"]: r for r in read(V2 / "labels-line1.csv")}
        l2 = {r["id"]: r for r in read(V2 / "labels-line2.csv")}
        ag = read(V2 / "agreement.csv")
        self.assertEqual(len(ag), 170)
        for r in ag:
            a, b = l1[r["id"]], l2[r["id"]]
            same = (a["結果"], a["分野"], a["指標"]) == (b["系統2_判定"], b["系統2_分野"], b["系統2_指標"])
            self.assertEqual(r["結果"], "採用" if same else "保留", r["id"])

    def test_v1_agreement_is_left_untouched(self):
        # 版を切り替えても、bill-triage-v1 の一致の表は 142/170 のまま（旧版の結果は上書きしない）
        ag = read(ROOT / "data" / "derived" / "bill-triage-v1" / "agreement.csv")
        self.assertEqual((len(ag), sum(r["結果"] == "採用" for r in ag)), (170, 142))

    def test_first_law_title(self):
        self.assertEqual(py.first_law("出入国管理及び難民認定法及び法務省設置法の一部を改正する法律案"), "出入国管理及び難民認定法の一部を改正する法律案")


if __name__ == "__main__":
    unittest.main()
