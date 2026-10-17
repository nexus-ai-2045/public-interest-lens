import unittest
import xml.etree.ElementTree as ET

from scripts import fetch_enforcement_fusoku as g

PUB = "1998-02-18"


class KanjiAndDateTests(unittest.TestCase):
    def test_kanji_num_additive_and_positional(self):
        self.assertEqual(g.kanji_num("二十五"), 25)
        self.assertEqual(g.kanji_num("一〇"), 10)
        self.assertEqual(g.kanji_num("二二"), 22)
        self.assertEqual(g.kanji_num("百十六"), 116)
        self.assertEqual(g.kanji_num("元"), 1)
        self.assertEqual(g.kanji_num("三十"), 30)
        with self.assertRaises(ValueError):
            g.kanji_num("あ")

    def test_find_dates(self):
        self.assertEqual(g.find_dates("平成十二年四月一日から施行する"), ["2000-04-01"])
        self.assertEqual(g.find_dates("昭和六十三年十二月三十一日"), ["1988-12-31"])
        self.assertEqual(g.find_dates("令和元年五月一日と令和二年四月一日"), ["2019-05-01", "2020-04-01"])
        self.assertEqual(g.find_dates("平成十二年二月三十日"), [])  # 存在しない日付

    def test_own_key_accepts_both_notations(self):
        self.assertEqual(g.own_key("平成十年法律第四号"), ("平成", 10, 4))
        self.assertEqual(g.own_key("平成一〇年二月一八日法律第四号"), ("平成", 10, 4))
        self.assertEqual(g.own_key("昭和五六年六月一日法律第六一号"), ("昭和", 56, 61))
        self.assertIsNone(g.own_key("政令第一号"))

    def test_add_period(self):
        self.assertEqual(g.add_period("2020-04-01", 0, 6, 0), "2020-10-01")
        self.assertEqual(g.add_period("2020-11-15", 1, 3, 0), "2022-02-15")
        self.assertEqual(g.add_period("2020-04-01", 0, 0, 20), "2020-04-21")
        self.assertIsNone(g.add_period("2020-08-31", 0, 1, 0))


class ParseKoryokuTests(unittest.TestCase):
    def test_explicit_date(self):
        r = g.parse_koryoku("この法律は、平成十年四月一日から施行する。", "", PUB)
        self.assertEqual((r["kind"], r["date"]), ("date", "1998-04-01"))

    def test_promulgation(self):
        r = g.parse_koryoku("この法律は、公布の日から施行する。", "", PUB)
        self.assertEqual((r["kind"], r["date"]), ("promulgation", PUB))

    def test_computed(self):
        r = g.parse_koryoku("この法律は、公布の日から起算して六月を経過した日から施行する。", "", PUB)
        self.assertEqual((r["kind"], r["date"]), ("computed", "1998-08-18"))
        r = g.parse_koryoku("この法律は、公布の日から起算して一年六月を経過した日から施行する。", "", PUB)
        self.assertEqual(r["date"], "1999-08-18")
        r = g.parse_koryoku("この法律は、公布の日から起算して二十日を経過した日から施行する。", "", PUB)
        self.assertEqual(r["date"], "1998-03-10")

    def test_decree_left_blank(self):
        r = g.parse_koryoku("この法律は、公布の日から起算して一年を超えない範囲内において政令で定める日から施行する。", "", PUB)
        self.assertEqual((r["kind"], r["date"]), ("decree", ""))
        self.assertIn(g.DECREE_NOTE, r["notes"])
        r = g.parse_koryoku("この法律は、政令で定める日から施行する。", "", PUB)
        self.assertEqual(r["kind"], "decree")

    def test_staged_main_and_others(self):
        r = g.parse_koryoku(
            "この法律は、平成十年四月一日から施行する。",
            "ただし、第三条の規定は平成十一年四月一日から、第五条の規定は公布の日から施行する。",
            PUB,
        )
        self.assertEqual(r["date"], "1998-04-01")
        self.assertEqual(r["others"], ["1999-04-01", PUB])

    def test_promulgation_with_proviso_decree(self):
        r = g.parse_koryoku("この法律は、公布の日から施行する。", "ただし、第二条の規定は、政令で定める日から施行する。", PUB)
        self.assertEqual(r["date"], PUB)
        self.assertTrue(any("政令で定める日" in n for n in r["notes"]))

    def test_items_has_no_main_date(self):
        r = g.parse_koryoku(
            "この法律は、次の各号に掲げる区分に従い、それぞれ当該各号に定める日から施行する。",
            "一　第一条の規定　公布の日　二　第二条の規定　平成十一年一月一日",
            PUB,
        )
        self.assertEqual((r["kind"], r["date"]), ("items", ""))

    def test_defined_term_parenthesis(self):
        r = g.parse_koryoku("この法律は、平成十四年四月一日（以下「施行日」という。）から施行し、施行日以後に適用する。", "", PUB)
        self.assertEqual(r["date"], "2002-04-01")

    def test_renamed_ids_are_well_formed(self):
        import re
        for ids in g.RENAMED.values():
            for i in ids:
                self.assertRegex(i, r"^\d{3}AC\d{10}$")

    def test_unparsed_is_not_guessed(self):
        r = g.parse_koryoku("この法律は、別に法律で定める日から施行する。", "", PUB)
        self.assertEqual((r["kind"], r["date"]), ("unparsed", ""))

    def test_impossible_date_is_not_used(self):
        r = g.parse_koryoku("この法律は、平成十年二月三十日から施行する。", "", PUB)
        self.assertEqual(r["date"], "")


XML = """<Law><SupplProvision AmendLawNum="平成一〇年二月一八日法律第四号" Extract="true">
<SupplProvisionLabel>附　則</SupplProvisionLabel>
<Article Num="1"><ArticleCaption>（施行期日）</ArticleCaption><ArticleTitle>第一条</ArticleTitle>
<Paragraph Num="1"><ParagraphNum/><ParagraphSentence><Sentence Function="main">この法律は、<Ruby>公布<Rt>こうふ</Rt></Ruby>の日から施行する。</Sentence>
<Sentence Function="proviso">ただし、次の各号は当該各号に定める日から施行する。</Sentence></ParagraphSentence>
<Item Num="1"><ItemTitle>一</ItemTitle><ItemSentence><Sentence>第二条　平成十一年四月一日</Sentence></ItemSentence></Item></Paragraph></Article>
</SupplProvision><SupplProvision AmendLawNum="平成一〇年三月三一日法律第二三号"><Article Num="1"><ArticleTitle>第一条</ArticleTitle>
<Paragraph><ParagraphSentence><Sentence>この法律は、公布の日から施行する。</Sentence></ParagraphSentence></Paragraph></Article></SupplProvision></Law>"""


class XmlTests(unittest.TestCase):
    def test_find_provision_and_article(self):
        root = ET.fromstring(XML)
        sps = g.find_provision(root, ("平成", 10, 4), is_new_law=False)
        self.assertEqual(len(sps), 1)
        art = g.koryoku_article(sps[0])
        self.assertEqual(art["body"], "この法律は、公布の日から施行する。")
        self.assertTrue(art["rest"].startswith("ただし、"))
        self.assertIn("平成十一年四月一日", art["rest"])
        self.assertTrue(art["quote"].startswith("第一条　この法律は、公布の日から"))
        self.assertNotIn("こうふ", art["quote"])
        r = g.parse_koryoku(art["body"], art["rest"], PUB)
        self.assertEqual((r["date"], r["others"]), (PUB, ["1999-04-01"]))

    def test_no_matching_provision(self):
        root = ET.fromstring(XML)
        self.assertEqual(g.find_provision(root, ("平成", 10, 99), is_new_law=False), [])

    def test_no_article_one_means_none(self):
        sp = ET.fromstring('<SupplProvision><Article Num="3"><ArticleTitle>第三条</ArticleTitle>'
                           "<Paragraph><ParagraphSentence><Sentence>なにか。</Sentence></ParagraphSentence></Paragraph></Article></SupplProvision>")
        self.assertIsNone(g.koryoku_article(sp))


class MergeTests(unittest.TestCase):
    def base(self):
        return {"id": "x", "題名": "甲法の一部を改正する法律案", "法令番号": "平成十年法律第四号", "公布日": PUB, "施行日": "",
                g.CAND_COL: "", "取得方法": "取得不可", "備考": "", "出典URL": "u", g.NEW_COL: ""}

    def test_fill_main(self):
        res = g.parse_koryoku("この法律は、公布の日から施行する。", "", PUB)
        row = g.merge_row(self.base(), {"results": [res], "quotes": ["q"], "urls": ["v"], "reason": ""})
        self.assertEqual(row["施行日"], PUB)
        self.assertEqual(row[g.NEW_COL], "q")
        self.assertEqual(row["出典URL"], "u;v")

    def test_decree_stays_blank(self):
        res = g.parse_koryoku("この法律は、政令で定める日から施行する。", "", PUB)
        row = g.merge_row(self.base(), {"results": [res], "quotes": ["q"], "urls": [], "reason": ""})
        self.assertEqual(row["施行日"], "")
        self.assertEqual(g.categorize(row), "decree")

    def test_disagreeing_targets_stay_blank(self):
        a = g.parse_koryoku("この法律は、平成十年四月一日から施行する。", "", PUB)
        b = g.parse_koryoku("この法律は、平成十年五月一日から施行する。", "", PUB)
        row = g.merge_row(self.base(), {"results": [a, b], "quotes": ["q1", "q2"], "urls": [], "reason": ""})
        self.assertEqual(row["施行日"], "")
        self.assertEqual(row[g.CAND_COL], "1998-04-01;1998-05-01")


if __name__ == "__main__":
    unittest.main()
