import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import political_funds as pf


SAMPLE = """\
５ 寄附の内訳
(1) 個人からの寄附
  1  山田太郎      1,000,000   R5/3/1   東京都千代田区   会社員
(2) 法人その他の団体からの寄附
  1  株式会社テスト製作所   500,000   令和5年4月10日   東京都港区
(3) 政治団体からの寄附
  1  日本テスト業政治連盟   300,000   R5. 6. 1   東京都新宿区
本年の収入額
\f
12 政治資金パーティー対価支払者の内訳
  1  テスト工業会   400,000   R5/9/20   大阪府大阪市
14 支出の内訳
  寄附・交付金
  寄附   200,000   R5/12/1   自由テスト党第一支部   東京都
  事務所費
  1  家賃   1,200,000   R5/1/31   株式会社テスト不動産   東京都
  組織活動費
  1  会合費   50,000   R5/2/3   佐藤花子   東京都
"""


class DueTests(unittest.TestCase):
    def test_monthly_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp = Path(tmp) / "last.txt"
            self.assertTrue(pf.due(date(2026, 10, 23), stamp))
            stamp.write_text("2026-10-01\n", encoding="utf-8")
            self.assertFalse(pf.due(date(2026, 10, 23), stamp))
            self.assertTrue(pf.due(date(2026, 10, 29), stamp))


class CrawlTests(unittest.TestCase):
    def test_collects_pdfs_and_follows_only_the_same_path(self):
        pages = {
            "https://www.example.go.jp/seiji/": '<h2>令和5年分 国会議員関係政治団体</h2><a href="a.html">一覧</a><a href="/other/x.html">外</a>'
                                                 '<a href="/main/1.pdf">テスト会（代表者：山田一郎）</a>',
            "https://www.example.go.jp/seiji/a.html": '<h3>令和4年分 政党本部</h3><a href="/main/2.pdf">自由テスト党本部</a>',
        }
        source = {"区分": "総務省", "名前": "総務省", "始点URL": "https://www.example.go.jp/seiji/", "たどるパス": "/seiji/"}
        rows = pf.crawl_source(source, get=lambda url: pages[url], wait=0)
        self.assertEqual([r["PDF_URL"] for r in rows], ["https://www.example.go.jp/main/1.pdf", "https://www.example.go.jp/main/2.pdf"])
        self.assertEqual((rows[0]["年分"], rows[0]["団体区分"], rows[0]["団体名"], rows[0]["関係議員名"]), ("2023", "国会議員関係政治団体", "テスト会", "山田一郎"))
        self.assertEqual((rows[1]["年分"], rows[1]["団体区分"]), ("2022", "政党本部"))


    def test_child_index_page_inherits_parent_year(self):
        pages = {
            "https://www.example.go.jp/seiji/": '<h2>令和5年分</h2><a href="groups.html">資金管理団体</a>',
            "https://www.example.go.jp/seiji/groups.html": '<h3>一覧</h3><a href="/main/3.pdf">テスト会</a><h3>令和4年分</h3><a href="/main/4.pdf">別会</a>',
        }
        source = {"区分": "総務省", "名前": "総務省", "始点URL": "https://www.example.go.jp/seiji/", "たどるパス": "/seiji/"}
        rows = pf.crawl_source(source, get=lambda url: pages[url], wait=0)
        self.assertEqual([(r["年分"], r["団体区分"]) for r in rows], [("2023", "資金管理団体"), ("2022", "資金管理団体")])

    def test_index_pages_are_kept_as_evidence(self):
        pages = {"https://www.example.go.jp/seiji/": '<h2>令和5年分</h2><a href="/main/5.pdf">テスト会（山田一郎）</a>'}
        kept = []
        source = {"区分": "総務省", "名前": "総務省", "始点URL": "https://www.example.go.jp/seiji/", "たどるパス": "/seiji/"}
        rows = pf.crawl_source(source, get=lambda url: pages[url], wait=0, keep=lambda url, html: kept.append(url) or "mat-1")
        self.assertEqual(kept, ["https://www.example.go.jp/seiji/"])
        self.assertEqual(rows[0]["索引ページの資料ID"], "mat-1")

    def test_depth_limits_flat_sites(self):
        pages = {
            "https://www.example.lg.jp/100.htm": '<h2>令和6年分</h2><a href="/200.htm">資金管理団体</a>',
            "https://www.example.lg.jp/200.htm": '<a href="/secure/1.pdf">テスト会</a><a href="/300.htm">トップ</a>',
            "https://www.example.lg.jp/300.htm": '<a href="/secure/2.pdf">関係ない</a>',
        }
        source = {"区分": "都道府県選管", "名前": "例県", "始点URL": "https://www.example.lg.jp/100.htm", "たどるパス": "/", "深さ": "1"}
        rows = pf.crawl_source(source, get=lambda url: pages[url], wait=0)
        self.assertEqual([r["PDF_URL"] for r in rows], ["https://www.example.lg.jp/secure/1.pdf"])

class ParseTests(unittest.TestCase):
    def setUp(self):
        self.rows = pf.parse_lines(SAMPLE, {"sha256": "x", "PDF_URL": "u", "年分": "2023", "報告団体": "テスト会"})

    def test_sections_amounts_and_dates(self):
        got = [(r["区分"], r["相手方種別"], r["金額"], r["年月日"]) for r in self.rows]
        self.assertEqual(got, [
            ("受けた寄附", "個人", "1000000", "2023-03-01"),
            ("受けた寄附", "法人その他の団体", "500000", "2023-04-10"),
            ("受けた寄附", "政治団体", "300000", "2023-06-01"),
            ("パーティー対価", "法人その他の団体", "400000", "2023-09-20"),
            ("出した寄附", "法人その他の団体", "200000", "2023-12-01"),
            ("支出", "法人その他の団体", "1200000", "2023-01-31"),
            ("支出", "個人", "50000", "2023-02-03"),
        ])
        self.assertEqual([r["費目"] for r in self.rows[4:]], ["寄附・交付金", "事務所費", "組織活動費"])
        self.assertEqual(self.rows[5]["相手方"], "株式会社テスト不動産")
        self.assertEqual(self.rows[3]["頁"], "2")
        self.assertEqual(self.rows[4]["相手方"], "自由テスト党第一支部")

    def test_private_individuals_are_not_kept(self):
        for row in self.rows:
            self.assertNotIn("山田太郎", " ".join(row.values()))

        self.assertEqual(self.rows[0]["相手方"], pf.INDIVIDUAL)

    def test_individual_payees_are_named_only_while_published(self):
        payee = self.rows[6]
        self.assertEqual(payee["相手方"], "佐藤花子")
        self.assertNotIn("東京都", payee["相手方"])
        from datetime import date as d
        self.assertEqual(pf.public_name(payee, d(2027, 11, 30)), "佐藤花子")
        self.assertEqual(pf.public_name(payee, d(2027, 12, 1)), pf.INDIVIDUAL)
        self.assertEqual(pf.public_name(self.rows[5], d(2030, 1, 1)), "株式会社テスト不動産")


class CompareAndLinkTests(unittest.TestCase):
    def test_only_rows_both_lines_agree_on_are_taken(self):
        a = [{"sha256": "x", "区分": "受けた寄附", "相手方種別": "法人その他の団体", "相手方": "株式会社A", "金額": "100", "年月日": "2023-01-01", "頁": "3"},
             {"sha256": "x", "区分": "受けた寄附", "相手方": "B連盟", "金額": "200", "年月日": "2023-01-02", "頁": "3"}]
        b = [{"sha256": "x", "区分": "受けた寄附", "相手方種別": "法人その他の団体", "相手方": "株式会社 A", "金額": "100", "年月日": "2023-01-01", "頁": "3"},
             {"sha256": "x", "区分": "受けた寄附", "相手方": "B連盟", "金額": "250", "年月日": "2023-01-02", "頁": "3"}]
        agreed, disagreed = pf.compare(a, b)
        self.assertEqual([r["相手方"] for r in agreed], ["株式会社A"])
        self.assertEqual(sorted(r["照合"] for r in disagreed), ["Aだけ", "Bだけ"])

    def test_link_needs_a_single_candidate(self):
        persons = [{"人物ID": "山田一郎", "氏名": "山田一郎"}, {"人物ID": "鈴木（衆）", "氏名": "鈴木二郎"}, {"人物ID": "鈴木（参）", "氏名": "鈴木二郎"}]
        index = {"u1": {"関係議員名": "山田 一郎", "団体名": "一郎会"}, "u2": {"関係議員名": "鈴木二郎", "団体名": "二郎会"}}
        rows = pf.link([{"sha256": "s1", "PDF_URL": "u1", "相手方": "日本テスト医師連盟", "相手方種別": "政治団体"},
                        {"sha256": "s2", "PDF_URL": "u2", "相手方": "宗教法人テスト教団", "相手方種別": "法人その他の団体"}], index, persons,
                       {"s1": "山田一郎", "s2": "鈴木二郎"})
        self.assertEqual([r["人物ID"] for r in rows], ["山田一郎", ""])
        self.assertEqual([r["団体の種類"] for r in rows], ["業界団体", "宗教団体"])
        self.assertEqual([r["団体名キー"] for r in rows], ["日本テスト医師連盟", "テスト教団"])

    def test_org_key_aligns_spelling_without_merging_names(self):
        from scripts.org_names import org_key
        self.assertEqual(org_key("㈱ テスト商事"), org_key("株式会社テスト商事"))
        self.assertEqual(org_key("一般社団法人　日本テスト協会"), "日本テスト協会")
        self.assertNotEqual(org_key("日本テスト協会"), org_key("日本テスト協会東京支部"))
        self.assertEqual(org_key(""), "")

    def test_link_needs_line_b_to_agree_on_the_member(self):
        persons = [{"人物ID": "山田一郎", "氏名": "山田一郎"}]
        index = {"u1": {"関係議員名": "山田一郎", "団体名": "一郎会"}}
        row = {"sha256": "s1", "PDF_URL": "u1", "相手方": "株式会社A", "相手方種別": "法人その他の団体"}
        got = [pf.link([row], index, persons, att)[0] for att in ({"s1": "山田一郎"}, {"s1": "佐藤三郎"}, {})]
        self.assertEqual([r["人物ID"] for r in got], ["山田一郎", "", ""])
        self.assertEqual([r["帰属の照合"] for r in got], ["A・B一致", "食い違い：B「佐藤三郎」", "系統Bの判定なし"])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "s1.json").write_text('{"関係議員名": "山田 一郎", "根拠": "表紙", "行": [{"区分": "受けた寄附", "相手方": "株式会社A", "相手方種別": "法人その他の団体", "金額": 100, "年月日": "R5/1/1", "頁": 1}]}', encoding="utf-8")
            (Path(tmp) / "s2.json").write_text("[]", encoding="utf-8")
            self.assertEqual(pf.line_b_attribution(Path(tmp)), {"s1": "山田 一郎"})
            self.assertEqual(len(pf.load_line_b(Path(tmp), {})), 1)

    def test_spending_by_member(self):
        rows = [{"人物ID": "山田一郎", "関係議員名": "山田一郎", "報告団体": "一郎会", "年分": "2023", "区分": "支出", "費目": "事務所費", "相手方": "株式会社A", "金額": "100", "PDF_URL": "u"},
                {"人物ID": "山田一郎", "関係議員名": "山田一郎", "報告団体": "党支部", "年分": "2023", "区分": "支出", "費目": "事務所費", "相手方": "株式会社A", "金額": "50", "PDF_URL": "u2"},
                {"人物ID": "山田一郎", "関係議員名": "山田一郎", "報告団体": "一郎会", "年分": "2023", "区分": "出した寄附", "費目": "", "相手方": "B会", "金額": "30", "PDF_URL": "u"},
                {"人物ID": "", "区分": "支出", "費目": "人件費", "相手方": "（個人）", "金額": "999"},
                {"人物ID": "山田一郎", "区分": "受けた寄附", "金額": "1000"}]
        got = pf.spending_by_member(rows)["山田一郎"]
        self.assertEqual(got["団体"], ["一郎会", "党支部"])
        self.assertEqual(got["年分"]["2023"]["合計"], 180)
        self.assertEqual(got["年分"]["2023"]["費目"]["事務所費"], {"金額": 150, "件数": 2})
        self.assertEqual(got["主な支払先"][0]["支払先"], "株式会社A")

    def test_hidden_individuals_still_join_across_years(self):
        a = {"相手方": "佐藤 花子", "相手方種別": "個人"}
        b = {"相手方": "佐藤花子", "相手方種別": "個人"}
        self.assertEqual(pf.payee_key(a), pf.payee_key(b))
        self.assertNotIn("佐藤", pf.payee_key(a))
        rows = [{"人物ID": "x", "年分": y, "区分": "支出", "費目": "人件費", "相手方": pf.INDIVIDUAL, "支払先キー": pf.payee_key(a), "金額": "600000", "報告団体": "会"} for y in ("2019", "2020", "2021")]
        got = pf.spending_by_member(rows)["x"]["偏り"]
        self.assertEqual(got["上位1の割合"], 1.0)
        self.assertEqual(got["印"], ["偏りがある"])

    def test_transfers_to_own_groups_are_not_concentration(self):
        rows = [{"人物ID": "x", "年分": "2023", "区分": "出した寄附", "費目": "", "相手方": "x後援会", "支払先キー": "x後援会", "金額": "9000000", "報告団体": "会"},
                {"人物ID": "x", "年分": "2023", "区分": "支出", "費目": "事務所費", "相手方": "株式会社A", "支払先キー": "株式会社A", "金額": "500000", "報告団体": "会"},
                {"人物ID": "x", "年分": "2023", "区分": "支出", "費目": "事務所費", "相手方": "株式会社B", "支払先キー": "株式会社B", "金額": "500000", "報告団体": "会"}]
        got = pf.spending_by_member(rows)["x"]
        self.assertEqual(got["偏り"]["名前の分かる支払先の合計"], 1000000)
        self.assertEqual(got["年分"]["2023"]["合計"], 10000000)

    def test_attribution_two_of_three(self):
        self.assertEqual(pf.attribution_check("山口 壯", "山口壮"), "A・B一致")
        self.assertEqual(pf.attribution_check("森 ゆうこ", "森 裕子", "森ゆうこ"), "索引・読み手A一致")
        self.assertTrue(pf.attribution_check("森 ゆうこ", "森 裕子", "森裕子").startswith("食い違い"))
        self.assertEqual(pf.attribution_check("", "山田一郎", "山田 一郎"), "読み手A・B一致")
        self.assertEqual(pf.attribution_check("", "山田一郎", "山田二郎"), "関係議員名なし")
        idx = pf.person_index([{"人物ID": "浜地雅一", "氏名": "浜地雅一", "別表記": "濵地雅一"}])
        self.assertEqual(idx.get("浜地雅一"), ["浜地雅一"])

    def test_safe_url_encodes_spaces(self):
        self.assertEqual(pf.safe_url("https://x.go.jp/a/104060_0017 .pdf"), "https://x.go.jp/a/104060_0017%20.pdf")
        self.assertEqual(pf.safe_url("https://x.go.jp/a%20b.pdf?q=1"), "https://x.go.jp/a%20b.pdf?q=1")

    def test_concentration_flags_only_facts(self):
        spread = {"株式会社A": [800_000, {"2021", "2022", "2023"}, {"一郎会"}], "B": [100_000, {"2023"}, {"党支部"}], "C": [100_000, {"2023"}, {"一郎会"}]}
        got = pf.concentration(spread)
        self.assertEqual(got["印"], ["偏りがある"])
        self.assertEqual(got["上位1の割合"], 0.8)
        self.assertTrue(any("3年分" in r for r in got["理由"]))
        self.assertNotIn("不正", " ".join(got["理由"]))
        small = pf.concentration({"A": [90_000, {"2023"}, {"x"}], "B": [10_000, {"2023"}, {"x"}]})
        self.assertEqual(small["印"], [])

    def test_small_amounts_and_surnames_with_kai(self):
        text = "事務所費\n  1  コピー代   500   R5/6/1   株式会社テスト   東京都\n  2  謝礼   30,000   R5/6/2   会田花子   東京都\n"
        rows = pf.parse_lines(text, {"sha256": "x", "年分": "2023"})
        self.assertEqual([(r["金額"], r["相手方種別"]) for r in rows], [("500", "法人その他の団体"), ("30000", "個人")])

    def test_kind_mismatch_is_not_agreed(self):
        a = [{"sha256": "x", "区分": "支出", "相手方種別": "法人その他の団体", "相手方": "会田花子", "金額": "1", "年月日": "2023-01-01"}]
        b = [{"sha256": "x", "区分": "支出", "相手方種別": "個人", "相手方": "会田花子", "金額": "1", "年月日": "2023-01-01"}]
        agreed, disagreed = pf.compare(a, b)
        self.assertEqual((len(agreed), len(disagreed)), (0, 2))

    def test_index_keeps_rows_missing_from_this_crawl(self):
        old = [{"PDF_URL": "a", "団体名": "A会"}, {"PDF_URL": "b", "団体名": "B会"}, {"PDF_URL": "", "リンク文字": "取得失敗"}]
        new = [{"PDF_URL": "a", "団体名": "A会（新）"}]
        self.assertEqual([r["団体名"] for r in pf.merge_index(old, new)], ["A会（新）", "B会"])

    def test_labor_unions_are_not_industry_groups(self):
        self.assertEqual(pf.org_type("全国テスト労働組合連合会", "政治団体"), "労働組合")
        self.assertEqual(pf.org_type("日本テスト業協同組合", "政治団体"), "業界団体")

    def test_same_person_named_and_hidden_years_count_once(self):
        key = pf.payee_key({"相手方": "佐藤花子", "相手方種別": "個人"})
        rows = [{"人物ID": "x", "年分": y, "区分": "支出", "費目": "人件費", "相手方": name, "支払先キー": key, "金額": "500000", "報告団体": "会"}
                for y, name in (("2020", pf.INDIVIDUAL), ("2021", pf.INDIVIDUAL), ("2023", "佐藤花子"))]
        rows.append({"人物ID": "x", "年分": "2023", "区分": "支出", "費目": "事務所費", "相手方": "株式会社A", "支払先キー": "株式会社A", "金額": "500000", "報告団体": "会"})
        got = pf.spending_by_member(rows)["x"]["偏り"]
        self.assertEqual(got["上位1の割合"], 0.75)
        self.assertTrue(any("佐藤花子 に3年分" in r for r in got["理由"]))

    def test_hidden_donors_are_matched_by_private_key(self):
        a = pf.parse_lines("(1) 個人からの寄附\n  1  試験太郎   100,000   R5/3/1   東京都\n", {"sha256": "x"})
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "x.json").write_text(json.dumps([{"区分": "受けた寄附", "相手方": "試験花子", "相手方種別": "個人", "金額": 100000, "年月日": "2023-03-01", "頁": 1}]), encoding="utf-8")
            b = pf.load_line_b(Path(tmp), {"x": {"sha256": "x"}})
        self.assertEqual(a[0]["相手方"], pf.INDIVIDUAL)
        self.assertNotIn("試験", a[0]["照合キー"])
        agreed, disagreed = pf.compare(a, b)
        self.assertEqual((len(agreed), len(disagreed)), (0, 2))

    def test_payee_names_with_single_spaces_are_kept_whole(self):
        rows = pf.parse_lines("事務所費\n  1  家賃   10,000   R5/6/1   株式会社 テスト   東京都\n", {"sha256": "x"})
        self.assertEqual(rows[0]["相手方"], "株式会社 テスト")

    def test_untried_pdfs_come_before_failed_ones(self):
        index = [{"PDF_URL": "https://e.example/a.pdf"}, {"PDF_URL": "https://e.example/b.pdf"}]
        manifest = [{"PDF_URL": "https://e.example/a.pdf", "状態": "失敗：x"}]
        tried = []
        def get(url):
            tried.append(url)
            raise OSError("x")
        pf.download(index, manifest, wait=0, limit=1, get_bytes=get)
        self.assertEqual(tried, ["https://e.example/b.pdf"])

    def test_line_b_expense_item_is_required_for_spending(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "x.json").write_text(json.dumps([
                {"区分": "支出", "費目": "事務所費", "相手方": "株式会社A", "相手方種別": "法人その他の団体", "金額": 1, "年月日": "2023-01-01", "頁": 1},
                {"区分": "支出", "相手方": "株式会社B", "相手方種別": "法人その他の団体", "金額": 1, "年月日": "2023-01-01", "頁": 1},
                {"区分": "出した寄附", "相手方": "C党支部", "相手方種別": "法人その他の団体", "金額": 1, "年月日": "2023-01-01", "頁": 1}]), encoding="utf-8")
            rows = pf.load_line_b(Path(tmp), {})
        self.assertEqual([r["費目"] for r in rows], ["事務所費", "入力不備：費目「」", "寄附・交付金"])

    def test_download_saves_progress(self):
        index = [{"PDF_URL": f"https://e.example/{i}.pdf"} for i in range(3)]
        saved = []
        def get(url):
            raise OSError("x")
        pf.download(index, [], wait=0, get_bytes=get, save=lambda rows: saved.append(len(rows)), save_every=2)
        self.assertEqual(saved, [1])

    def test_keep_image_stores_only_pdfs_without_text(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = [{"PDF_URL": "https://a.example/text.pdf"}, {"PDF_URL": "https://b.example/scan.pdf"}]
            texts = {b"T": ("あ" * 200 + "\f", 1), b"S": ("", 1)}
            with mock.patch.object(pf, "WORK", root / "work"), \
                 mock.patch.object(pf, "pdf_text", side_effect=lambda path: texts[path.read_bytes()]):
                out = pf.download(index, [], storage=root / "store", wait=0, keep="image", text_dir=root / "text",
                                  get_bytes=lambda url: b"T" if "text" in url else b"S", workers=2,
                                  free_bytes=lambda path: 10 ** 12)
            got = {m["PDF_URL"].split("/")[-1]: m for m in out}
            self.assertEqual({k: v["状態"] for k, v in got.items()}, {"text.pdf": "取得済み", "scan.pdf": "取得済み"})
            self.assertEqual(got["text.pdf"]["material_id"], "")
            self.assertNotEqual(got["scan.pdf"]["material_id"], "")
            self.assertTrue((root / "text" / f"{got['text.pdf']['sha256']}.txt").exists())
            self.assertEqual(list((root / "work" / "download").iterdir()), [])

    def test_low_disk_marks_failure_and_stops(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = [{"PDF_URL": f"https://a.example/{i}.pdf"} for i in range(3)]
            with mock.patch.object(pf, "WORK", root / "work"):
                out = pf.download(index, [], storage=root / "store", wait=0, keep="all",
                                  get_bytes=lambda url: b"S", free_bytes=lambda path: 0)
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0]["状態"].startswith("失敗"))
            self.assertEqual(list((root / "work" / "download").iterdir()), [])

    def test_same_pdf_from_two_hosts_at_once(self):
        import threading
        from unittest import mock
        barrier = threading.Barrier(2)
        def get(url):
            barrier.wait(timeout=5)  # 2本の取得を同時に走らせる
            return b"SAME"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = [{"PDF_URL": "https://a.example/x.pdf"}, {"PDF_URL": "https://b.example/x.pdf"}]
            with mock.patch.object(pf, "WORK", root / "work"):
                out = pf.download(index, [], storage=root / "store", wait=0, keep="all", get_bytes=get, workers=2,
                                  free_bytes=lambda path: 10 ** 12)
            self.assertEqual([m["状態"] for m in out], ["取得済み", "取得済み"])
            self.assertEqual(list((root / "work" / "download").iterdir()), [])

    def test_page_forms_reads_marks_and_fills_gaps(self):
        import types
        marks = iter(["", "（その2）", "(その７)寄附の内訳", "読めない", "（そ の 14）", "政治資金監査報告書", "(別紙)\n様式 注釈番号", ""])
        def run(args, **kwargs):
            if args[0] == "pdfinfo":
                return types.SimpleNamespace(args=args, returncode=0, stdout="Title: x\nPages:          8\n")
            if args[0] == "pdftoppm":
                return types.SimpleNamespace(args=args, returncode=0, stdout=b"png")
            return types.SimpleNamespace(args=args, returncode=0, stdout=next(marks).encode("utf-8"))
        self.assertEqual(pf.page_forms(Path("x.pdf"), run), ["1", "2", "7", "7", "14", "監査", "別紙", "別紙"])

    def test_ocr_failure_is_not_saved_as_classified(self):
        import types
        def run(args, **kwargs):
            if args[0] == "pdfinfo":
                return types.SimpleNamespace(args=args, returncode=0, stdout="Pages: 2\n")
            return types.SimpleNamespace(args=args, returncode=1, stdout=b"")
        with self.assertRaises(pf.subprocess.SubprocessError):
            pf.page_forms(Path("x.pdf"), run)

    def test_incomplete_ai_rows_are_never_adopted(self):
        base = {"sha256": "s", "区分": "支出", "費目": "事務所費", "相手方": "株式会社X", "相手方種別": "法人その他の団体",
                "金額": "100", "年月日": "2024-01-01", "頁": "1"}
        for broken in ({**base, "金額": ""}, {**base, "年月日": ""},
                       {**base, "区分": "受けた寄附", "費目": "", "相手方": "山田太郎", "相手方種別": ""}):
            agreed, _ = pf.compare([broken], [dict(broken)])
            self.assertEqual(agreed, [])
            agreed, _ = pf.tie_break([], [{**broken, "照合": "Aだけ"}], [dict(broken)])
            self.assertEqual(agreed, [])
        agreed, _ = pf.compare([{**base, "頁": ""}], [{**base, "頁": ""}])
        self.assertEqual(agreed, [])
        # パーティー対価の支払者は年月日が無くてよい
        party = {**base, "区分": "パーティー対価", "費目": "", "年月日": ""}
        self.assertEqual(len(pf.compare([party], [dict(party)])[0]), 1)

    def test_ai_reader_rows_are_normalized_like_line_a(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "s1.json").write_text(json.dumps({"関係議員名": "", "行": [
                {"区分": "支出", "費目": "事務所費", "相手方": "株式会社テスト", "相手方種別": "個人", "金額": "16,500", "年月日": "R6/6/26", "頁": 5},
                {"区分": "受けた寄附", "相手方": "現代日本研究会", "相手方種別": "政治団体", "金額": 60000, "年月日": "令和6年7月1日", "頁": 3}]}), encoding="utf-8")
            rows = pf.load_line_b(Path(tmp), {}, line="A")
        self.assertEqual([(r["系統"], r["相手方種別"], r["金額"], r["年月日"]) for r in rows],
                         [("A", "法人その他の団体", "16500", "2024-06-26"), ("A", "政治団体", "60000", "2024-07-01")])

    def test_reader_individual_is_kept_unless_name_shows_legal_entity(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "s1.json").write_text(json.dumps({"行": [
                {"区分": "パーティー対価", "相手方": "山田商店", "相手方種別": "個人", "金額": 300000, "頁": 9},
                {"区分": "パーティー対価", "相手方": "山田商店", "金額": 300000, "頁": 9}]}), encoding="utf-8")
            rows = pf.load_line_b(Path(tmp), {}, line="A")
        self.assertEqual([(r["相手方種別"], r["相手方"]) for r in rows], [("個人", pf.INDIVIDUAL), ("法人その他の団体", "山田商店")])

    def test_keep_none_text_failure_is_retried(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(pf, "WORK", root / "work"), mock.patch.object(pf, "pdf_text", return_value=None):
                out = pf.download([{"PDF_URL": "https://a.example/x.pdf"}], [], storage=root / "store", wait=0, keep="none",
                                  text_dir=root / "text", get_bytes=lambda url: b"X", free_bytes=lambda path: 10 ** 12)
            self.assertTrue(out[0]["状態"].startswith("失敗"))

    def test_keep_none_image_pdf_is_retried(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(pf, "WORK", root / "work"), mock.patch.object(pf, "pdf_text", return_value=("\f", 1)), \
                 mock.patch.object(pf, "classify_text", return_value="文字なし"):
                out = pf.download([{"PDF_URL": "https://a.example/x.pdf"}], [], storage=root / "store", wait=0, keep="none",
                                  text_dir=root / "text", get_bytes=lambda url: b"X", free_bytes=lambda path: 10 ** 12)
            self.assertTrue(out[0]["状態"].startswith("失敗"))

    def test_roster_failure_keeps_previous_table(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp, "member-groups.csv")
            table.write_text("氏名\n前回\n", encoding="utf-8")
            with mock.patch.object(pf, "MEMBER_GROUPS", table), mock.patch.object(pf, "roster_rows", side_effect=OSError("403")), \
                 mock.patch.object(pf, "SOURCES", Path(tmp, "none.csv")):
                self.assertEqual(pf.main(["roster"]), 0)
            self.assertEqual(table.read_text(encoding="utf-8"), "氏名\n前回\n")

    def test_pages_to_read_uses_range_not_each_mark(self):
        forms = ["1", "2", "6", "7", "7", "13", "14", "13", "14", "15", "17", "20"]
        self.assertEqual(pf.pages_to_read(forms), [1, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(pf.pages_to_read(["1", "2", "17"]), [1])
        # 末尾の別紙（「*1」の本当の名前の一覧）は読み、監査報告書は読まない
        self.assertEqual(pf.pages_to_read(["1", "7", "14", "17", "20", "監査", "別紙", "別紙"]), [1, 2, 3, 7, 8])
        # 途中の頁を 19 と読み違えても、その後ろの内訳（15）まで読む
        self.assertEqual(pf.pages_to_read(["1", "7", "14", "19", "14", "15", "17", "20"]), [1, 2, 3, 4, 5, 6])

    def test_reader_name_folds_spelling_variants(self):
        self.assertEqual(pf.reader_name("髙石会計事務所　吉葉無線電機㈱"), "高石会計事務所 吉葉無線電機(株)")
        self.assertEqual(pf.counterpart_kind(pf.reader_name("吉葉無線電機㈱"), ""), "法人その他の団体")

    def test_invalid_expense_item_never_agrees_and_variants_match(self):
        base = {"sha256": "s", "区分": "支出", "相手方種別": "法人その他の団体", "金額": "100", "年月日": "2024-01-01", "頁": "1"}
        bad = {**base, "費目": "入力不備：費目「」", "相手方": "株式会社X"}
        agreed, disagreed = pf.compare([bad], [dict(bad)])
        self.assertEqual((len(agreed), len(disagreed)), (0, 2))
        a = {**base, "費目": "事務所費", "相手方": "髙橋事務所"}
        agreed, _ = pf.compare([a], [{**a, "相手方": "高橋事務所"}])
        self.assertEqual(len(agreed), 1)

    def test_private_key_ignores_spelling_variants(self):
        self.assertEqual(pf.private_key("髙橋 太郎"), pf.private_key("高橋太郎"))

    def test_tie_break_takes_rows_where_c_agrees_with_one_side(self):
        base = {"sha256": "s", "区分": "支出", "費目": "事務所費", "相手方種別": "法人その他の団体", "年月日": "2024-01-01", "頁": "5"}
        a = {**base, "相手方": "大槻デザイニング株式会社", "金額": "100", "照合": "Aだけ"}
        b = {**base, "相手方": "大機デザイニング株式会社", "金額": "100", "照合": "Bだけ"}
        other_page = {**base, "頁": "9", "相手方": "株式会社Z", "金額": "5", "照合": "Aだけ"}
        c = [{**base, "相手方": "大槻デザイニング株式会社", "金額": "100"}, {**base, "頁": "9", "相手方": "株式会社Z", "金額": "5"}]
        agreed, disagreed = pf.tie_break([], [a, b, other_page], c)
        self.assertEqual([(r["相手方"], r["照合"]) for r in agreed], [("大槻デザイニング株式会社", "A・C一致"), ("株式会社Z", "A・C一致")])
        self.assertEqual([r["相手方"] for r in disagreed], ["大機デザイニング株式会社"])

    def test_tie_break_does_not_reuse_c_for_rows_already_agreed(self):
        row = {"sha256": "s", "区分": "支出", "費目": "事務所費", "相手方種別": "法人その他の団体", "年月日": "2024-01-01", "頁": "5",
               "相手方": "株式会社X", "金額": "100"}
        agreed, disagreed = pf.compare([dict(row), dict(row)], [dict(row)])
        agreed, disagreed = pf.tie_break(agreed, disagreed, [dict(row)])
        self.assertEqual((len(agreed), len(disagreed)), (1, 1))

    def test_manifest_meta_gives_source_without_line_a_rows(self):
        manifest = [{"PDF_URL": "https://example.jp/a.pdf", "sha256": "s1"}, {"PDF_URL": "https://example.jp/b.pdf", "sha256": "s1"}]
        index = [{"PDF_URL": "https://example.jp/a.pdf", "年分": "2024", "団体名": "テスト会"}]
        meta = pf.manifest_meta(manifest, index)
        self.assertEqual(meta["s1"], {"sha256": "s1", "PDF_URL": "https://example.jp/a.pdf", "年分": "2024", "報告団体": "テスト会"})
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "s1.json").write_text(json.dumps({"行": [{"区分": "支出", "費目": "事務所費", "相手方": "株式会社X", "金額": 100, "頁": 5}]}), encoding="utf-8")
            row = pf.load_line_b(Path(tmp), meta)[0]
        self.assertEqual((row["PDF_URL"], row["年分"], row["報告団体"]), ("https://example.jp/a.pdf", "2024", "テスト会"))

    def test_year_prefers_nenbun_over_publication_date(self):
        self.assertEqual(pf.year_of("令和7年11月28日公表（令和6年分）"), "2024")
        self.assertEqual(pf.year_of("令和7年11月28日公表"), "")
        self.assertEqual(pf.year_of("リンク", "令和5年 定期公表"), "2023")

    def test_upper_heading_year_survives_lower_heading(self):
        html = "<h2>令和5年分</h2><h3>資金管理団体</h3><a href='a.pdf'>テスト会（山田一郎）</a><h2>令和4年分</h2><a href='b.pdf'>別会</a>"
        links = pf.parse_links(html, "https://example.jp/x/")
        self.assertEqual(pf.year_of(links[0][1], links[0][2]), "2023")
        self.assertEqual(pf.group_kind(links[0][2], links[0][1]), "資金管理団体")
        self.assertEqual(pf.year_of(links[1][1], links[1][2]), "2022")
        self.assertNotIn("資金管理団体", links[1][2])

    def test_failed_text_extraction_is_not_cached(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = root / "store"
            pdf = storage / pf.TASK_ID / "m1" / "original.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF")
            manifest = [{"sha256": "abc", "状態": "取得済み", "material_id": "m1"}]
            failed = mock.Mock(returncode=1, stdout=b"")
            with mock.patch.object(pf.subprocess, "run", return_value=failed) as run:
                rows = pf.extract(manifest, root / "text", storage=storage)
                pf.extract(manifest, root / "text", storage=storage)
            self.assertEqual(rows[0]["状態"], "文字抽出の失敗")
            self.assertEqual(run.call_count, 2)
            self.assertFalse((root / "text" / "abc.txt").exists())

    def test_monthly_skip_still_rebuilds_offline_outputs(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            called = []
            with mock.patch.object(pf, "due", return_value=False), \
                 mock.patch.object(pf, "LAST_FETCH", Path(tmp) / "last.txt"), \
                 mock.patch.object(pf, "crawl", side_effect=AssertionError("通信してはいけない")), \
                 mock.patch.object(pf, "download", side_effect=AssertionError("通信してはいけない")), \
                 mock.patch.object(pf, "DERIVED", Path(tmp)), \
                 mock.patch.object(pf, "link", side_effect=lambda *a, **k: called.append("link") or []):
                (Path(tmp) / "last.txt").write_text("2026-10-20\n", encoding="utf-8")
                self.assertEqual(pf.main(["link", "--monthly"]), 0)
            self.assertEqual(called, ["link"])

    def test_hidden_payees_are_not_merged_in_top_payees(self):
        base = {"人物ID": "x", "関係議員名": "山田一郎", "区分": "支出", "費目": "人件費", "年分": "2019", "報告団体": "会", "相手方": "（個人）", "PDF_URL": "u"}
        rows = [{**base, "金額": "600000", "支払先キー": "個人aaaa"}, {**base, "金額": "400000", "支払先キー": "個人bbbb"}]
        top = pf.spending_by_member(rows)["x"]["主な支払先"]
        self.assertEqual([t["金額"] for t in top], [600000, 400000])
        self.assertNotEqual(top[0]["支払先"], top[1]["支払先"])

    def test_donor_name_is_split_from_address_columns(self):
        text = "(2) 法人その他の団体からの寄附\n  1  株式会社テスト   東京都港区   代表太郎   500,000   R5/4/10\n"
        rows = pf.parse_lines(text, {"sha256": "x"})
        self.assertEqual([r["相手方"] for r in rows], ["株式会社テスト"])

    def test_text_classification(self):
        self.assertEqual(pf.classify_text("あ" * 200, 2), "文字あり")
        self.assertEqual(pf.classify_text("あ" * 20, 2), "画像（OCR待ち）")

    def test_roster_table_carries_member_and_fixes_spilled_names(self):
        import sys
        import types

        table = [
            ["氏名", "衆・参", "選挙区", "総務大臣届出", None, "都道府県選挙管理委員会届出", None, None],
            [None, None, None, "団体名", "区分", "届出先選管", "団体名", "区分"],
            ["【あ】", "", "", "", "", "", "", ""],
            ["試験 一郎\n（試驗 一郎）", "衆", "東京１", "試験会", "２", "東京都", "試験一郎後援会（代表者 山田", "太郎）１・２"],
            [None, None, None, "", "", "東京都", "試験党東京都第一支部", "１"],
        ]
        page = types.SimpleNamespace(extract_tables=lambda: [table])
        pdf = types.SimpleNamespace(pages=[page], __enter__=None)

        class Opened:
            def __enter__(self):
                return pdf

            def __exit__(self, *exc):
                return False

        fake = types.ModuleType("pdfplumber")
        fake.open = lambda path: Opened()
        saved = sys.modules.get("pdfplumber")
        sys.modules["pdfplumber"] = fake
        try:
            rows = pf.parse_roster(Path("x.pdf"), "国会議員関係政治団体", "試し")
        finally:
            if saved is None:
                sys.modules.pop("pdfplumber")
            else:
                sys.modules["pdfplumber"] = saved
        self.assertEqual([(r["氏名"], r["届出先"], r["団体名"], r["区分"]) for r in rows], [
            ("試験 一郎", "総務大臣", "試験会", "２"),
            ("試験 一郎", "東京都", "試験一郎後援会（代表者 山田太郎）", "１・２"),
            ("試験 一郎", "東京都", "試験党東京都第一支部", "１"),
        ])
        self.assertEqual(rows[0]["届出上の氏名"], "試驗 一郎")

    def test_member_comes_from_roster_only_when_one_member_matches(self):
        members = [
            {"氏名": "試験 一郎", "届出上の氏名": "", "届出先": "総務大臣", "団体名": "試験一郎後援会（代表者 和田昌夫）"},
            {"氏名": "試験一郎", "届出上の氏名": "", "届出先": "総務大臣", "団体名": "試験一郎後援会（代表者 試験一郎）"},
            {"氏名": "甲 太郎", "届出上の氏名": "", "届出先": "総務大臣", "団体名": "同名会"},
            {"氏名": "乙 次郎", "届出上の氏名": "", "届出先": "総務大臣", "団体名": "同名会"},
            {"氏名": "丙 三郎", "届出上の氏名": "", "届出先": "東京都", "団体名": "丙会"},
        ]
        lookup = pf.roster_lookup(members)
        soumu = "総務省（中央分・定期公表）"
        # 索引と名簿で代表者名の字が違っても（晶／昌）、かっこ書きを落として同じ議員に決まる
        self.assertEqual(pf.member_of({"出典": soumu, "団体名": "試験一郎後援会(和田 晶夫)"}, lookup), "試験 一郎")
        self.assertEqual(pf.member_of({"出典": soumu, "団体名": "同名会"}, lookup), "")
        self.assertEqual(pf.member_of({"出典": soumu, "団体名": "丙会"}, lookup), "")
        self.assertEqual(pf.member_of({"出典": "東京都", "団体名": "丙会"}, lookup), "丙 三郎")
        self.assertEqual(pf.member_of({"出典": soumu, "団体名": "同名会", "関係議員名": "甲 太郎"}, lookup), "甲 太郎")


if __name__ == "__main__":
    unittest.main()
