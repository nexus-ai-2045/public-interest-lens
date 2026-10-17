import unittest
import xml.etree.ElementTree as ET

from scripts import fetch_enforcement_decrees as d

NUM = "平成十年法律第八十八号"
PUB = "1998-06-03"


class DecreeStatementTests(unittest.TestCase):
    def test_main_statement(self):
        text = "この政令は、放送法の一部を改正する法律（平成十年法律第八十八号）の施行の日（平成十年十一月一日）から施行する。"
        got = d.decree_statements(text, NUM)
        self.assertEqual([(s["kind"], s["date"]) for s in got], [("main", "1998-11-01")])

    def test_main_statement_with_abbreviations(self):
        text = (
            "この政令は、放送法等の一部を改正する法律（平成二十二年法律第六十五号。以下「放送法等改正法」という。）"
            "の施行の日（平成二十三年六月三十日。以下「施行日」という。）から施行する。"
        )
        got = d.decree_statements(text, "平成二十二年法律第六十五号")
        self.assertEqual([(s["kind"], s["date"]) for s in got], [("main", "2011-06-30")])

    def test_part_and_combined_are_not_main(self):
        part = "この政令は、電気事業法の一部を改正する法律（平成二十五年法律第七十四号）附則第一条第二号に掲げる規定の施行の日（平成二十六年二月十七日）から施行する。"
        self.assertEqual(
            [(s["kind"], s["date"]) for s in d.decree_statements(part, "平成二十五年法律第七十四号")],
            [("part", "2014-02-17")],
        )
        combo = "この政令は、放送法等の一部を改正する法律（平成十九年法律第百三十六号）及び同法附則第一条第二号に掲げる規定の施行の日（平成二十年四月一日）から施行する。"
        self.assertEqual(
            [(s["kind"], s["date"]) for s in d.decree_statements(combo, "平成十九年法律第百三十六号")],
            [("combined", "2008-04-01")],
        )

    def test_rejects_other_numbers_dateless_and_proviso(self):
        text = "この政令は、放送法の一部を改正する法律（平成十年法律第八十八号）の施行の日（平成十年十一月一日）から施行する。"
        self.assertEqual(d.decree_statements(text, "平成十年法律第八十九号"), [])
        # 日付が無い
        self.assertEqual(d.decree_statements("この政令は、放送法の一部を改正する法律（平成十年法律第八十八号）の施行の日から施行する。", NUM), [])
        # ただし書の中の法律（この政令自体の施行日は別）
        proviso = "この政令は、平成十年十二月一日から施行する。ただし、第三条の規定は、放送法の一部を改正する法律（平成十年法律第八十八号）の施行の日（平成十年十一月一日）から施行する。"
        self.assertEqual(d.decree_statements(proviso, NUM), [])
        # 別の法律の番号も並ぶ文は採らない
        multi = "この政令は、甲法（平成九年法律第一号）及び乙法（平成十年法律第八十八号）の施行の日（平成十年十一月一日）から施行する。"
        self.assertEqual(d.decree_statements(multi, NUM), [])

    def test_enact_decree(self):
        enact = "内閣は、電気通信事業法の一部を改正する法律（平成十五年法律第百二十五号）の施行に伴い、この政令を制定する。"
        self.assertEqual(d.enact_subject(enact, "平成十五年法律第百二十五号"), "電気通信事業法の一部を改正する法律")
        self.assertIsNone(d.enact_subject("内閣は、甲法（平成十五年法律第百二十五号）の一部の施行に伴い、この政令を制定する。", "平成十五年法律第百二十五号"))
        suppl = "この政令は、電気通信事業法の一部を改正する法律の施行の日（平成十六年一月二十六日）から施行する。"
        got = d.enact_decree_dates(enact, suppl, "平成十五年法律第百二十五号")
        self.assertEqual([(s["kind"], s["date"]) for s in got], [("main", "2004-01-26")])
        self.assertEqual(d.enact_decree_dates(enact, "この政令は、別の法律の施行の日（平成十六年一月二十六日）から施行する。", "平成十五年法律第百二十五号"), [])

    def test_short_law_num(self):
        self.assertEqual(d.short_law_num("平成十年十月三十日政令第三百三十七号"), "平成十年政令第三百三十七号")
        self.assertEqual(d.short_law_num("昭和四十年政令第九十六号"), "昭和四十年政令第九十六号")
        self.assertEqual(d.short_law_num(None), "")
        # 位取り表記と十・百の表記を同じ形にそろえる
        self.assertEqual(d.short_law_num("平成一〇年政令第三五六号"), "平成十年政令第三百五十六号")
        self.assertEqual(d.short_law_num("令和元年六月七日政令第一号"), "令和元年政令第一号")


class WindowAndPickTests(unittest.TestCase):
    def test_window_end(self):
        self.assertEqual(d.window_end("この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。", "1998-06-03"), "1998-12-03")
        self.assertEqual(d.window_end("この法律は、公布の日から起算して十日を超えない範囲内において政令で定める日から施行する。", "1998-10-16"), "1998-10-26")
        self.assertEqual(d.window_end("この法律は、平成十四年三月三十一日までの間において政令で定める日から施行する。", "2000-05-26"), "2002-03-31")
        self.assertIsNone(d.window_end("この法律は、公布の日から施行する。", "2000-05-26"))

    def test_window_end_year_and_month(self):
        self.assertEqual(d.window_end("公布の日から起算して一年六月を超えない範囲内において政令で定める日", "2000-05-15"), "2001-11-15")

    def test_pick_decree_main(self):
        s = lambda date, kind="main": {"kind": kind, "date": date}
        self.assertEqual(d.pick_decree_main([s("1998-11-01")], PUB, "1998-12-03"), ("1998-11-01", "", []))
        self.assertEqual(d.pick_decree_main([s("1998-11-01"), s("1998-11-01")], PUB, None)[0], "1998-11-01")
        self.assertEqual(d.pick_decree_main([s("1998-11-01"), s("1998-12-01")], PUB, None)[1], d.R_CONFLICT)
        self.assertEqual(d.pick_decree_main([s("1998-05-01")], PUB, None)[1], d.R_OUT_OF_WINDOW)
        self.assertEqual(d.pick_decree_main([s("1999-01-01")], PUB, "1998-12-03")[1], d.R_OUT_OF_WINDOW)
        self.assertEqual(d.pick_decree_main([s("1998-11-01", "part")], PUB, None), ("", "", []))

    def test_referenced_law_num(self):
        body = "この法律は、商法等の一部を改正する法律（平成十二年法律第九十号）の施行の日から施行する。"
        self.assertEqual(d.referenced_law_num(body), "平成十二年法律第九十号")
        self.assertIsNone(d.referenced_law_num("この法律は、公布の日から施行する。"))


class RevisionTests(unittest.TestCase):
    QUOTE = "第一条　この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。ただし、第五十二条の十の改正規定は、公布の日から施行する。"

    def test_revision_dates_filters_by_number(self):
        revs = {"revisions": [
            {"amendment_law_num": "平成十年法律第八十八号", "amendment_enforcement_date": "1998-11-01"},
            {"amendment_law_num": "平成十年法律第八十八号", "amendment_enforcement_date": "1998-06-03"},
            {"amendment_law_num": "平成十一年法律第五十八号", "amendment_enforcement_date": "1999-11-01"},
            {"amendment_law_num": None, "amendment_enforcement_date": "1950-01-01"},
        ]}
        self.assertEqual(d.revision_dates(revs, ("平成", 10, 88)), ["1998-06-03", "1998-11-01"])

    def test_revision_main_date_excludes_proviso_dates(self):
        got = d.revision_main_date(["1998-06-03", "1998-11-01"], self.QUOTE, PUB)
        self.assertEqual(got[0], "1998-11-01")

    def test_revision_main_date_only_proviso_date_is_not_taken(self):
        self.assertEqual(d.revision_main_date(["1998-06-03"], self.QUOTE, PUB)[0], "")

    def test_revision_main_date_ambiguous(self):
        plain = "第一条　この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。"
        self.assertEqual(d.revision_main_date(["1998-08-01", "1998-11-01"], plain, PUB)[0], "")
        self.assertEqual(d.revision_main_date(["1998-11-01"], plain, PUB)[0], "1998-11-01")
        # 期間の外の日は採らない
        self.assertEqual(d.revision_main_date(["1999-04-01"], plain, PUB)[0], "")

    def test_revision_main_date_other_decree_in_proviso(self):
        quote = "第一条　この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。ただし、第三条の規定は、公布の日から起算して一年を超えない範囲内において政令で定める日から施行する。"
        self.assertEqual(d.revision_main_date(["1998-08-01", "1999-01-01"], quote, PUB)[0], "")

    def test_revision_main_date_proviso_tied_to_other_law(self):
        quote = "第一条　この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。ただし、第三条の規定は、商法等の一部を改正する法律の施行の日から施行する。"
        self.assertEqual(d.revision_main_date(["1998-08-01"], quote, PUB)[0], "")

    def test_revision_main_date_items_and_not_decree(self):
        items = "第一条　この法律は、次の各号に掲げる区分に応じ、当該各号に定める日から施行する。　一　公布の日"
        self.assertEqual(d.revision_main_date(["1998-08-01"], items, PUB)[0], "")
        fixed = "第一条　この法律は、平成十年十一月一日から施行する。"
        self.assertEqual(d.revision_main_date(["1998-11-01"], fixed, PUB)[0], "")


class XmlAndRowTests(unittest.TestCase):
    XML = (
        "<Law><LawNum>昭和四十年政令第九十六号</LawNum><LawBody><LawTitle>所得税法施行令</LawTitle>"
        "<SupplProvision AmendLawNum='平成十二年六月二十日政令第三百三十一号' Extract='true'><Paragraph><ParagraphSentence><Sentence>"
        "この政令は、沖縄振興開発金融公庫法の一部を改正する法律（平成十二年法律第七十七号）の施行の日（平成十二年六月二十六日）から施行する。"
        "</Sentence></ParagraphSentence></Paragraph></SupplProvision>"
        "<SupplProvision><Paragraph><ParagraphSentence><Sentence>この政令は、公布の日から施行する。</Sentence></ParagraphSentence></Paragraph></SupplProvision>"
        "</LawBody></Law>"
    )

    def test_scan_decree_xml(self):
        got = d.scan_decree_xml(ET.fromstring(self.XML), "平成十二年法律第七十七号")
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["kind"], got[0]["date"], got[0]["ref"], got[0]["title"]), ("main", "2000-06-26", "平成十二年政令第三百三十一号", "所得税法施行令"))
        self.assertTrue(got[0]["extract"])
        self.assertEqual(d.scan_decree_xml(ET.fromstring(self.XML), "平成十二年法律第七十八号"), [])

    def row(self):
        return {"id": "x", "題名": "t", "法令番号": NUM, "公布日": PUB, "施行日": "", d.CAND_COL: "1998-06-03",
                "取得方法": "施行期日条文（政令で定める日）", "備考": "政令で定める日（未確定）", "出典URL": "u1", d.NEW_COL: "第一条　この法律は、政令で定める日から施行する。"}

    def test_apply_row_filled(self):
        r = self.row()
        got = {"date": "1998-11-01", "method": d.METHOD_DECREE, "cands": ["1998-06-03"], "notes": ["根拠"], "quote": "【政令 平成十年政令第三百号（放送法施行令）附則】文", "urls": ["u1", "u2"], "reason": ""}
        d.apply_row(r, got)
        self.assertEqual(r["施行日"], "1998-11-01")
        self.assertEqual(r["取得方法"], "施行期日政令")
        self.assertEqual(r[d.CAND_COL], "1998-06-03")
        self.assertNotIn("未確定", r["備考"])
        self.assertIn(d.MARK, r["備考"])
        self.assertTrue(r[d.NEW_COL].endswith("文"))
        self.assertTrue(r[d.NEW_COL].startswith("第一条　この法律は、政令で定める日から施行する。 / 【政令"))
        self.assertEqual(r["出典URL"], "u1;u2")

    def test_apply_row_unfilled_is_idempotent(self):
        r = self.row()
        got = {"date": "", "method": "", "cands": [], "notes": [], "quote": "", "urls": [], "reason": d.R_NO_DECREE}
        d.apply_row(r, got)
        d.apply_row(r, got)
        self.assertEqual(r["施行日"], "")
        self.assertEqual(r["取得方法"], "施行期日条文（政令で定める日）")
        self.assertEqual(r["備考"].count(d.MARK), 1)
        self.assertIn("政令で定める日（未確定）", r["備考"])
        self.assertTrue(r["備考"].endswith(d.R_NO_DECREE))
        self.assertEqual(d.reason_of(r), d.R_NO_DECREE)


if __name__ == "__main__":
    unittest.main()
