import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data" / "derived" / "bill-triage-old"


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class OldLawsTriageTest(unittest.TestCase):
    """R1：第77〜141回の成立法の振り分け（scripts/build_old_laws_triage.py）。"""

    def test_every_enacted_law_has_three_labels(self):
        ids = [r["法令番号"] for r in read(ROOT / "data" / "acquired" / "bill-census-old" / "enacted_old.csv")]
        for name in ("labels-A.csv", "labels-B.csv", "labels-line2.csv", "triage.csv"):
            self.assertEqual([r["id"] for r in read(OLD / name)], ids, name)

    def test_only_two_agreeing_lines_are_adopted(self):
        # ADR 0007：A と B の種類・分野がそろい、どちらも保留でないときだけ一致。値は2系統の値そのもの
        for r in read(OLD / "triage.csv"):
            agreed = (r["A_種類"], r["A_分野"]) == (r["B_種類"], r["B_分野"]) and "保留" not in (r["A_種類"], r["A_分野"])
            self.assertEqual(r["結果"], "一致" if agreed else "保留", r["id"])
            self.assertEqual((r["種類"], r["分野"]), (r["A_種類"], r["A_分野"]) if agreed else ("", ""), r["id"])

    def test_triage_is_rebuilt_from_the_labels(self):
        import tempfile
        from unittest import mock
        from scripts import build_old_laws_triage as b
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for name in b.LINES.values():
                (out / name).write_bytes((OLD / name).read_bytes())
            with mock.patch.object(b, "OUT", out):
                b.build()
            self.assertEqual((out / "triage.csv").read_bytes(), (OLD / "triage.csv").read_bytes())

    def test_import_writes_nothing_when_a_later_line_is_incomplete(self):
        # A が完全でも B が欠けていれば、どのラベルも書き換えない（世代の違う A・B が混ざらない）
        import json
        import tempfile
        from unittest import mock
        from scripts import build_old_laws_triage as b
        ids = [r["法令番号"] for r in read(ROOT / "data" / "acquired" / "bill-census-old" / "enacted_old.csv")]
        full = [{"id": i, "kind": "k", "field": "f", "reason": ""} for i in ids]
        with tempfile.TemporaryDirectory() as tmp:
            out, result = Path(tmp) / "out", Path(tmp) / "result.json"
            result.write_text(json.dumps({"A": full, "B": full[:-1], "line2": full}), encoding="utf-8")
            with mock.patch.object(b, "OUT", out), self.assertRaises(SystemExit):
                b.import_result(result)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
