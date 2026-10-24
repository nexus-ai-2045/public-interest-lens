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
        a = [{"sha256": "x", "区分": "受けた寄附", "相手方": "株式会社A", "金額": "100", "年月日": "2023-01-01"},
             {"sha256": "x", "区分": "受けた寄附", "相手方": "B連盟", "金額": "200", "年月日": "2023-01-02"}]
        b = [{"sha256": "x", "区分": "受けた寄附", "相手方": "株式会社 A", "金額": "100", "年月日": "2023-01-01"},
             {"sha256": "x", "区分": "受けた寄附", "相手方": "B連盟", "金額": "250", "年月日": "2023-01-02"}]
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


if __name__ == "__main__":
    unittest.main()
