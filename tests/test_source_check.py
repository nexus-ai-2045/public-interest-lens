import copy
import csv
import json
import re
import unittest

from scripts import build_public_ranking, source_check


class SourceCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = source_check.context()
        cls.ranking = json.loads(build_public_ranking.OUTPUT.read_text(encoding="utf-8"))

    def test_wareki(self):
        self.assertEqual(source_check.wareki_to_iso("平成26年11月12日"), "2014-11-12")
        self.assertEqual(source_check.wareki_to_iso("令和元年 5月 1日"), "2019-05-01")
        self.assertEqual(source_check.wareki_to_iso("昭和64年1月7日"), "1989-01-07")
        self.assertIsNone(source_check.wareki_to_iso("不明"))

    def test_primary_hosts(self):
        self.assertTrue(source_check.is_primary("https://laws.e-gov.go.jp/law/426AC1000000104"))
        self.assertTrue(source_check.is_primary("https://sdmx.oecd.org/public/rest/data"))
        self.assertFalse(source_check.is_primary("https://example.com/go.jp"))
        self.assertFalse(source_check.is_primary("http://www.shugiin.go.jp/"))

    def test_published_laws_match_primary_sources(self):
        rows, summary = source_check.check(self.ranking, self.ctx)
        self.assertEqual(summary["mismatch"], 0, [r for r in rows if r["結果"] == source_check.NG])
        self.assertEqual(summary["heldOut"], [])

    def test_recompute_reproduces_every_oecd_loss_row(self):
        # 判定ルール（TypeScript）とは別に、元の表だけから同じ額が出ることを確かめる。
        enforcement = self.ctx["enforcement"]
        checked = 0
        with (source_check.DERIVED / "loss-v1-triage-v2" / "loss.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                industry = re.search(r"OECD 表6 JPN [^（]*（([A-Z_]+)）", row["計算式の要素"])
                amount = re.search(r"中央値=(-?\d+);第1四分位=(-?\d+);第3四分位=(-?\d+)", row["損失または便益の額"])
                countries = re.search(r"比較国：\d+か国（([A-Z・]+)）", row["計算式の要素"])
                if not (industry and amount and countries):
                    continue
                got = source_check.recompute(self.ctx["oecd"], industry.group(1), enforcement[row["id"]]["施行日"], 9999, countries.group(1).split("・"))
                self.assertEqual((got["median"], got["low"], got["high"]), tuple(int(x) for x in amount.groups()), row["id"])
                checked += 1
        self.assertGreater(checked, 0)

    def test_tampered_numbers_are_held_out(self):
        self.assertTrue(self.ranking["laws"])
        for field, value in [("amountMedianYen", 1000), ("title", "別の題名"), ("enforcedOn", "2000-01-01"), ("sources", ["https://example.com/x"])]:
            tampered = copy.deepcopy(self.ranking)
            law = tampered["laws"][0]
            law[field] = law[field] + value if isinstance(value, int) else value
            _, summary = source_check.check(tampered, self.ctx)
            self.assertEqual(summary["heldOut"], [law["id"]], field)

    def test_held_law_moves_to_source_reason(self):
        law_id = self.ranking["laws"][0]["id"]
        approved = self.ranking["approval"]["approvedLaws"]
        payload = build_public_ranking.build(approved, self.ranking["approval"]["approvedAt"], held_by_check={law_id})
        self.assertNotIn(law_id, [law["id"] for law in payload["laws"]])
        self.assertNotIn(law_id, payload["approval"]["approvedLaws"])
        self.assertIn(("SOURCE", law_id), {(h["reasonCode"], h["id"]) for h in payload["held"]})
        self.assertEqual(payload["counts"]["published"], len(payload["laws"]))


if __name__ == "__main__":
    unittest.main()
