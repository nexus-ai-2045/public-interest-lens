"""全法律の一覧（scripts/build_laws_catalog.py）の読み替えが、公開ランキングと台帳の値と一致するか。"""

import csv
import json
import unittest

from scripts import build_laws_catalog as catalog
from _data_gate import requires_data  # noqa: E402


class BuildLawsCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = catalog.build()
        cls.laws = {item["id"]: item for item in cls.payload["laws"]}
        cls.ranking = json.loads(catalog.INPUTS["ranking"].read_text(encoding="utf-8"))

    def test_all_enacted_laws_once(self):
        with catalog.INPUTS["enacted"].open(encoding="utf-8", newline="") as handle:
            enacted = list(csv.DictReader(handle))
        self.assertEqual(len(self.laws), len(enacted))
        self.assertEqual(len(self.payload["laws"]), len(enacted))

    def test_era_date(self):
        self.assertEqual(catalog.era_date("平成10年 3月25日"), "1998-03-25")
        self.assertEqual(catalog.era_date("令和元年 5月 1日"), "2019-05-01")
        self.assertIsNone(catalog.era_date(""))

    def test_amounts_match_public_ranking(self):
        amounted = {law_id for law_id, item in self.laws.items() if item["amount"]}
        self.assertEqual(amounted, {law["id"] for law in self.ranking["laws"]})
        for law in self.ranking["laws"]:
            item = self.laws[law["id"]]
            self.assertEqual(item["amount"], {"median": law["amountMedianYen"], "low": law["amountLowYen"], "high": law["amountHighYen"]})
            self.assertEqual(item["side"], law["side"])
            self.assertIn(catalog.CERTAINTY[law["certainty"]], item["marks"])

    def test_laws_without_amount_carry_the_public_reason(self):
        for other in self.ranking["others"]:
            self.assertTrue(self.laws[other["id"]]["summary"].startswith(other["outcome"]))

    def test_every_row_has_reason_and_source(self):
        for item in self.payload["laws"]:
            self.assertTrue(item["summary"], item["id"])
            self.assertTrue(item["sources"], item["id"])

    def test_every_law_has_an_overview_with_passage_and_result(self):
        for item in self.payload["laws"]:
            view = item["overview"]
            self.assertTrue(view["passage"], item["id"])
            self.assertTrue(view["result"], item["id"])
            for key in ("what", "aim", "concern"):
                if key in view and view[key].get("withheld") in ("other", "unchecked"):
                    # この法律の発言ではなかったものは、URL を持たない
                    self.assertNotIn("url", view[key], item["id"])
                elif key in view:
                    self.assertTrue(view[key]["url"].startswith("https://kokkai.ndl.go.jp/"), item["id"])
            # 狙いは要約があるときだけ。何をする・反対側の心配は、要約できなくても見つかった発言を示す
            if "aim" in view:
                self.assertTrue(view["aim"]["text"], item["id"])

    def test_passage_orders_houses_by_date(self):
        census = {"種別": "衆法", "提出者": "山田 太郎君外四名", "議決結果_衆": "可決", "議決日_衆": "平成10年 5月12日",
                  "議決結果_参": "修正", "議決日_参": "平成10年 3月20日", "公布日": "平成10年 5月20日"}
        self.assertEqual(catalog.passage(census), "山田太郎ほか四名が提出（衆議院の議員立法）。参院で修正して可決（1998-03-20）→衆院で可決（1998-05-12）→1998-05-20に公布")

    def test_overview_drops_summary_without_source(self):
        census = {"種別": "閣法", "提出者": "内閣", "公布日": ""}
        view = catalog.overview(census, {"説明のURL": "", "反対のURL": ""}, {"何をする": "推測の文", "狙い": "", "反対側の心配": ""}, "結果")
        self.assertNotIn("what", view)

    def test_overview_keeps_source_when_summary_was_withheld(self):
        # 発言はあるが、どの法案の話か決められず要約しなかったときは「見つからない」にしない
        census = {"種別": "閣法", "提出者": "内閣", "公布日": ""}
        speech = {"説明のURL": "", "反対のURL": "https://kokkai.ndl.go.jp/txt/x/1", "反対の発言者": "議員", "反対の日付": "1999-05-13"}
        view = catalog.overview(census, speech, {"何をする": "", "狙い": "", "反対側の心配": ""}, "結果")
        self.assertEqual(view["concern"]["text"], "")
        self.assertEqual(view["concern"]["url"], "https://kokkai.ndl.go.jp/txt/x/1")
        self.assertEqual(view["concern"]["withheld"], "unread")
        view = catalog.overview(census, speech, {"何をする": "", "狙い": "", "反対側の心配": ""}, "結果", frozenset({"反対のURL"}))
        self.assertEqual(view["concern"]["withheld"], "shared")

    def test_speech_without_an_overview_row_is_not_shown(self):
        # 発言を取った後で、要約と照合がまだの法律（概要の台帳に行が無い）は、見つかった発言として示さない
        census = {"種別": "閣法", "提出者": "内閣", "公布日": ""}
        speech = {"説明のURL": "https://kokkai.ndl.go.jp/txt/x/2", "説明の発言者": "大臣", "説明の日付": "1999-05-13",
                  "反対のURL": "https://kokkai.ndl.go.jp/txt/x/1", "反対の発言者": "議員", "反対の日付": "1999-05-13"}
        for ambiguous in (frozenset(), frozenset({"説明のURL", "反対のURL"})):
            view = catalog.overview(census, speech, None, "結果", ambiguous)
            self.assertEqual(view["what"], {"text": "", "withheld": "unchecked"})
            self.assertEqual(view["concern"], {"text": "", "withheld": "unchecked"})

    def test_speech_facts_are_recorded_as_an_input(self):
        self.assertIn("speechFacts", catalog.INPUTS)
        self.assertIn("speechFacts", self.payload["inputs"])
        self.assertNotIn("speeches", catalog.INPUTS)
        self.assertNotIn("segments", catalog.INPUTS)

    def test_withheld_reason_matches_shared_speeches(self):
        # 発言が1本の法案だけのものなら、要約が空でも「まとめた説明」とは言わない（衆法-139-18 など）
        item = next(law for law in self.payload["laws"] if law["id"] == "衆法-139-18")
        what = item["overview"].get("what")
        if what and not what["text"]:
            self.assertEqual(what["withheld"], "unread")

    def test_shared_speech_is_withheld_as_shared_only_when_the_facts_say_it_cannot_be_told_apart(self):
        # 共有の発言を「区別できた（unread）」と言えるのは、speech-facts.csv の「区別できない」に入っていないときだけ
        facts = {row["id"]: row for row in csv.DictReader(catalog.INPUTS["speechFacts"].open(encoding="utf-8"))}
        for law in self.payload["laws"]:
            kinds = facts.get(law["id"], {}).get("区別できない", "").split("・")
            for key, kind in (("what", "説明"), ("concern", "反対")):
                withheld = ((law.get("overview") or {}).get(key) or {}).get("withheld")
                if withheld == "shared":
                    self.assertIn(kind, kinds, law["id"])
                if withheld == "unread":
                    self.assertNotIn(kind, kinds, law["id"])

    def test_debate_about_another_topic_is_marked_as_such(self):
        # 閣法-174-6（子ども手当）の反対討論として拾った発言は予算への討論なので、この法律の反対討論とは示さない
        item = next(law for law in self.payload["laws"] if law["id"] == "閣法-174-6")
        concern = item["overview"].get("concern")
        self.assertEqual(concern["text"], "")
        self.assertEqual(concern["withheld"], "other")
        # 予算への討論の URL を、この法律の出典（国会会議録（反対討論））として出さない
        self.assertNotIn("url", concern)
        self.assertNotIn("国会会議録（反対討論）", [source["label"] for source in item.get("sources", [])])

    def test_supporting_speech_is_not_shown_as_an_opposition_debate(self):
        # 閣法-153-5 の候補の討論は法案に賛成し修正案にだけ反対するもの。要約が空でも「反対討論は見つかった」と示さない
        item = next(law for law in self.payload["laws"] if law["id"] == "閣法-153-5")
        self.assertEqual(item["overview"]["concern"], {"text": "", "withheld": "other"})

    def test_bundle_rule(self):
        self.assertEqual(catalog.bundle_of("閣法-142-1"), "142")
        self.assertEqual(catalog.bundle_of("fsa-financial-revival-2002"), "policy")

    def test_representative_is_first_id_of_each_observation(self):
        items = [
            {"id": "閣法-1-9", "amount": {"median": 5}, "group": "製造業-1", "window": "2001〜2010年"},
            {"id": "衆法-1-2", "amount": {"median": 5}, "group": "製造業-1", "window": "2001〜2010年"},
            {"id": "閣法-1-3", "amount": {"median": 5}, "group": "製造業-1", "window": "2002〜2011年"},
            {"id": "閣法-1-4", "amount": None},
        ]
        self.assertEqual(catalog.mark_observations(items), 2)
        self.assertEqual(items[0]["observation"], {"key": "製造業-1／2001〜2010年", "size": 2, "representative": False, "representativeId": "衆法-1-2"})
        self.assertEqual(items[1]["observation"], {"key": "製造業-1／2001〜2010年", "size": 2, "representative": True})
        self.assertEqual(items[2]["observation"]["size"], 1)
        self.assertNotIn("observation", items[3])

    def test_outlier_mark_only_when_amount_exceeds_previous_year_value_added(self):
        value_added = {2000: 500e12, 2001: 510e12}
        items = [
            {"id": "a", "amount": {"median": 600e12}, "window": "2001〜2010年", "marks": []},
            {"id": "b", "amount": {"median": 400e12}, "window": "2001〜2010年", "marks": []},
            {"id": "c", "amount": {"median": 900e12}, "window": "1990〜1999年", "marks": []},
            {"id": "d", "amount": None, "window": "2001〜2010年", "marks": []},
        ]
        self.assertEqual(catalog.mark_outliers(items, value_added), 1)
        self.assertEqual(items[0]["marks"], [catalog.OUTLIER_MARK])
        self.assertEqual(items[0]["scale"], 1.2)
        self.assertTrue(all(not item["marks"] and "scale" not in item for item in items[1:]))

    @requires_data("industry_va")
    def test_japan_value_added_uses_nominal_all_industry_only(self):
        value_added = catalog.japan_value_added()
        self.assertIn(1999, value_added)
        self.assertGreater(value_added[2000], 4e14)

    def test_published_catalog_marks_match_rules(self):
        shared = {}
        for item in self.payload["laws"]:
            if item.get("observation"):
                shared.setdefault(item["observation"]["key"], []).append(item)
        for key, group in shared.items():
            self.assertEqual([item["observation"]["representative"] for item in group].count(True), 1, key)
            # 代表は確かさの高い順（高・中・低・参考）、同じなら id の小さい法律。
            first = min(group, key=lambda item: (catalog.CERTAINTY_ORDER.get(item.get("certainty") or "", 9), item["id"]))["id"]
            for item in group:
                self.assertEqual(item["observation"]["size"], len(group))
                self.assertEqual(item["observation"]["representative"], item["id"] == first)
        va = catalog.japan_value_added()
        for item in self.payload["laws"]:
            year = catalog.start_year(item.get("window", ""))
            over = bool(item["amount"] and year and va.get(year - 1) and item["amount"]["median"] > va[year - 1])
            self.assertEqual(catalog.OUTLIER_MARK in item["marks"], over, item["id"])


if __name__ == "__main__":
    unittest.main()
