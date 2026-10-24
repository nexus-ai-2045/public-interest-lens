"""scripts/fetch_target_series.py の読み取り（各省の表・PDF の文字）と、数値目標と系列の結び付け（判定）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import fetch_target_series as ts  # noqa: E402
from scripts.fetch_fiscal_more import read_csv  # noqa: E402

URL = "https://www.esri.cao.go.jp/x.csv"


def series(sid: str, values: dict[int, float]) -> dict:
    return {sid: {y: {"系列ID": sid, "系列": sid, "年": str(y), "値": str(v), "出典URL": URL} for y, v in values.items()}}


def target(did: str, indicator: str, value: float, unit: str, year: int | None = None, kind: str = "") -> dict:
    return {"決定ID": did, "指標": indicator, "目標値": str(value), "単位": unit, "目標年": str(year or ""), "年の別": kind}


class Parsers(unittest.TestCase):
    def test_yen(self):
        self.assertEqual(ts.yen("1兆7,005億円"), 1.7005e12)
        self.assertEqual(ts.yen("9,860億円"), 9.86e11)
        self.assertIsNone(ts.yen("5.3兆円"))

    def test_sna_csv_reads_fiscal_and_calendar_years(self):
        text = '名目年度,,\n,国内総生産(支出側),\n1994/4-3.,"522,040.3 ",x\n1995/4-3.,"534,706.2 ",x\n,,\n'
        rows = ts.parse_sna_csv(text, "s", "GDP", "円", "年度", URL, "")
        self.assertEqual([(r["年"], r["値"]) for r in rows], [(1994, 522040.3e9), (1995, 534706.2e9)])
        rows = ts.parse_sna_csv('1995/4-3.,,\n1996/4-3.,3.0 ,\n', "g", "率", "%", "年度", URL, "")
        self.assertEqual([(r["年"], r["値"]) for r in rows], [(1996, 3.0)])  # 空の年（最初の年の前年度比）は飛ばす

    def test_pb_keeps_only_actual_years(self):
        rows = [["【国・地方の財政の姿】"], ["年　　度", None, None, 2023, 2024, 2025], ["基礎的財政収支", None, None, -13.2, -11.3, -0.2],
                [None, "（対名目GDP比）", None, -2.1, -1.8, "▲0.0"]]
        out = ts.parse_pb(rows, URL, 2026, "試算")
        self.assertEqual(sorted({r["年"] for r in out}), [2023, 2024])  # 2026年の版は2024年度まで実績、2025年度は推計
        self.assertEqual([r["値"] for r in out if r["系列ID"].endswith("兆円")], [-13.2e12, -11.3e12])

    def test_wage_reads_weighted_average(self):
        rows = [["年度", "平成14年度", None, "令和5年度", None], ["都道府県名", "改定額(円)", "発効年月日", "改定額(円)", "発効年月日"],
                ["北海道", 637, 1, 960, 1], ["全国加重平均額", 663, "-", 1004, "-"]]
        self.assertEqual([(r["年"], r["値"]) for r in ts.parse_wage(rows, URL)], [(2002, 663), (2023, 1004)])

    def test_visitors_reads_year_and_count(self):
        text = "   2019      平成31 / 令和元 年                 31,882,049              2.2                20,080,669\n" \
               "   2020         令和 2 年                     4,115,828           △87.1                  3,174,219\n"
        self.assertEqual([(r["年"], r["値"]) for r in ts.parse_visitors(text, URL)], [(2019, 31882049.0), (2020, 4115828.0)])

    def test_spending_headline(self):
        text = "【インバウンド消費動向調査】2025年暦年の調査結果(確報)の概要\n~訪日外国人旅行消費額(確報)は9.5兆円と過去最高~\n●訪日外国人旅行消費額(確報)は9兆4,549億円(2024年比16.4%増)"
        self.assertEqual(ts.parse_spending(text, 2025, URL)["値"], 9.4549e12)
        self.assertIsNone(ts.parse_spending(text, 2024, URL))  # 年が本文に無い PDF は採らない
        page = '<p>2025年</p><a href="/kankocho/content/002020046.pdf">暦年</a><p>2020年</p><a href="/kankocho/content/002026218.pdf">年間試算結果</a>'
        self.assertEqual(ts.spending_pages(page, "https://www.mlit.go.jp/kankocho/x.html"),
                         [(2025, "https://www.mlit.go.jp/kankocho/content/002020046.pdf"), (2020, "https://www.mlit.go.jp/kankocho/content/002026218.pdf")])

    def test_export_headlines(self):
        self.assertEqual(ts.parse_export("2025年１-12月の輸出額は、対前年比+12.8％の1兆7,005億円となりました。", 2025, URL)["値"], 1.7005e12)
        self.assertEqual(ts.parse_export("修正 金額 前年差 前年比 １－12月累計 9,860億円 － － １－12月累計 9,217億円", 2020, URL)["値"], 9.86e11)
        self.assertEqual(ts.parse_export(" 2019年の輸出額は9,121億円。前年同期比＋0.6％。", 2019, URL)["値"], 9.121e11)
        page = ('<a href="./attach/pdf/zisseki-280.pdf">令和7年（2025年）農林水産物・食品の輸出額(PDF)</a>'
                '<a href="./attach/pdf/zisseki-307.pdf">「令和7年（2025年）農林水産物・食品の輸出実績（国・地域別）」</a>'
                '<a href="./attach/pdf/zisseki-312.pdf">令和8年（2026年）8月の農林水産物・食品の輸出実績</a>')
        self.assertEqual(ts.export_pages(page, "https://www.maff.go.jp/j/x/zisseki.html"), [(2025, "https://www.maff.go.jp/j/x/attach/pdf/zisseki-280.pdf")])

    def test_lodging_sums_regions(self):
        prefs = ["01北海道", "02青森県", "03岩手県", "04宮城県", "05秋田県", "06山形県", "07福島県", "08茨城県", "09栃木県", "10群馬県", "11埼玉県", "12千葉県",
                 "13東京都", "14神奈川県", "15新潟県", "16富山県", "17石川県", "18福井県", "19山梨県", "20長野県", "21岐阜県", "22静岡県", "23愛知県", "24三重県",
                 "25滋賀県", "26京都府", "27大阪府", "28兵庫県", "29奈良県", "30和歌山県", "31鳥取県", "32島根県", "33岡山県", "34広島県", "35山口県", "36徳島県",
                 "37香川県", "38愛媛県", "39高知県", "40福岡県", "41佐賀県", "42長崎県", "43熊本県", "44大分県", "45宮崎県", "46鹿児島県", "47沖縄県"]
        rows = [["表"], [None, "令和6年", "令和7年", "令和5年"], ["全　国", 470, 470, 470]] + [[p, 10, 10, 10] for p in prefs]
        out = {(r["系列ID"].split(":")[-1], r["年"]): r["値"] for r in ts.parse_lodging(rows, URL)}
        self.assertEqual(out[("地方部", 2025)], 470 - 80)  # 三大都市圏8都府県を引く
        self.assertEqual(out[("東北6県", 2025)], 60)

    def test_iip_reads_liability_direct_investment(self):
        rows = [["本邦対外資産負債残高の推移"], ["", "", "資産残高", "", "", "負債残高", ""], ["", "", "Total assets", "", "", "Total liabilities", ""],
                ["", "", "", "直接投資", "証券投資", "", "直接投資"], ["", "", "", "Direct", "Portfolio", "", "Direct"],
                ["令和7年末", "End of 2025", 1, 2, 3, 4, 58562.0]]
        self.assertEqual([(r["年"], r["値"]) for r in ts.parse_iip(rows, URL)], [(2025, 58562e9)])

    def test_rd_and_ghg(self):
        payload = {"GET_STATS": {"STATISTICAL_DATA": {"DATA_INF": {"DATA_OBJ": [{"VALUE": {"@time": "2024FY00", "$": "23790000"}}]}}}}
        self.assertEqual([(r["年"], r["値"]) for r in ts.parse_rd(payload, URL)], [(2024, 23.79e12)])
        pad = [None] * 26
        rows = [pad + [1990, 2013, 2024], ["温室効果ガス"] + pad[1:] + [None, None, None], ["計"] + pad[1:] + [1270.0, 1393.5, 1046.4],
                ["■排出・吸収量"] + pad[1:], ["排出・吸収量（計）"] + pad[1:] + [None, None, 994.1]]
        out = {(r["系列ID"].split(":")[-1], r["年"]): r["値"] for r in ts.parse_ghg(rows, URL)}
        self.assertEqual(out[("総排出量", 2013)], 1393.5e6)
        self.assertEqual(out[("排出・吸収量", 2024)], 994.1e6)
        self.assertNotIn(("排出・吸収量", 2013), out)


class Database(unittest.TestCase):
    def test_year_ranges(self):
        from scripts.build_database import year_ranges

        self.assertEqual(year_ranges([2025, 2019, 2023, 2024]), "2019・2023〜2025年")
        self.assertEqual(year_ranges([2020]), "2020年")


class Judge(unittest.TestCase):
    def test_target_year_reached_or_not(self):
        table = series("jnto:訪日外客数", {2019: 31882049, 2020: 4115828, 2025: 42683301})
        r = ts.judge(target("国策-honebuto-2018", "訪日外国人旅行者数", 4000, "万人", 2020, "年"), table)
        self.assertEqual((r["判定"], r["達成の値"], r["達成の年"]), ("未達", 411.5828, 2020))
        r = ts.judge(target("国策-honebuto-2019", "訪日外国人旅行者数(2030年)", 6000, "万人", 2030, "年"), table)
        self.assertEqual((r["判定"], r["達成の年"]), ("期限前（未到達）", 2025))

    def test_surplus_is_shown_in_cho_yen(self):
        table = series("pb-cao:国・地方:兆円", {2020: -50.5e12})
        r = ts.judge(target("国策-honebuto-2015", "国・地方の基礎的財政収支(PB)", 0, "黒字化", 2020, "年度"), table)
        self.assertEqual((r["判定"], r["達成の値"]), ("未達", -50.5))

    def test_no_year_counts_only_after_the_decision(self):
        table = series("minwage:全国加重平均", {2015: 798, 2016: 823, 2023: 1004})
        r = ts.judge(target("国策-honebuto-2016", "最低賃金(全国加重平均)", 1000, "円"), table)
        self.assertEqual((r["判定"], r["達成の年"]), ("期限なし（到達）", 2023))
        table = series("minwage:全国加重平均", {2015: 1000, 2016: 990})
        self.assertEqual(ts.judge(target("国策-honebuto-2016", "最低賃金(全国加重平均)", 1000, "円"), table)["判定"], "期限なし（未到達）")

    def test_finished_year_without_actuals_is_not_before_the_deadline(self):
        table = series("pb-cao:国・地方:兆円", {2024: -11.3e12})
        r = ts.judge(target("国策-honebuto-2019", "国・地方の基礎的財政収支(PB)", 0, "黒字化", 2025, "年度"), table)
        self.assertEqual(r["判定"], "値なし（期限後・実績待ち）")  # 2025年度は終わったが実績がまだ無い（2026-10 時点）
        from datetime import date
        self.assertFalse(ts.ended(2025, "年度", date(2026, 3, 31)))
        self.assertTrue(ts.ended(2025, "年", date(2026, 1, 1)))

    def test_reach_in_the_decision_year_counts(self):
        table = series("kanko:訪日外国人旅行消費額", {2022: 0.9e12, 2023: 5.3065e12, 2024: 8.1e12})
        r = ts.judge(target("国策-honebuto-2023", "訪日外国人旅行消費額", 5, "兆円"), table)
        self.assertEqual((r["判定"], r["達成の年"]), ("期限なし（到達）", 2023))

    def test_zero_balance_is_not_a_surplus(self):
        self.assertFalse(ts.reached(-0.0, 0, "黒字化", "surplus"))

    def test_rates_without_year_use_the_average(self):
        table = series("sna-qe:実質GDP成長率:年度", {2016: 0.5, 2020: -3.9, 2021: 3.8})
        r = ts.judge(target("国策-honebuto-2015", "実質GDP成長率", 2.0, "%程度"), table)
        self.assertEqual(r["判定"], "期限なし（未到達）")  # 2021年の反動 3.8% だけでは到達にしない
        self.assertAlmostEqual(r["達成の値"], 0.08, places=2)  # (1.005×0.961×1.038)^(1/3)−1

    def test_ten_year_average_from_levels(self):
        table = series("sna-qe:名目GDP:年度", {2012: 100.0, 2022: 121.899})
        r = ts.judge(target("国策-honebuto-2013", "名目GDP成長率(10年平均)", 3.0, "%程度", 2022, "年度"), table)
        self.assertEqual((r["判定"], r["達成の値"]), ("未達", 2.0))

    def test_gdp_level_follows_the_year_kind(self):
        table = {**series(ts.GDP_CY, {2020: 539e12}), **series(ts.GDP_FY, {2020: 540e12, 2023: 600e12})}
        r = ts.judge(target("国策-honebuto-2018", "名目GDP", 600, "兆円", 2020, "年"), table)
        self.assertEqual((r["系列ID"], r["判定"]), (ts.GDP_CY, "未達"))
        r = ts.judge(target("国策-honebuto-2017", "名目GDP(600兆円経済)", 600, "兆円"), table)
        self.assertEqual((r["系列ID"], r["判定"], r["達成の年"]), (ts.GDP_FY, "期限なし（到達）", 2023))

    def test_qualifier_over_needs_strictly_more(self):
        table = series("x", {2025: 150e12})
        self.assertFalse(ts.reached(150e12, 150e12, "兆円超", "level"))
        self.assertTrue(ts.reached(150e12, 150e12, "兆円程度", "level"))

    def test_mismatched_definitions_are_not_linked(self):
        for t in (target("国策-honebuto-2016", "政府研究開発投資の対GDP比", 1.0, "%"),
                  target("国策-honebuto-2013", "1人当たり名目国民総所得(名目GNI)の増加額", 150, "万円以上"),
                  target("国策-honebuto-2019", "温室効果ガス排出量の削減率", 80, "%", 2050, "年"),
                  target("国策-honebuto-2015", "後発医薬品の数量シェア", 80, "%以上", 2020, "年度")):
            r = ts.judge(t, {})
            self.assertEqual((r["判定"], r["系列ID"]), ("結ばない", ""), t["指標"])
            self.assertTrue(r["理由"])

    def test_committed_links_cover_every_target(self):
        targets = read_csv(ts.TARGETS)
        links = read_csv(ts.OUT / "target-links.csv")
        self.assertEqual(len(links), len(targets))
        self.assertEqual([(t["決定ID"], t["指標"]) for t in targets], [(r["決定ID"], r["指標"]) for r in links])
        for r in links:
            self.assertTrue(r["理由"], r)
            self.assertEqual(bool(r["系列ID"]), r["判定"] != "結ばない", r)


if __name__ == "__main__":
    unittest.main()
