import json
import unittest

from scripts.build_public_ranking import APPROVAL_NOTE, OUTCOMES, OUTPUT, build
from _data_gate import requires_data  # noqa: E402


class EnforcementDateSourceTest(unittest.TestCase):
    def test_the_house_enacted_law_page_stays_with_the_published_date(self):
        from scripts.build_laws_catalog import source_links
        from scripts.build_public_ranking import _sources

        house = "https://www.shugiin.go.jp/internet/itdb_housei.nsf/html/housei/h142029.htm"
        urls = _sources("閣法-142-20", {}, {"閣法-142-20": {"出典URL": house}})
        self.assertEqual(urls, [house])
        self.assertEqual(source_links(urls), [{"label": "衆議院 制定法律", "url": house}])
        egov = _sources("x", {}, {"x": {"出典URL": "https://laws.e-gov.go.jp/api/2/law_revisions/410AC0000000029"}})
        self.assertEqual(egov, ["https://laws.e-gov.go.jp/law/410AC0000000029"])


@requires_data("industry_va")
class PublicRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build(True, "2026-10-17", held_by_check=set())

    def test_committed_file_matches_inputs(self):
        committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
        approval = committed["approval"]
        self.assertEqual(committed, build(approval["scope"] == "all-laws", approval["approvedAt"] or ""))

    def test_blanket_approval_is_recorded(self):
        approval = json.loads(OUTPUT.read_text(encoding="utf-8"))["approval"]
        self.assertEqual(approval, {"approvedAt": "2026-10-17", "scope": "all-laws", "note": APPROVAL_NOTE})
        self.assertEqual(APPROVAL_NOTE, "法律単位の結果を全件公開（2026-10-17 ユーザー承認、議員の実名は別承認）")
        with self.assertRaises(ValueError):
            build(True, "")

    def test_unapproved_build_has_no_amounts(self):
        payload = build(False, "")
        self.assertEqual(payload["laws"], [])
        self.assertEqual(payload["approval"], {"approvedAt": None, "scope": None, "note": None})
        self.assertEqual(payload["counts"]["published"], 0)
        self.assertEqual(payload["counts"]["others"], payload["counts"]["enacted"])
        self.assertIn(OUTCOMES["pending"], {item["outcome"] for item in payload["others"]})
        for item in payload["others"]:
            self.assertEqual(set(item), {"id", "title", "outcome", "reason"})

    def test_stage1_without_a_loss_amount_is_held(self):
        by_id = {item["id"]: item for item in build(False, "")["others"]}
        # 閣法-159-73・164-7・164-35・183-21 は、証拠のない「一致」を採用しなくなった（eval_loop.line_agreement_proven）ため、
        # 段階の判定に進まず振り分けの保留に戻る。
        for law_id in ("閣法-159-73", "閣法-164-7", "閣法-164-35", "閣法-183-21"):
            self.assertEqual(by_id[law_id]["outcome"], OUTCOMES["triage_hold"], law_id)
            self.assertTrue(by_id[law_id]["reason"].strip(), law_id)

    def test_every_enacted_law_appears_exactly_once(self):
        payload = self.payload
        ids = [law["id"] for law in payload["laws"]] + [item["id"] for item in payload["others"]]
        self.assertEqual(len(ids), payload["counts"]["enacted"])
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(payload["counts"]["published"] + payload["counts"]["others"], payload["counts"]["enacted"])
        for item in payload["others"]:
            self.assertTrue(item["reason"].strip())
            self.assertIn(item["outcome"], OUTCOMES.values())
            self.assertNotRegex(json.dumps(item, ensure_ascii=False), r"Yen|中央値|四分位")

    def test_laws_carry_range_certainty_and_sources(self):
        payload = self.payload
        self.assertEqual(payload["counts"]["confirmed"] + payload["counts"]["reference"], len(payload["laws"]))
        for law in payload["laws"]:
            self.assertIn(law["certainty"], ("高", "中", "低", "参考"))
            self.assertLessEqual(law["amountLowYen"], law["amountMedianYen"])
            self.assertLessEqual(law["amountMedianYen"], law["amountHighYen"])
            # 中央値は側の向きに正。四分位の幅は確かさによらず0をまたいでよい（そのまま見せる）。
            self.assertGreater(law["amountMedianYen"], 0)
            self.assertTrue(law["sources"])
            self.assertIn(law["side"], ("loss", "benefit"))
        self.assertNotIn("people", payload)

    def test_reference_amounts_come_after_confirmed_ones(self):
        flags = [law["certainty"] == "参考" for law in self.payload["laws"]]
        self.assertEqual(flags, sorted(flags))
        by_id = {law["id"]: law for law in self.payload["laws"]}
        self.assertEqual(by_id["衆法-186-35"]["certainty"], "高")
        self.assertEqual(by_id["閣法-193-37"]["certainty"], "参考")

    def test_shared_observation_and_oversized_notes(self):
        from collections import Counter
        from scripts.build_public_ranking import japan_value_added_max
        laws = self.payload["laws"]
        shared = Counter((law["group"], law["window"], law["amountMedianYen"]) for law in laws)
        ceiling = japan_value_added_max()
        for law in laws:
            n = shared[(law["group"], law["window"], law["amountMedianYen"])]
            self.assertEqual(any("1つの観測を共有" in note for note in law["notes"]), n > 1, law["id"])
            self.assertEqual(any("付加価値1年分を超える" in note for note in law["notes"]), law["amountMedianYen"] > ceiling, law["id"])

    def test_covid_overlap_and_unmeasured_notes(self):
        by_id = {law["id"]: law for law in self.payload["laws"]}
        for law_id in ("衆法-189-20", "閣法-193-59", "閣法-196-2", "閣法-196-4"):
            self.assertIn("コロナ期と重なる", by_id[law_id]["notes"])
        self.assertIn("便益側の一部が未測定", by_id["閣法-189-27"]["notes"])
        self.assertFalse({"コロナ期と重なる", "便益側の一部が未測定"} & set(by_id["衆法-186-35"]["notes"]))

    def test_source_held_law_moves_to_others(self):
        payload = build(True, "2026-10-17", held_by_check={"衆法-186-35"})
        self.assertNotIn("衆法-186-35", {law["id"] for law in payload["laws"]})
        held = next(item for item in payload["others"] if item["id"] == "衆法-186-35")
        self.assertEqual(held["outcome"], OUTCOMES["source"])


if __name__ == "__main__":
    unittest.main()
