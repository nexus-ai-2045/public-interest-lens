"""scripts/fetch_fiscal_more.py の読み取り（主要経費別の表・国債の PDF の文字・地方財政白書の CSV・数値目標の照合・DB への取り込み）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import fetch_fiscal_more as ff  # noqa: E402

URL = "https://www.mof.go.jp/x.xlsx"


class Basics(unittest.TestCase):
    def test_number(self):
        self.assertEqual(ff.number("△93,486"), -93486.0)
        self.assertEqual(ff.number("－"), 0.0)
        self.assertEqual(ff.number("(9,689)"), 9689.0)
        self.assertIsNone(ff.number("撤回"))

    def test_wareki_year(self):
        self.assertEqual(ff.wareki_year("令和８年度"), 2026)
        self.assertEqual(ff.wareki_year("Ｈ元"), 1989)
        self.assertEqual(ff.wareki_year("昭和42"), 1967)
        self.assertEqual(ff.wareki_year("R8"), 2026)

    def test_due(self):
        with tempfile.TemporaryDirectory() as d:
            stamp = Path(d) / "last.txt"
            self.assertTrue(ff.due(date(2026, 10, 24), stamp))
            stamp.write_text("2026-10-01\n", encoding="utf-8")  # 古い形（日付だけ）
            self.assertFalse(ff.due(date(2026, 10, 24), stamp))
            self.assertTrue(ff.due(date(2026, 10, 29), stamp))

    def test_due_per_phase(self):
        # 落ちた段（地方財政）だけ1週間後に取り直し、ほかの段は28日待つ
        with tempfile.TemporaryDirectory() as d:
            stamp = Path(d) / "last.txt"
            ok = {p: True for p in ff.FETCH_PHASES}
            ff.record_fetch(dict(ok, local=False), stamp, today=date(2026, 10, 1))
            self.assertFalse(ff.due(date(2026, 10, 5), stamp, phase="local"))
            self.assertTrue(ff.due(date(2026, 10, 8), stamp, phase="local"))
            self.assertFalse(ff.due(date(2026, 10, 8), stamp, phase="special"))
            ff.record_fetch({"local": True}, stamp, today=date(2026, 10, 8))
            self.assertFalse(ff.due(date(2026, 10, 20), stamp))
            self.assertTrue(ff.due(date(2026, 10, 29), stamp, phase="special"))


class Budget(unittest.TestCase):
    def rows(self):
        # 第19表(2) の形：見出し（数値なし）→ 番号つきの内訳 → 計。数値のある主要経費。「計」の無い見出し。小計。総合計。
        return [
            [None, None, None, None, None, None, "（単位：千円）"],
            ["令　和　８　年　度", None, None, None, None, None, None],
            ["主　要　経　費　別", None, None, None, "当　初　予　算", "補　正　予　算", "計"],
            [None, "社会保障関係費", None, None, None, None, None],
            [None, "1.", "年金給付費", None, 1_000_000, "-", 1_000_000],
            [None, "2.", "介護給付費", None, None, None, None],
            [None, "3.", "医療給付費", None, 500_000, 100_000, 600_000],
            [None, "計", None, None, 1_500_000, 100_000, 1_600_000],
            [None, "国債費", None, None, 2_000_000, "△200,000", 1_800_000],
            [None, "地方財政関係費", None, None, None, None, None],
            [None, None, "地方交付税交付金", None, 700_000, "-", 700_000],
            [None, "公共事業関係費", None, None, None, None, None],
            [None, "1.", "道路整備事業費", None, 300_000, "-", 300_000],
            [None, "小　　計", None, None, 300_000, "-", 300_000],
            [None, "2.", "災害復旧等事業費", None, 100_000, 50_000, 150_000],
            [None, "計", None, None, 400_000, 50_000, 450_000],
            [None, "合　　計", None, None, 4_600_000, -50_000, 4_550_000],
            [None, "前年度決算不足補てん繰戻", None, None, 100_000, "-", 100_000],
            [None, "総合計", None, None, 4_700_000, -50_000, 4_650_000],
            [None, "（注）本表は…", None, None, None, None, None],
        ]

    def test_parse_sheet(self):
        out, totals, notes = ff.parse_budget_sheet(self.rows(), "R8", "19b", URL)
        majors = {(r["項目"], r["段階"]): r["金額_億円"] for r in out if r["区分"] == "主要経費別"}
        self.assertEqual(majors[("社会保障関係費", "当初")], 15.0)
        self.assertEqual(majors[("国債費", "補正")], -2.0)
        self.assertEqual(majors[("地方財政関係費", "当初")], 7.0)  # 「計」の無い見出しは内訳の足し上げ
        self.assertEqual(majors[("公共事業関係費", "当初")], 4.0)  # 小計は採らない
        self.assertEqual(majors[("前年度決算不足補てん繰戻", "当初")], 1.0)
        self.assertNotIn(("介護給付費", "当初"), majors)
        children = {r["項目"] for r in out if r["区分"] == "主要経費別の内訳"}
        self.assertEqual(children, {"年金給付費", "医療給付費", "地方交付税交付金", "道路整備事業費", "災害復旧等事業費"})
        self.assertEqual({r["年度"] for r in out}, {2026})
        total = {t["段階"]: t["歳出_億円"] for t in totals}
        self.assertEqual(total["当初"], 47.0)  # 総合計を採る
        # 主要経費の足し上げが総合計と合う（照合で使う関係）
        self.assertAlmostEqual(sum(v for (k, st), v in majors.items() if st == "当初"), 47.0)

    def test_sub_numbering_is_child_of_numbered_major(self):
        rows = [
            ["昭　和　25　年　度", None, None, None, None, None, None, None],
            ["重　要　経　費　別", None, None, None, None, "当初予算", "補正予算", "合　計"],
            [None, "6.", "公共事業費", None, None, 990_000, 40_000, 1_030_000],
            [None, None, "⑴ ", "災害復旧", None, 470_000, 41_000, 511_000],
            [None, "7.", "出資及投資関係", None, None, 110_000, 130_000, 240_000],
            [None, None, "合　計", None, None, 1_100_000, 170_000, 1_270_000],
        ]
        out, totals, _ = ff.parse_budget_sheet(rows, "昭和25", "19a", URL)
        majors = [r["項目"] for r in out if r["区分"] == "主要経費別" and r["段階"] == "当初"]
        self.assertEqual(majors, ["公共事業費", "出資及投資関係"])
        self.assertEqual([r["主要経費"] for r in out if r["区分"] == "主要経費別の内訳"], ["公共事業費", "公共事業費"])
        self.assertEqual(out[0]["年度"], 1950)

JGB_TEXT = """                                                                国債発行額の推移（実績ベース）
 度               ４条債        特例債
 40      1,972          -     1,972      -     -      -    -      -     -           -       1,972  5.3        2,000         0.6       220    0.6 41.1 シ団引受開始
 41      6,656     6,656           -     -     -      -    -      -     -           -       6,656 14.9        8,750         2.2       489    1.1
\f
 5     349,980     90,680   259,300       -         -    15,401       -        -     29,959   1,539,211   1,934,552 27.4     10,536,526    170.1     252,503   22.1
 6     371,390     96,590   274,800               260    10,551    1,964       -     94,907   1,329,746   1,808,819 30.2     10,797,344    168.1     270,090   24.0
 7     403,431    103,300   300,131       -         -    13,541   11,397     256    120,000   1,347,243   1,895,869 30.2     11,367,719    169.7     282,179   24.5
（注）令和６年度までは実績。令和７年度は補正後、令和８年度は当初。
"""


# 第20表（決算）の形：「（社会保障関係費）」の見出しと内訳が同じ列に並び、番号が無い。
SETTLEMENT_ROWS = [
    [None, None, None, None, None, "（単位：千円）"],
    ["令\u3000和\u30006\u3000年\u3000度", None, None, None, None, None],
    [None, "主\u3000要\u3000経\u3000費\u3000別", None, "予\u3000算\u3000現\u3000額", "決\u3000算\u3000額", "差\u3000引\u3000額"],
    [None, "（社会保障関係費）", None, None, None, None],
    [None, "年金給付費", None, 13_000_000_000, 11_000_000_000, 2_000_000_000],
    [None, "医療給付費", None, 12_000_000_000, 12_000_000_000, 0],
    [None, "計", None, 25_000_000_000, 23_000_000_000, 2_000_000_000],
    [None, "国債費", None, 26_000_000_000, 25_000_000_000, 1_000_000_000],
    [None, "（公共事業関係費）", None, None, None, None],
    [None, "道路整備事業費", None, 3_000_000_000, 2_000_000_000, 1_000_000_000],
    [None, "小\u3000\u3000計", None, 3_000_000_000, 2_000_000_000, 1_000_000_000],
    [None, "災害復旧等事業費", None, 1_000_000_000, 500_000_000, 500_000_000],
    [None, "計", None, 4_000_000_000, 2_500_000_000, 1_500_000_000],
    [None, "合\u3000\u3000計", None, 55_000_000_000, 50_500_000_000, 4_500_000_000],
]


class Settlement(unittest.TestCase):
    def test_bracketed_headings_in_same_column(self):
        out, totals, _ = ff.parse_budget_sheet(SETTLEMENT_ROWS, "令和6", "20", URL)
        majors = {r["主要経費"]: r["金額_億円"] for r in out if r["区分"] == "主要経費別"}
        self.assertEqual(majors, {"社会保障関係費": 230000.0, "国債費": 250000.0, "公共事業関係費": 25000.0})
        inner = {r["項目"] for r in out if r["区分"] == "主要経費別の内訳"}
        self.assertEqual(inner, {"年金給付費", "医療給付費", "道路整備事業費", "災害復旧等事業費"})
        self.assertEqual(sum(majors.values()), totals[0]["歳出_億円"])


# 平成6〜8年度は特例債の欄が2段（＜減税特例公債＞と［震災特例公債］、または括弧書きと残り）
JGB_SPLIT = "\n".join([
    "平成6     164,900   123,457 <33,337>        -     -      -    -      -         -   228,817   393,717 17.9     2,066,046    39.6      143,602   19.6",
    "                           [8,106]",
    " 7     212,470   164,401 <28,511>        -     -      -    -      -         -   253,767   466,238 24.2     2,251,847    42.1      132,213   18.6",
    "                          19,558",
    " 9     184,580    99,400     85,180      -     -      -    -      -         -   314,320   498,900 23.5     2,579,875    46.7      168,023   21.7",
])


class Jgb(unittest.TestCase):
    def test_split_special_bonds(self):
        rows, notes = ff.parse_jgb_issue(JGB_SPLIT, URL)
        self.assertEqual(notes, [])
        got = {(r["年度"], r["項目"]): r["金額_億円"] for r in rows}
        # 特例債＝小計−4条債（括弧書きを含む）、括弧書きは「うち」の内訳
        self.assertEqual(got[(1994, "特例債")], 41443.0)
        self.assertEqual(got[(1994, "うち減税特例公債")], 33337.0)
        self.assertEqual(got[(1994, "うち震災特例公債")], 8106.0)
        self.assertEqual(got[(1995, "特例債")], 48069.0)
        self.assertNotIn((1995, "うち震災特例公債"), got)
        self.assertEqual(got[(1997, "特例債")], 85180.0)
        kinds = {r["区分"] for r in rows if r["項目"].startswith("うち")}
        self.assertEqual(kinds, {"国債発行額の内訳"})

    def test_columns_by_position(self):
        text = JGB_TEXT.replace(" 5     ", "令和5    ", 1)
        rows, notes = ff.parse_jgb_issue(text, URL)
        self.assertEqual(notes, [])
        got = {(r["年度"], r["項目"]): r["金額_億円"] for r in rows}
        self.assertEqual(got[(1965, "特例債")], 1972.0)
        self.assertEqual(got[(1966, "4条債（建設国債）")], 6656.0)
        # 令和6年度は年金特例債の欄が空。復興債 260、GX 10,551、子ども 1,964 が右の列にずれずに入る
        self.assertEqual(got[(2024, "年金特例債")], 0.0)
        self.assertEqual(got[(2024, "復興債")], 260.0)
        self.assertEqual(got[(2024, "GX経済移行債")], 10551.0)
        self.assertEqual(got[(2024, "子ども特例債")], 1964.0)
        self.assertEqual(got[(2024, "普通国債残高")], 10797344.0)
        status = {r["年度"]: r["実績の別"] for r in rows}
        self.assertEqual((status[2024], status[2025]), ("実績", "補正後"))

    def test_balance_first_table_only(self):
        text = "平成19     5,414,584   3,543,655\n  20     5,459,356   3,542,378\n国鉄\n平成19      194,129      69,871\n"
        rows = ff.parse_jgb_balance(text, URL)
        self.assertEqual([(r["年度"], r["金額_億円"]) for r in rows], [(2007, 5414584.0), (2008, 5459356.0)])


LOCAL_CSV = """第11表　歳入決算額の状況（つづき）,,,
その2　推　　移,,,
区分,歳　　入　　決　　算　　額,,
,令和元年度,2年度,3年度
地方税,"41,211,450","40,825,620","42,408,938"
地方交付税,"16,739,246","16,988,952","19,504,879"
小計（一般財源）,"61,032,809","60,272,516","64,815,291"
国庫支出金,"15,834,380","37,455,724","32,071,593"
地方債,"10,870,548","12,260,718","11,745,371"
"""


class Local(unittest.TestCase):
    def test_trend(self):
        rows = ff.parse_local_trend(LOCAL_CSV, URL, "r08")
        got = {(r["年度"], r["項目"]): r["金額_億円"] for r in rows}
        self.assertEqual(got[(2019, "地方交付税")], 167392.46)
        self.assertEqual(got[(2020, "国庫支出金（交通安全対策特別交付金等を含む）")], 374557.24)
        self.assertIn((2021, "一般財源（小計）"), got)


class FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages, self.asked = pages, []

    def text(self, url: str) -> str:
        self.asked.append(url)
        if url not in self.pages:
            raise OSError(url)
        return self.pages[url]


class RegisterEverything(unittest.TestCase):
    def test_html_pages_are_registered_too(self):
        import io
        with tempfile.TemporaryDirectory() as d:
            saved = (ff.RAW, ff.OUT, ff.register, ff.urllib.request.urlopen, ff.ROOT)
            ff.ROOT, ff.RAW, ff.OUT = Path(d), Path(d) / "raw", Path(d) / "out"
            ff.OUT.mkdir()
            got = []
            ff.register = lambda path, url: got.append(url)

            class Response(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            ff.urllib.request.urlopen = lambda request, timeout=60: Response(b"<html></html>")
            try:
                ff.Fetcher(wait=0).get("https://www5.cao.go.jp/keizai-shimon/kaigi/cabinet/honebuto/honebuto-index.html")
                ff.Fetcher(wait=0).get("https://www.digital.go.jp/policies/priority-policy-program")
            finally:
                ff.RAW, ff.OUT, ff.register, ff.urllib.request.urlopen, ff.ROOT = saved
        self.assertEqual(len(got), 2)  # 拡張子の無い一覧ページも登録する


class LocalFinder(unittest.TestCase):
    def test_checks_csv_heading_not_number(self):
        # 令和7年版から s-010-2 は「繰越額等」、歳入の推移は s-011-2。表の番号ではなく CSV の見出しで決める
        base = "https://www.soumu.go.jp/menu_seisaku/hakusyo/chihou/r08data/"
        pages = {
            base + "index-czs.html": '<a href="2026data/r08czs00-00.html">資料編</a>',
            base + "2026data/r08czs00-00.html": '<a href="r08czs01-01.html">総括</a><a href="r08czs01-02.html">歳入</a>',
            base + "2026data/r08czs01-01.html": '<a href="csv/s-010-2.csv">CSV</a>',
            base + "2026data/r08czs01-02.html": '<a href="csv/s-011-2.csv">CSV</a>',
            base + "2026data/csv/s-010-2.csv": "第10表　繰越額等の状況（つづき）,,,\nその2　都道府県,,,\n",
            base + "2026data/csv/s-011-2.csv": LOCAL_CSV,
        }
        fetcher = FakeFetcher(pages)
        rows = ff._find_local_trend(fetcher, base + "index-czs.html", "r08")
        self.assertEqual({r["出典URL"] for r in rows}, {base + "2026data/csv/s-011-2.csv"})
        self.assertNotIn(base + "2026data/r08czs01-01.html", fetcher.asked)  # 「歳入」のページを先に読む


class LocalKeepsMissingEditions(unittest.TestCase):
    def test_failed_edition_keeps_previous_rows(self):
        with tempfile.TemporaryDirectory() as d:
            saved = (ff.OUT, ff._find_local_trend)
            ff.OUT = Path(d)
            idx = "https://www.soumu.go.jp/menu_seisaku/hakusyo/chihou/"
            index = f'<a href="{idx}28data/index.html">28</a><a href="{idx}r08data/index-czs.html">r08</a>'
            ff.write_csv(ff.OUT / "local-revenue.csv", ff.LOCAL_HEADER, [
                {"年度": 2009, "項目": "地方税", "金額_億円": 1, "白書の版": "28", "出典URL": URL},
                {"年度": 2023, "項目": "地方税", "金額_億円": 2, "白書の版": "r08", "出典URL": URL}])
            ff._find_local_trend = lambda fetcher, start, edition: [] if edition == "28" else [
                {"年度": 2024, "項目": "地方税", "金額_億円": 3, "白書の版": "r08", "出典URL": URL}]
            try:
                result = ff.fetch_local(FakeFetcher({ff.HAKUSYO_INDEX: index}))
                years = sorted(int(r["年度"]) for r in ff.read_csv(ff.OUT / "local-revenue.csv"))
            finally:
                ff.OUT, ff._find_local_trend = saved
        self.assertEqual(years, [2009, 2024])  # 取れなかった版（28）の行は残す。取れた版（r08）は新しい行で置き換える
        self.assertEqual(result["前回のまま残した行"], 1)


class Targets(unittest.TestCase):
    def test_only_matching_and_real_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            out, text, a, b = d / "out", d / "text", d / "a", d / "b"
            for p in (out, text, a, b):
                p.mkdir()
            saved = (ff.OUT, ff.TEXT, ff.WORK)
            ff.OUT, ff.TEXT, ff.WORK = out, text, d  # 実物の .local/fiscal/target-disagreements.csv を書き換えない
            try:
                (text / "国策-honebuto-2015.txt").write_text("2020年度までに国・地方を合わせた基礎的財政収支の黒字化を目指す。\n名目GDP600兆円を目指す。", encoding="utf-8")
                ff.write_csv(out / "policies.csv", ff.POLICY_HEADER, [{"決定ID": "国策-honebuto-2015", "本文URL": "https://www5.cao.go.jp/a.pdf"}])
                pb = {"line": 1, "quote": "2020年度までに国・地方を合わせた基礎的財政収支の黒字化を目指す。", "indicator": "PB", "target_value": 0,
                      "unit": "黒字化", "target_year": 2020, "year_kind": "年度"}
                made_up = {"line": 2, "quote": "名目GDP700兆円を2030年に達成する。", "indicator": "名目GDP", "target_value": 700, "unit": "兆円",
                           "target_year": 2030, "year_kind": "年"}
                only_a = {"line": 2, "quote": "名目GDP600兆円を目指す。", "indicator": "名目GDP", "target_value": 600, "unit": "兆円",
                          "target_year": None, "year_kind": "不明"}
                (a / "国策-honebuto-2015.json").write_text(json.dumps({"targets": [pb, made_up, only_a]}, ensure_ascii=False), encoding="utf-8")
                (b / "国策-honebuto-2015.json").write_text(json.dumps({"targets": [dict(pb, quote="基礎的財政収支の黒字化"), made_up]},
                                                                  ensure_ascii=False), encoding="utf-8")
                # 前回の結果：本文の無い文書（国策-honebuto-2018）の行は照合し直せないので残す
                ff.write_csv(out / "policy-targets.csv", ff.TARGET_HEADER, [{"決定ID": "国策-honebuto-2018", "指標": "x", "目標値": 1}])
                (a / "国策-honebuto-2018.json").write_text(json.dumps({"targets": []}), encoding="utf-8")
                result = ff.compare_targets(a, b)
                rows = ff.read_csv(out / "policy-targets.csv")
                disagreements = ff.read_csv(d / "target-disagreements.csv")
            finally:
                ff.OUT, ff.TEXT, ff.WORK = saved
        self.assertEqual(result["採った目標"], 1)
        self.assertEqual([r["決定ID"] for r in rows], ["国策-honebuto-2018", "国策-honebuto-2015"])
        self.assertEqual((rows[1]["指標"], rows[1]["目標値"], rows[1]["目標年"]), ("PB", "0.0", "2020"))
        self.assertTrue(any(r["理由"] == "原文が本文に見つからない" for r in disagreements))

    def test_value_must_be_in_quote(self):
        self.assertTrue(ff._value_in_quote(30.0, "%", "運用等経費等の３割削減目標"))
        self.assertTrue(ff._value_in_quote(600.0, "兆円", "名目ＧＤＰ６００兆円"))
        self.assertFalse(ff._value_in_quote(700.0, "兆円", "名目GDP600兆円を目指す"))
        self.assertFalse(ff._value_in_quote(50.0, "%", "2050年度までに排出量を10%削減する。"))  # 年の中の 50 を取らない
        self.assertTrue(ff._value_in_quote(10.0, "%", "2050年度までに排出量を10%削減する。"))
        self.assertTrue(ff._value_in_quote(150.0, "団体", "全国 150 の地方公共団体における計画の策定"))
        self.assertIsNone(ff._qualifier(20.0, "%", "数年で法人実効税率を20％台まで引き下げる"))  # 幅のある目標は採らない
        self.assertEqual(ff._qualifier(30.0, "%", "30%以上とする"), "以上")
        self.assertEqual(ff._qualifier(100.0, "地域", "100以上の地域において"), "以上")  # 数と数え方の語の間の限定語
        self.assertEqual(ff._qualifier(100.0, "%", "おおむね全ての医療機関・薬局に対し"), "（おおむね）")
        self.assertEqual(ff._qualifier(100.0, "%", "全ての都道府県において"), "")
        self.assertEqual(ff._qualifier(150.0, "団体", "全国 150 の地方公共団体"), "")
        self.assertEqual(ff._qualifier(600.0, "兆円", "名目GDP600兆円を目指す"), "")
        self.assertEqual(ff._qualifier(150.0, "兆円", "150兆円超の投資"), "超")  # 単位を全部読んでから語を見る
        self.assertEqual(ff._qualifier(150.0, "万円", "GNIを150万円以上増加"), "以上")
        self.assertEqual(ff._qualifier(50.0, "%", "5割程度とする"), "程度")
        self.assertIsNone(ff._qualifier(2.0, "%", "2030年までに成長率を1～2%にする。"))  # 幅の上限だけを1つの値にしない
        self.assertIsNone(ff._qualifier(2.0, "%", "成長率を1%～2%にする"))
        self.assertEqual(ff._qualifier(28.0, "万人", "約28万人を育成する"), "（約）")
        self.assertFalse(ff._value_in_quote(230.0, "万人", "2030年までに年間の補助額を230万円にする。"))  # 「万」だけで人と円を取り違えない
        self.assertTrue(ff._value_in_quote(230.0, "万円", "2030年までに年間の補助額を230万円にする。"))
        self.assertFalse(ff._value_in_quote(230.0, "円", "2030年までに年間の補助額を230万円にする。"))  # 倍率を読み飛ばさない
        self.assertTrue(ff._value_in_quote(150.0, "団体", "全国 150 の地方公共団体"))
        self.assertTrue(ff._value_in_quote(5.0, "兆円", "5兆の投資"))
        self.assertFalse(ff._value_in_quote(100.0, "%", "2030年度までに全国の施設の導入率を10%にする。"))
        self.assertFalse(ff._value_in_quote(0.0, "黒字化", "2030年度までに財政赤字を10兆円まで削減する。"))  # 黒字化も本文で確かめる
        self.assertTrue(ff._value_in_quote(0.0, "黒字化", "2025年度の国・地方を合わせたPB黒字化を目指す"))  # 「全国」の「全」で 100% にしない
        self.assertTrue(ff._value_in_quote(100.0, "%", "全ての都道府県で実施する"))
        self.assertEqual(ff._year_kind(2030, "2030年度までに導入率を10%にする"), "年度")  # 年の別は本文で決める
        self.assertEqual(ff._year_kind(2030, "2030年までに"), "年")
        self.assertEqual(ff._year_kind(2030, "2030年に、2030年度までに"), "不明")
        self.assertEqual(ff._year_kind(2020, "平成 32 年までに"), "年")  # 元号の年も見る
        self.assertFalse(ff._year_in(2040, "2030年度までに排出量を50%削減する。"))  # 本文と違う目標年は採らない
        self.assertTrue(ff._year_in(2031, "令和 13 年度末までに"))
        self.assertTrue(ff._year_in(None, "目標年の無い目標"))
        self.assertEqual(ff._year_kind(2031, "令和 13 年度末までに"), "年度")  # 数の前の語も残す
        self.assertEqual(ff._qualifier(100.0, "か所", "少なくとも100か所に広げる"), "（少なくとも）")  # 割で書かれた目標

    def test_quote_must_be_whole_and_same_place(self):
        text = ff.squash("2030年度までに風力発電設備の比率を50%にする。\n2030年度までに女性役員の比率を50%にする。\n名目GDP600兆円を目指す。")
        wind, women = ff._locate("2030年度までに風力発電設備の比率を50%にする", text), ff._locate("2030年度までに女性役員の比率を50%にする", text)
        self.assertFalse(ff._same_passage(wind, women))  # 年と値が同じでも別の目標
        self.assertTrue(ff._same_passage(wind, ff._locate("風力発電設備の比率を50%", text)))
        # 先頭が本文にあっても、付け足した部分（999兆円）が本文に無ければ採らない
        self.assertIsNone(ff._locate("2030年度までに風力発電設備の比率を50%にする。名目GDP999兆円を目指す", text))
        self.assertIsNotNone(ff._locate("2030年度までに風力発電設備…50%にする", text))

    def test_zero_adopted_removes_old_rows(self):
        # 照合できた文書で採用が0件なら、前回の行を消す（読み手の直しで目標が無くなった場合）
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            out, text, a, b = d / "out", d / "text", d / "a", d / "b"
            for p in (out, text, a, b):
                p.mkdir()
            saved = (ff.OUT, ff.TEXT, ff.WORK, ff.TARGETS)
            ff.OUT, ff.TEXT, ff.WORK, ff.TARGETS = out, text, d, d
            try:
                (text / "国策-x.txt").write_text("名目GDP600兆円を目指す。", encoding="utf-8")
                ff.write_csv(out / "policies.csv", ff.POLICY_HEADER, [{"決定ID": "国策-x"}])
                ff.write_csv(out / "policy-targets.csv", ff.TARGET_HEADER, [{"決定ID": "国策-x", "指標": "古い", "目標値": 1}])
                for line in (a, b):
                    (line / "国策-x.json").write_text(json.dumps({"targets": []}), encoding="utf-8")
                result = ff.compare_targets(a, b)
                rows = ff.read_csv(out / "policy-targets.csv")
            finally:
                ff.OUT, ff.TEXT, ff.WORK, ff.TARGETS = saved
        self.assertEqual((result["採った目標"], rows), (0, []))

    def test_pending_readers(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            saved = (ff.TEXT, ff.TARGETS)
            ff.TEXT, ff.TARGETS = d / "text", d / "targets"
            try:
                for p in (ff.TEXT, ff.TARGETS / "a", ff.TARGETS / "b"):
                    p.mkdir(parents=True)
                (ff.TEXT / "国策-新.txt").write_text("あ" * 2000, encoding="utf-8")
                (ff.TEXT / "国策-文字なし.txt").write_text("", encoding="utf-8")
                (ff.TEXT / "国策-済.txt").write_text("あ" * 2000, encoding="utf-8")
                for line in ("a", "b"):
                    (ff.TARGETS / line / "国策-済.json").write_text("{}", encoding="utf-8")
                self.assertEqual(ff.targets_pending(), ["国策-新"])
            finally:
                ff.TEXT, ff.TARGETS = saved


class SpecialTotal(unittest.TestCase):
    def test_total_without_local_transfers(self):
        # 平成24年度 当初：足し上げ 3,940,944.89、表の合計 3,736,137.10、地方交付税等の3つで 204,807.79
        self.assertEqual(ff.sum_for_total(3940944.89, 204807.79, 3736137.10, 3.7), (3736137.1, ff.TOTAL_WITHOUT_LOCAL))
        self.assertEqual(ff.sum_for_total(100.0, 0.0, 100.0, 1.0), (100.0, ""))
        self.assertEqual(ff.sum_for_total(150.0, 10.0, 100.0, 1.0), (150.0, ""))  # 3つを除いても合わなければそのまま（不一致）


class PolicyTexts(unittest.TestCase):
    def test_first_text_keeps_targets_from_the_same_source(self):
        # 新しい手元で初めて本文を作るだけなら、同じ本文URL で採った目標は残す
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            saved = (ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text)
            ff.OUT, ff.TEXT, ff.TARGETS = d / "out", d / "text", d / "targets"
            ff.pdf_text = lambda path: "本文"
            try:
                ff.OUT.mkdir(parents=True)
                url = "https://example.go.jp/a.pdf"
                ff.write_csv(ff.OUT / "policies.csv", ff.POLICY_HEADER, [{"決定ID": "国策-x", "本文URL": url}])
                ff.write_csv(ff.OUT / "policy-targets.csv", ff.TARGET_HEADER,
                             [{"決定ID": "国策-x", "指標": "残る", "目標値": 1, "本文URL": url}])
                got = type("G", (), {"get": lambda self, u: None, "path": lambda self, u: u})()
                self.assertEqual(ff.policy_texts(got), {"本文を文字にした": 1})
                self.assertEqual([t["指標"] for t in ff.read_csv(ff.OUT / "policy-targets.csv")], ["残る"])
            finally:
                ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text = saved

    def test_new_source_url_refreshes_text_and_readers(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            saved = (ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text)
            ff.OUT, ff.TEXT, ff.TARGETS = d / "out", d / "text", d / "targets"
            ff.pdf_text = lambda path: f"新しい本文 {path}"
            try:
                for p in (ff.OUT, ff.TEXT, ff.TARGETS / "a", ff.TARGETS / "b"):
                    p.mkdir(parents=True)
                ff.write_csv(ff.OUT / "policies.csv", ff.POLICY_HEADER, [{"決定ID": "国策-x", "本文URL": "https://example.go.jp/new.pdf"}])
                (ff.TEXT / "国策-x.txt").write_text("古い本文", encoding="utf-8")
                (ff.TEXT / "国策-x.url").write_text("https://example.go.jp/old.pdf", encoding="utf-8")
                for line in ("a", "b"):
                    (ff.TARGETS / line / "国策-x.json").write_text("{}", encoding="utf-8")
                ff.write_csv(ff.OUT / "policy-targets.csv", ff.TARGET_HEADER,
                             [{"決定ID": "国策-x", "指標": "古い", "目標値": 1}, {"決定ID": "国策-y", "指標": "残る", "目標値": 2}])

                class Got:
                    def get(self, url):
                        self.url = url

                    def path(self, url):
                        return url
                self.assertEqual(ff.policy_texts(Got()), {"本文を文字にした": 1})
                self.assertIn("new.pdf", (ff.TEXT / "国策-x.txt").read_text(encoding="utf-8"))
                self.assertEqual(ff.text_source("国策-x"), "https://example.go.jp/new.pdf")
                self.assertFalse((ff.TARGETS / "a" / "国策-x.json").exists())  # 古い本文を読んだ結果は読み手待ちに戻す
                self.assertEqual([t["決定ID"] for t in ff.read_csv(ff.OUT / "policy-targets.csv")], ["国策-y"])  # 古い本文で採った目標も外す
                self.assertEqual(ff.policy_texts(Got()), {"本文を文字にした": 0})  # 同じ取得元なら取り直さない
            finally:
                ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text = saved


    def test_blank_text_is_extracted_again(self):
        # 日本語フォント非埋め込みの PDF を CMap 無しで文字にした空の本文（行番号だけ）は取り直す
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            saved = (ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text)
            ff.OUT, ff.TEXT, ff.TARGETS = d / "out", d / "text", d / "targets"
            ff.pdf_text = lambda path: "目標を目指す"
            try:
                for p in (ff.OUT, ff.TEXT):
                    p.mkdir(parents=True)
                url = "https://example.go.jp/a.pdf"
                ff.write_csv(ff.OUT / "policies.csv", ff.POLICY_HEADER, [{"決定ID": "国策-x", "本文URL": url}])
                (ff.TEXT / "国策-x.txt").write_text("1\n2\n3\n", encoding="utf-8")
                (ff.TEXT / "国策-x.url").write_text(url, encoding="utf-8")
                self.assertTrue(ff.texts_needed())
                got = type("G", (), {"get": lambda self, u: None, "path": lambda self, u: u})()
                self.assertEqual(ff.policy_texts(got), {"本文を文字にした": 1})
                self.assertEqual((ff.TEXT / "国策-x.txt").read_text(encoding="utf-8"), "目標を目指す")
                self.assertFalse(ff.texts_needed())
            finally:
                ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text = saved

    def test_one_blank_pdf_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            saved = (ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text)
            ff.OUT, ff.TEXT, ff.TARGETS = d / "out", d / "text", d / "targets"

            def fake(path):
                if "blank" in path:
                    raise RuntimeError("blank.pdf：日本語の文字が取れない（poppler-data を入れてから取り直す）")
                return "目標を目指す"
            ff.pdf_text = fake
            try:
                ff.OUT.mkdir(parents=True)
                ff.write_csv(ff.OUT / "policies.csv", ff.POLICY_HEADER,
                             [{"決定ID": "国策-x", "本文URL": "https://example.go.jp/blank.pdf"},
                              {"決定ID": "国策-y", "本文URL": "https://example.go.jp/ok.pdf"}])
                got = type("G", (), {"get": lambda self, u: None, "path": lambda self, u: u})()
                self.assertEqual(ff.policy_texts(got), {"本文を文字にした": 1, "日本語が取れない": ["国策-x"]})
                self.assertFalse((ff.TEXT / "国策-x.txt").exists())
                self.assertTrue((ff.TEXT / "国策-y.txt").exists())
                self.assertTrue(ff.texts_needed())  # 取れなかった本文は次の回にまた取る
            finally:
                ff.OUT, ff.TEXT, ff.TARGETS, ff.pdf_text = saved

    def test_pdf_without_japanese_text_stops(self):
        saved = ff.subprocess.run
        ff.subprocess.run = lambda *a, **kw: type("R", (), {"stdout": "1\n2\n———\n"})()
        try:
            with self.assertRaisesRegex(RuntimeError, "poppler-data"):
                ff.pdf_text(Path("x.pdf"))
        finally:
            ff.subprocess.run = saved


class Monthly(unittest.TestCase):
    def test_local_checks_run_even_when_nothing_is_due(self):
        called = []
        saved = (ff.due, ff.compare_targets, ff.check_all, ff.Fetcher)
        ff.due = lambda **kw: False
        ff.compare_targets = lambda: called.append("targets") or {}
        ff.check_all = lambda: called.append("check") or {}
        ff.Fetcher = lambda offline=False: type("F", (), {"save_manifest": lambda self: None})()
        saved_record, saved_needed = ff.record_fetch, ff.texts_needed
        ff.record_fetch = lambda results: called.append(("record", dict(results)))
        ff.texts_needed = lambda: False
        try:
            self.assertEqual(ff.main(["all", "--monthly"]), 0)
        finally:
            ff.due, ff.compare_targets, ff.check_all, ff.Fetcher = saved
            ff.record_fetch, ff.texts_needed = saved_record, saved_needed
        self.assertEqual(called, ["targets", "check", ("record", {})])

    def test_texts_run_when_the_list_has_new_bodies(self):
        # policies を取り直して本文URL が増えた・変わった日は、texts の期限前でも本文を取る
        called = []
        saved = (ff.due, ff.compare_targets, ff.check_all, ff.Fetcher, ff.record_fetch, ff.texts_needed, ff.policy_texts)
        ff.due = lambda **kw: False
        ff.compare_targets = lambda: {}
        ff.check_all = lambda: {}
        ff.Fetcher = lambda offline=False: type("F", (), {"save_manifest": lambda self: None})()
        ff.record_fetch = lambda results: None
        ff.texts_needed = lambda: True
        ff.policy_texts = lambda fetcher: called.append("texts") or {}
        try:
            self.assertEqual(ff.main(["all", "--monthly"]), 0)
        finally:
            ff.due, ff.compare_targets, ff.check_all, ff.Fetcher, ff.record_fetch, ff.texts_needed, ff.policy_texts = saved
        self.assertEqual(called, ["texts"])


class LoadIntoDatabase(unittest.TestCase):
    def test_only_what_passed_and_what_load_fiscal_lacks(self):
        from scripts import build_database as bd

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            more = d / "fiscal-more"
            more.mkdir()
            table = lambda st: "21" if st != "決算" else "22"
            budget = [{"年度": y, "会計": "特別会計", "段階": st, "区分": "主要経費別", "主要経費": "国債費", "項目": "国債費", "金額_億円": 1,
                       "表": table(st), "出典URL": URL} for y in (2020, 2021, 2022) for st in ("当初", "補正", "決算")]
            ff.write_csv(more / "special-budget.csv", ff.BUDGET_HEADER, budget)
            checks = [{"照合": "予算：主要経費の足し上げ＝表の合計", "対象": f"特別会計 {y}年度 {st}（第{table(st)}表）", "判定": "一致"}
                      for y in (2020, 2021, 2022) for st in ("当初", "補正", "決算")]
            checks[3]["判定"] = "不一致"   # 2021 当初が落ちた → 2021 は補正・決算も入れない
            checks[8]["判定"] = "照合できない"  # 2022 決算は照合できない → それだけ入れない
            ff.write_csv(more / "checks.csv", ["照合", "対象", "判定"], checks)
            ff.write_csv(more / "local-revenue.csv", ff.LOCAL_HEADER, [
                {"年度": 2017, "項目": "地方税", "金額_億円": 399044.02, "白書の版": "30", "出典URL": URL},
                {"年度": 2018, "項目": "地方税", "金額_億円": 407514.42, "白書の版": "r03", "出典URL": URL}])
            ff.write_csv(more / "policies.csv", ff.POLICY_HEADER, [
                {"決定ID": "国策-honebuto-2015", "題名": "骨太2015", "決定日": "2015-06-30", "決定の形式": "閣議決定", "所管": "内閣府", "本文URL": URL},
                {"決定ID": "国策-honebuto-2014", "題名": "骨太2014", "決定日": "2014-06-24", "決定の形式": "閣議決定", "所管": "内閣府", "本文URL": URL}])
            ff.write_csv(more / "policy-targets.csv", ff.TARGET_HEADER, [
                {"決定ID": "国策-honebuto-2015", "指標": "PB", "目標値": 0, "単位": "黒字化", "目標年": 2020, "年の別": "年度", "本文URL": URL}])
            saved = bd.FISCAL_MORE
            bd.FISCAL_MORE = more
            try:
                db = bd.Db(d / "t.sqlite")
                # load_fiscal が入れたもの（地方の2018年度と骨太2015）の代わり
                db.insert("fiscal_flows", {"fiscal_year": 2018, "account": "地方（純計）", "stage": "決算", "category": "地方財政（歳入）", "item": "地方税",
                                           "amount": 4.0751442e13, "unit": "円", "decision_id": None, "source_id": None})
                db.insert("decisions", {"decision_id": "国策-honebuto-2015", "country": "JPN", "kind": "国策", "title": "骨太2015"})
                bd.load_fiscal_more(db)
                special = sorted(db.con.execute("SELECT fiscal_year, stage FROM fiscal_flows WHERE account = '特別会計'").fetchall())
                local = db.con.execute("SELECT fiscal_year, amount FROM fiscal_flows WHERE account = '地方（純計）' ORDER BY 1").fetchall()
                policies = [r for (r,) in db.con.execute("SELECT decision_id FROM decisions WHERE kind = '国策' ORDER BY 1")]
                targets = db.con.execute("SELECT decision_id, target_year, target_year_kind FROM decision_targets").fetchall()
            finally:
                bd.FISCAL_MORE = saved
        self.assertEqual(special, sorted([(2020, "当初"), (2020, "補正"), (2020, "決算"), (2022, "当初"), (2022, "補正")]))
        self.assertEqual(local, [(2017, 399044.02 * 1e8), (2018, 4.0751442e13)])  # 2018 は load_fiscal の行だけ
        self.assertEqual(policies, ["国策-honebuto-2014", "国策-honebuto-2015"])
        self.assertEqual(targets, [("国策-honebuto-2015", 2020, "年度")])  # 暦年か年度かも残す


if __name__ == "__main__":
    unittest.main()
