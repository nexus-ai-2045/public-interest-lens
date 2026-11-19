"""一次資料で直したサイトの値（primary-source-corrections-v1）の検査。

表の値は読み直しの記録（2系統の一致、または裁定）と同じでなければならない。手で別の値を書いた行があれば落ちる。
直した値が台帳と全法律の結果に届いていることも確かめる。
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import primary_source_corrections as corrections

ROOT = Path(__file__).resolve().parents[1]
RV = ROOT / "data" / "derived" / "evaluation-ledger-v1" / "reverification-v1"
SITE_WORD = {"経済に効く": corrections.ECON, "制度のみ": corrections.INSTITUTIONAL}


def by_id(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


class CorrectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corr = corrections.load()
        cls.a = {x["id"]: x for x in json.loads((RV / "lineA.json").read_text(encoding="utf-8"))}
        cls.b = {x["id"]: x for x in json.loads((RV / "lineB.json").read_text(encoding="utf-8"))}
        cls.rulings = json.loads((RV / "rulings.json").read_text(encoding="utf-8"))

    def test_every_value_comes_from_the_recorded_reading(self):
        self.assertTrue(self.corr)
        for i, items in self.corr.items():
            for item, row in items.items():
                ruling = self.rulings.get(i, {}).get(item)
                if ruling:
                    want = ruling["値"]
                else:
                    self.assertEqual(self.a[i][item], self.b[i][item], f"{i} {item}：2系統が割れていて裁定も無い")
                    want = self.a[i][item]
                self.assertEqual(row["直した値"], SITE_WORD.get(want, want), f"{i} {item}")
                for k in ("理由", "引用", "出典URL", "判定者", "指示文", "記録"):
                    self.assertTrue(row[k].strip(), f"{i} {item} {k}")

    def test_corrected_values_reach_the_outcomes_and_the_ledger(self):
        outcomes = by_id(ROOT / "data" / "derived" / "all-laws-v1" / "outcomes.csv")
        ledger = by_id(ROOT / "data" / "derived" / "evaluation-ledger-v1" / "ledger.csv")
        for i, items in self.corr.items():
            if "類型" in items:
                self.assertEqual(outcomes[i]["種類"], items["類型"]["直した値"], i)
                self.assertEqual(ledger[i]["類型"], items["類型"]["直した値"], i)
            if "経済に効くか" in items:
                v = items["経済に効くか"]["直した値"]
                self.assertTrue(ledger[i]["経済に効くか"].startswith(v), i)
                if v == corrections.INSTITUTIONAL:
                    self.assertEqual((outcomes[i]["結果"], ledger[i]["分類"]), ("評価対象外", "評価対象外"), i)
                else:
                    self.assertNotIn(outcomes[i]["結果"], ("評価対象外", "効果なし（定例）"), i)

    def test_undefined_item_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.csv"
            bad.write_text("id,項目,直した値\nx,分野,金融\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                corrections.load(bad)


if __name__ == "__main__":
    unittest.main()
