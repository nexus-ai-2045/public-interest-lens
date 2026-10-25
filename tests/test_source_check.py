import copy
import csv
import json
import re
import unittest

from scripts import build_public_ranking, source_check
from _data_gate import requires_data  # noqa: E402


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

    @requires_data("industry_va")
    def test_published_laws_match_primary_sources(self):
        rows, summary = source_check.check(self.ranking, self.ctx)
        self.assertEqual(summary["mismatch"], 0, [r for r in rows if r["結果"] == source_check.NG])
        self.assertEqual(summary["heldOut"], [])

    @requires_data("industry_va")
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
                # 複数の節を足す産業は丸めで1円ずれることがある（出典チェックと同じ許容幅）。
                for value, expected in zip((got["median"], got["low"], got["high"]), (int(x) for x in amount.groups())):
                    self.assertLessEqual(abs(value - expected), source_check.TOLERANCE_YEN, row["id"])
                checked += 1
        self.assertGreater(checked, 0)

    @requires_data("industry_va")
    def test_tampered_numbers_are_held_out(self):
        self.assertTrue(self.ranking["laws"])
        for field, value in [("amountMedianYen", 1000), ("title", "別の題名"), ("enforcedOn", "2000-01-01"), ("sources", ["https://example.com/x"])]:
            tampered = copy.deepcopy(self.ranking)
            law = tampered["laws"][0]
            law[field] = law[field] + value if isinstance(value, int) else value
            _, summary = source_check.check(tampered, self.ctx)
            self.assertEqual(summary["heldOut"], [law["id"]], field)

    @requires_data("industry_va")
    def test_held_law_moves_to_source_reason(self):
        law_id = self.ranking["laws"][0]["id"]
        payload = build_public_ranking.build(True, self.ranking["approval"]["approvedAt"], held_by_check={law_id})
        self.assertNotIn(law_id, [law["id"] for law in payload["laws"]])
        self.assertIn((build_public_ranking.OUTCOMES["source"], law_id), {(o["outcome"], o["id"]) for o in payload["others"]})
        self.assertEqual(payload["counts"]["published"], len(payload["laws"]))

    def test_revision_based_enforcement_without_clause_is_not_a_mismatch(self):
        # e-Gov の改正履歴から施行日を取った行は、附則の原文が無いことだけでは外さない。
        tampered = copy.deepcopy(self.ctx)
        row = tampered["enforcement"]["衆法-189-20"]
        self.assertEqual(row["施行期日の原文"], "")
        rows = source_check.check_law(next(l for l in self.ranking["laws"] if l["id"] == "衆法-189-20"), tampered)
        clause = next(r for r in rows if r["項目"] == "施行期日の原文")
        self.assertEqual(clause["結果"], source_check.NA)
        row["取得方法"] = "その他"
        rows = source_check.check_law(next(l for l in self.ranking["laws"] if l["id"] == "衆法-189-20"), tampered)
        self.assertEqual(next(r for r in rows if r["項目"] == "施行期日の原文")["結果"], source_check.NG)

    def test_refetched_raw_is_checked_against_latest_manifest_row(self):
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquired = root / "data" / "acquired"
            (acquired / "oecd").mkdir(parents=True)
            raw = root / ".local" / "raw.csv"
            raw.parent.mkdir()
            raw.write_bytes(b"new")
            old, new = hashlib.sha256(b"old").hexdigest(), hashlib.sha256(b"new").hexdigest()
            (acquired / "oecd" / "manifest.csv").write_text(
                "url,path,sha256\nhttps://x/a,.local/raw.csv," + old + "\nhttps://x/a,.local/raw.csv," + new + "\n",
                encoding="utf-8")
            by_url, present = source_check._manifest_hashes(acquired, root)
        self.assertEqual(present, 1)
        self.assertEqual(by_url["https://x/a"], [(raw, new)])

    def test_report_leaves_out_matching_raw_hashes(self):
        import tempfile
        from pathlib import Path
        ok, ng = source_check.OK, source_check.NG
        rows = [
            {"id": "閣法-1-1", "項目": "施行日", "公開値": "a", "一次資料の値": "a", "結果": ok, "備考": ""},
            {"id": "閣法-1-1", "項目": "原本のハッシュ", "公開値": "x", "一次資料の値": "x", "結果": ok, "備考": ""},
            {"id": "閣法-1-2", "項目": "原本のハッシュ", "公開値": "x", "一次資料の値": "y", "結果": ng, "備考": ""},
        ]
        summary = {"checkedLaws": 2, "items": 3, "match": 2, "mismatch": 1, "notApplicable": 0, "heldOut": ["閣法-1-2"], "rawFilesPresent": 2}
        with tempfile.TemporaryDirectory() as tmp:
            source_check.write_report(rows, summary, Path(tmp))
            stable = json.loads((Path(tmp) / "summary.json").read_text(encoding="utf-8"))
            written = list(csv.DictReader((Path(tmp) / "check.csv").open(encoding="utf-8")))
        # 原本が手元にあるかどうかで公開の件数が変わらない。食い違った原本は残す
        self.assertEqual((stable["items"], stable["match"], stable["mismatch"]), (2, 1, 1))
        self.assertNotIn("rawFilesPresent", stable)
        self.assertEqual([r["id"] for r in written], ["閣法-1-1", "閣法-1-2"])

    def test_members_page_matches_ranking(self):
        members = json.loads(source_check.MEMBERS.read_text(encoding="utf-8"))
        rows = source_check.check_members(members, self.ranking)
        self.assertEqual([r for r in rows if r["結果"] == source_check.NG], [])
        tampered = copy.deepcopy(members)
        listed = {l["id"] for l in self.ranking["laws"]}
        law = next(l for l in tampered["laws"] if l["id"] in listed and l["observationLaws"] == 1)
        law["amount"]["median"] += 1
        tampered["members"][0]["laws"][0]["evidence"][0]["url"] = "https://example.com/"
        bad = {r["項目"] for r in source_check.check_members(tampered, self.ranking) if r["結果"] == source_check.NG}
        # 額を変えると、配分の合計も額と合わなくなる。
        self.assertEqual(bad, {"議員ページの額", "証拠URL", "配分の合計"})
        # 同じ観測を共有する本数を書き換えると（二重に数える配り方）、本数も配分の合計も合わない。
        shared = copy.deepcopy(members)
        law = next(l for l in shared["laws"] if l["id"] in listed and l["observationLaws"] > 1)
        law["observationLaws"] = 1
        bad = {r["項目"] for r in source_check.check_members(shared, self.ranking) if r["結果"] == source_check.NG}
        self.assertEqual(bad, {"同じ観測を共有する本数", "配分の合計"})


if __name__ == "__main__":
    unittest.main()
