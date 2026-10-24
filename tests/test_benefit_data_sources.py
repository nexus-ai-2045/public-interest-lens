import unittest

from scripts import fetch_fsa_kasikin as f
from scripts import fetch_kokusen_pionet as k
from scripts import fetch_law_purposes as lp
from scripts import fetch_sesc_actions as s


class LawPurposesTests(unittest.TestCase):
    def test_target_ids_and_relation(self):
        url = ("https://laws.e-gov.go.jp/api/2/laws?law_title=x;https://laws.e-gov.go.jp/api/2/law_revisions/346AC0000000034;"
               "https://laws.e-gov.go.jp/api/2/law_file/xml/346AC0000000034;https://laws.e-gov.go.jp/api/2/law_revisions/411AC0100000004")
        self.assertEqual(lp.target_ids(url), ["346AC0000000034", "411AC0100000004"])
        self.assertEqual(lp.target_ids(""), [])
        self.assertEqual(lp.relation("預金保険法の一部を改正する法律案"), "改正対象の法令")
        self.assertEqual(lp.relation("国際観光旅客税法案"), "新規の法令（自身）")

    def test_article1_text(self):
        tree = {"tag": "Law", "attr": {}, "children": [{"tag": "MainProvision", "attr": {}, "children": [
            {"tag": "Article", "attr": {"Num": "1"}, "children": [
                {"tag": "ArticleCaption", "attr": {}, "children": ["（目的）"]},
                {"tag": "ArticleTitle", "attr": {}, "children": ["第一条"]},
                {"tag": "Paragraph", "attr": {"Num": "1"}, "children": [
                    {"tag": "ParagraphSentence", "attr": {}, "children": [
                        {"tag": "Sentence", "attr": {}, "children": ["この法律は、", {"tag": "Ruby", "attr": {}, "children": [
                            "目的", {"tag": "Rt", "attr": {}, "children": ["もくてき"]}]}, "とする。"]}]},
                    {"tag": "Item", "attr": {"Num": "1"}, "children": [
                        {"tag": "ItemTitle", "attr": {}, "children": ["一"]},
                        {"tag": "ItemSentence", "attr": {}, "children": ["甲"]}]}]}]},
            {"tag": "Article", "attr": {"Num": "2"}, "children": []}]}]}
        art = lp.find_article1(tree)
        self.assertEqual(art["attr"]["Num"], "1")
        self.assertEqual(lp.article_text(art), "（目的）\n第一条　この法律は、目的とする。\n一甲")
        self.assertIsNone(lp.find_article1({"tag": "Law", "attr": {}, "children": []}))

    def test_pick_revision(self):
        own = ("平成", 28, 69)
        revs = {"revisions": [
            {"law_revision_id": "A_20160401_426AC0000000069", "amendment_enforcement_date": "2016-04-01",
             "amendment_law_num": "平成二十六年法律第六十九号"},
            {"law_revision_id": "A_20160401_999", "amendment_enforcement_date": "2016-04-02",
             "amendment_law_num": "平成二十八年法律第六十九号"},
            {"law_revision_id": "A_20170401", "amendment_enforcement_date": "2017-04-01", "amendment_law_num": None},
        ]}
        self.assertEqual(lp.pick_revision(revs, ("平成", 26, 69), "2016-04-01")["law_revision_id"], "A_20160401_426AC0000000069")
        self.assertIsNone(lp.pick_revision(revs, own, "2016-04-01"))  # 法令番号が合わない
        self.assertEqual(lp.pick_revision(revs, own, "2017-04-01")["law_revision_id"], "A_20170401")  # 初めの版


class KokusenTests(unittest.TestCase):
    def test_table1(self):
        text = "表１ 消費生活相談の年度別総件数\n年度 件数 年度 件数 年度 件数\n1984 48,550 1995 274,076 2006 1,113,146\n" \
               "1994 234,022 2005 1,303,588 累積 19,922,338\n9 消費生活年報 2016\n1990 1,000 2000 2,000"
        got = k.parse_table1(text)
        self.assertEqual(got[1984], 48550)
        self.assertEqual(got[2006], 1113146)
        self.assertEqual(got[2005], 1303588)
        self.assertNotIn(1990, got)  # 表の終わり以降は読まない

    def test_fig_amounts(self):
        text = "図８ 年度別にみた契約購入金額および既支払金額の推移\n年度\n135 5,618\n2012\n57 2,075\n126 5,749\n2013\n52 2,115\n" \
               "【相談全体での平均金額】\n"
        got = k.parse_fig_amounts(text)
        self.assertEqual(got[2012], {"契約購入金額の平均": 135, "契約購入金額の合計": 5618, "既支払金額の平均": 57, "既支払金額の合計": 2075})
        self.assertEqual(got[2013]["既支払金額の合計"], 2115)

    def test_features_both_layouts(self):
        text = "\n".join([
            "表10−１ 2021年度の上位商品・役務等別にみた相談の特徴",
            "男性 9,248 50歳以上、女性中心 35,805 通信販売 （89.7）",
            "2 化粧品 44,608 53.6",
            "女性 34,685 給与生活者 25,440 マルチ取引 （2.5）",
            "男性 11,249 20歳以上 2,208,949 店舗購入 （43.6）",
            "9 フリーローン・サラ金 18,065 51.5",
            "女性 6,296 給与生活者、無職 268,566 通信販売 （5.0）",
            "娯楽等情報配信サービス 男性 3,611 20歳代 245,069 通信販売 （82.2）",
            "18 7,251 44.8",
            "その他※ 女性 3,412 給与生活者 102,540 電話勧誘販売 （6.7）",
            "（注１）x",
            "表10−２ 2021年度の別",
        ])
        rows, skipped = k.parse_features(text)
        got = {r["商品・役務等"]: r for r in rows[2021]}
        self.assertEqual(got["フリーローン・サラ金"]["平均既支払金額（円）"], 268566)
        self.assertEqual(got["化粧品"]["件数"], 44608)
        self.assertEqual(len(rows[2021]), 2)  # 名前が折り返した順位18は採らない
        self.assertIn(18, skipped[2021])
        old = "\n".join([
            "表10−１ 2015年度の契約当事者年代別",  # 別の表は読まない
            "表16−１ 2015年度の上位商品・役務別にみた相談の特徴",
            "男性 20,227 48.3 30歳代〜60歳代 2,033,285 店舗購入 （55.7）",
            "6 フリーローン・サラ金 32,046",
            "女性 10,872 50.5 給与生活者 368,117 通信販売 （9.5）",
        ])
        rows2, _ = k.parse_features(old)
        self.assertEqual(rows2[2015][0]["平均既支払金額（円）"], 368117)

    def test_features_rejects_count_mismatch(self):
        text = "表10−１ 2021年度の上位商品・役務等別にみた相談の特徴\n男性 900 x 1 通信販売 （1.0）\n1 テスト 100 50.0\n女性 900 給与 5 店舗 （1.0）\n"
        rows, _ = k.parse_features(text)
        self.assertEqual(rows[2021], [])  # 男性＋女性が件数を超える

    def test_narrative(self):
        html = "<p>契約購入金額は、合計金額が4,776億円、平均金額が88万円、既支払金額は合計金額が2,087億円、平均金額が50万円であり</p>"
        self.assertEqual(k.parse_narrative(html)["既支払金額の平均"], 50)
        self.assertIsNone(k.parse_narrative("<p>無関係</p>"))


class FsaTests(unittest.TestCase):
    def test_years(self):
        self.assertEqual(f.era_year("平成16年3月末"), ("平成", 2004))
        self.assertEqual(f.era_year("令和\n元年度"), ("令和", 2019))
        self.assertEqual(f.era_year("令和２年度"), ("令和", 2020))
        self.assertEqual(f.era_year("12年3月末", "平成"), ("平成", 2000))
        self.assertIsNone(f.era_year("12年3月末"))
        self.assertEqual(f.short_year("Ｈ元年"), 1989)
        self.assertEqual(f.short_year("R7年"), 2025)
        self.assertIsNone(f.short_year("R7.9"))

    def test_year_blocks(self):
        grid = [
            [None, None, "平成16年3月末", "平成17年3月末"],
            [None, "財務局登録", 839, 762],
            [None, "合　計", 23708, 18005],
            [None, None, "平成18年3月末"],
            [None, "財務局登録", 702],
            [None, "（注）x", None],
        ]
        got = f.parse_year_blocks(grid)
        self.assertIn(("財務局登録", 2004, 839), got)
        self.assertIn(("合計", 2005, 18005), got)
        self.assertIn(("財務局登録", 2006, 702), got)
        self.assertEqual(len(got), 5)

    def test_gyotai_skips_percent_rows(self):
        header = ["(2)", "平成11年\n3月末"] + [f"{y}年3月末" for y in range(12, 32)] + ["令和2年\n3月末", "3年3月末"]
        grid = [header,
                ["消費者向無担保貸金業者", 89845, 95948] + [1] * 19 + [5, 6],
                [None, 20.1, 6.8] + [0] * 21,
                ["合　計", 545309, 476376] + [2] * 19 + [7, 8]]
        got = f.parse_gyotai(grid)
        d = {(a, y): v for a, y, v in got}
        self.assertEqual(d[("消費者向無担保貸金業者", 1999)], 89845)
        self.assertEqual(d[("消費者向無担保貸金業者", 2019)], 1)   # 平成31年
        self.assertEqual(d[("消費者向無担保貸金業者", 2020)], 5)   # 令和2年
        self.assertEqual(d[("合計", 2021)], 8)
        self.assertEqual(len([1 for a, _, _ in got if a == ""]), 0)

    def test_long_term(self):
        grid = [[None, None, "S59年", "H元年", "H10年", "H20年", "R7年", "R7.9"],
                [None, "都道府県登録", 18882, 36898, 1, 2, 1219, 1221],
                [None, "合　計", 19501, 38048, 3, 4, 1473, 1471]]
        got = f.parse_long_term(grid)
        self.assertIn(("都道府県登録", 1984, 18882), got)
        self.assertIn(("合計", 1989, 38048), got)
        self.assertIn(("合計", 2025, 1473), got)
        self.assertEqual(len(got), 10)  # R7.9 は読まない

    def test_year_columns_drops_partial_year(self):
        years = [None, None, "令和元年度", None, None, None, None, "令和２年度", None]
        subs = [None, None, "4～6月", "7～9月", "10～12月", "1～3月", "計", "4～6月", "計"]
        self.assertEqual(f.year_columns(years, subs), [(6, 2019)])
        years2 = [None, None, "平成26年度", "平成27年度"]
        subs2 = [None, None, "計", "計"]
        self.assertEqual(f.year_columns(years2, subs2), [(2, 2014), (3, 2015)])

    def test_complaints_groups(self):
        grid = [
            [None, "区分"],
            [None, None, None, "令和元年度", "令和２年度", "令和３年度"],
            [None, None, None, "計", "計", "計"],
            [None, "苦情等受付件数", None, 4768, 4747, 1],
            [None, None, "うち無登録業者に係るもの", 998, 1171, 1],
            [None, "苦情の内容", "取立て行為", 69, 67, 1],
            [None, "苦情計", None, 516, 398, 1],
            [None, "相談・照会の内容", "金利", 50, 39, 1],
            [None, "（注）x"],
        ]
        got = {(a, y): v for a, y, v in f.parse_complaints(grid)}
        self.assertEqual(got[("苦情等受付件数", 2019)], 4768)
        self.assertEqual(got[("うち無登録業者に係るもの", 2020)], 1171)
        self.assertEqual(got[("苦情の内容/取立て行為", 2019)], 69)
        self.assertEqual(got[("相談・照会の内容/金利", 2020)], 39)
        self.assertEqual(got[("苦情計", 2020)], 398)

    def test_complaints_by_office(self):
        grid = [
            [None, "区分", None, "令和２年度", None, None, None, "令和３年度", None],
            [None, None, None, "金融庁", "財務局", "都道府県", "計", "金融庁", "計"],
            [None, "苦情等受付件数", None, 1223, 1641, 1883, 4747, 1, 2],
        ]
        got = {(a, y): v for a, y, v in f.parse_complaints_by_office(grid)}
        self.assertEqual(got[("苦情等受付件数/財務局", 2020)], 1641)
        self.assertEqual(got[("苦情等受付件数/計", 2020)], 4747)

    def test_group_columns(self):
        subs = ["計", "計", "4～6月", "7～9月", "10～12月", "1～3月", "計", "4～6月", "計"]
        cols = f.group_columns([2007, 2008, 2009, 2010], subs)
        self.assertEqual(cols[0], (2007, "計"))
        self.assertEqual(cols[6], (2009, "計"))
        self.assertEqual(cols[8], (2010, "一部期間の計"))
        self.assertIsNone(f.group_columns([2007], ["計", "計"]))
        self.assertIsNone(f.group_columns([2007, 2008], ["計"]))

    PDF = "\n".join([
        "平成１９年度 平成２０年度 平成２１年度",
        "区 分",
        "計 計 4~6月 7~9月 10~12月 1~3月 計",
        "苦情等受付件数 100 90 10 20 30 40 100",
        "うち無登録業者に係るもの 50 40 5 5 5 5 20",
        "取立て行為 6 5 1 1 1 1 4",
        "苦 その他 4 3 1 1 1 1 4",
        "苦情計 10 8 2 2 2 2 8",
        "相 債務整理等 20 10 5 5 5 5 20",
        "相談・照会計 20 10 5 5 5 5 20",
        "（注）x",
    ])

    def test_complaints_pdf_with_verified_breakdown(self):
        got, note = f.parse_complaints_pdf(self.PDF)
        d = {(a, y): v for a, y, v in got}
        self.assertEqual(d[("苦情等受付件数", 2007)], 100)
        self.assertEqual(d[("苦情等受付件数", 2009)], 100)
        self.assertEqual(d[("苦情の内容/取立て行為", 2009)], 4)
        self.assertEqual(d[("相談・照会の内容/債務整理等", 2008)], 10)
        self.assertEqual(note, "")

    def test_complaints_pdf_breakdown_mismatch_keeps_totals_only(self):
        bad = self.PDF.replace("苦情計 10 8 2 2 2 2 8", "苦情計 11 8 2 2 2 2 8")
        got, note = f.parse_complaints_pdf(bad)
        labels = {a for a, _, _ in got}
        self.assertIn("苦情計", labels)
        self.assertNotIn("苦情の内容/取立て行為", labels)
        self.assertIn("一致しない", note)

    def test_long_term_pdf(self):
        hdr = " ".join(["Ｓ59年", "Ｓ60年"] + [f"Ｈ{i}年" for i in range(2, 10)] + ["H27.7"])
        text = hdr + "\n都道府県登録 18,882 44,607 " + " ".join(["1"] * 8) + " 9\n合 計 19,501 45,720 " + " ".join(["2"] * 8) + " 9\n"
        got = f.parse_long_term_pdf(text)
        d = {(a, y): v for a, y, v in got}
        self.assertEqual(d[("都道府県登録", 1984)], 18882)
        self.assertEqual(d[("合計", 1985)], 45720)
        self.assertNotIn(("合計", 2015), d)  # H27.7 は年として読まない
        self.assertEqual(f.parse_long_term_pdf("見出し無し"), [])


class SescTests(unittest.TestCase):
    TABLE = "\n".join([
        "附属資料 ３－３ 勧告等実施状況",
        "１．勧告実施件数一覧表",
        "（単位：件数）",
        "年 度 平成４ 令和 令和 令和 令和 令和",
        "合計",
        "区 分 ～令和元 ２ ３ ４ ５ ６",
        "勧告件数 1,131 29 20 26 33 38 1,277",
        "行政処分に関する勧告 584 5 2 5 8 9 613",
        "課徴金納付命令に関する勧告 543 24 17 21 25 28 658",
        "・ 注",
    ])

    def test_kankoku(self):
        fy, rows, why = s.parse_kankoku(self.TABLE)
        self.assertEqual(fy, 2024)
        self.assertEqual(rows["勧告件数"], (38, 1277))
        self.assertEqual(rows["課徴金納付命令に関する勧告"], (28, 658))
        self.assertEqual(why, "")

    def test_kankoku_rejects_bad_sum(self):
        fy, rows, why = s.parse_kankoku(self.TABLE.replace("1,277", "1,278"))
        self.assertNotIn("勧告件数", rows)

    def test_kankoku_ignores_toc_line(self):
        toc = "勧告実施件数一覧表 ········ 169\n"
        fy, rows, why = s.parse_kankoku(toc)
        self.assertEqual(rows, {})
        self.assertIn("無い", why)

    def test_kokuhatsu(self):
        text = "３．告発実施状況\n（１） 告発件数等一覧表\n年度\n令和元 令和２ 令和３ 令和４ 令和５ 令和６\n区分\n" \
               "告発件数 ３ ２ ８ ８ ４ ７\n告発人数 ９ ３ 24 17 11 ８\n"
        got, why = s.parse_kokuhatsu(text)
        d = {(a, y): v for a, y, v in got}
        self.assertEqual(d[("告発件数", 2019)], 3)
        self.assertEqual(d[("告発人数", 2021)], 24)
        self.assertEqual(d[("告発件数", 2024)], 7)
        self.assertEqual(why, "")

    def test_kokuhatsu_count_mismatch(self):
        text = "（１） 告発件数等一覧表\n令和元 令和２\n告発件数 ３ ２ ８\n"
        got, why = s.parse_kokuhatsu(text)
        self.assertEqual(got, [])

    def test_report_pages(self):
        html = '<a href="/sesc/reports/n_2024/n_2024.html">令和６年度「証券取引等監視委員会の活動状況」の公表について</a>' \
               '<a href="/sesc/houdou/others.html">年次公表等</a>'
        self.assertEqual([h for h, _ in s.report_pages(html)], ["/sesc/reports/n_2024/n_2024.html"])
        self.assertEqual(s.pdf_links('<a href="/a.pdf">附属資料編</a>'), [("/a.pdf", "附属資料編")])


if __name__ == "__main__":
    unittest.main()
