import unittest

from scripts.apply_enforcement_webfetch import apply, decree_deadline, header_matches, main_sentence

ROW = {
    "id": "閣法-1-1", "題名": "甲法案", "法令番号": "平成十年法律第五号", "公布日": "1998-02-18", "施行日": "",
    "施行日の候補（; 区切り）": "", "取得方法": "取得不可", "備考": "", "出典URL": "", "施行期日の原文": "",
}


def quote(line, text, header="法律第五号（平一〇・二・一八）"):
    return {"系統": line, "id": "閣法-1-1", "honbun_url": "https://www.shugiin.go.jp/x.htm", "header": header, "fusoku_quote": text}


class ApplyEnforcementTests(unittest.TestCase):
    def test_main_sentence_strips_heading_and_number(self):
        a, _ = main_sentence("（施行期日）\n第一条 この法律は、平成十一年十月一日から施行する。ただし、附則第七条は、公布の日から施行する。")
        b, _ = main_sentence("この法律は、平成十一年十月一日から施行する。ただし、附則第七条は、公布の日から施行する。")
        self.assertEqual(a, b)
        self.assertEqual(a, "この法律は、平成十一年十月一日から施行する。")

    def test_header_must_match_number_and_date(self):
        self.assertTrue(header_matches("法律第五号（平一〇・二・一八）", "平成十年法律第五号", "1998-02-18"))
        self.assertFalse(header_matches("法律第六号（平一〇・二・一八）", "平成十年法律第五号", "1998-02-18"))
        self.assertFalse(header_matches("法律第五号（平一〇・二・一九）", "平成十年法律第五号", "1998-02-18"))

    def test_decree_deadline(self):
        text = "この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。"
        self.assertEqual(decree_deadline(text, "2005-05-06"), "2005-11-06")

    def test_both_lines_must_agree(self):
        rows = [dict(ROW)]
        apply(rows, {"附則": [quote("A", "この法律は、公布の日から施行する。"), quote("B", "この法律は、平成十年四月一日から施行する。")], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "")

    def test_agreeing_lines_set_date(self):
        rows = [dict(ROW)]
        apply(rows, {"附則": [quote("A", "第一条 この法律は、公布の日から施行する。"), quote("B", "この法律は、公布の日から施行する。")], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "1998-02-18")
        self.assertIn("2系統一致", rows[0]["取得方法"])

    def test_candidate_needs_second_fetch_and_period(self):
        base = dict(ROW, 施行期日の原文="この法律は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。")
        first = {"id": "閣法-1-1", "施行日": "1998-04-01", "出典URL": "https://www.mlit.go.jp/a", "原文の引用": "甲法の施行期日を平成十年四月一日とする。"}
        rows = [dict(base)]
        apply(rows, {"附則": [], "省庁資料の候補": [first]})
        self.assertEqual(rows[0]["施行日"], "")
        self.assertIn("1998-04-01", rows[0]["施行日の候補（; 区切り）"])
        rows = [dict(base)]
        second = {"id": "閣法-1-1", "fetched": True, "law_matches": True, "date": "1998-04-01"}
        apply(rows, {"附則": [], "省庁資料の候補": [first], "候補の再取得": [second]})
        self.assertEqual(rows[0]["施行日"], "1998-04-01")
        rows = [dict(base)]
        late = dict(first, 施行日="1998-07-01")
        apply(rows, {"附則": [], "省庁資料の候補": [late], "候補の再取得": [dict(second, date="1998-07-01")]})
        self.assertEqual(rows[0]["施行日"], "")


if __name__ == "__main__":
    unittest.main()
