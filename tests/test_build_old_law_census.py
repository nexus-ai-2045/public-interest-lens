import unittest

from scripts.build_old_law_census import build, kanji_number, law_num_text

import datetime as dt

BASE = "https://www.shugiin.go.jp/internet/itdb_housei.nsf/html/houritsu/"


def session(number, rows):
    return {"回次": number, "url": f"{BASE}kaiji{number:03d}_l.htm", "取得": True, "rows": rows, "メモ": ""}


class OldLawCensusTests(unittest.TestCase):
    def test_kanji_number(self):
        self.assertEqual(kanji_number(1), "一")
        self.assertEqual(kanji_number(10), "十")
        self.assertEqual(kanji_number(123), "百二十三")
        self.assertEqual(kanji_number(64), "六十四")

    def test_era_boundary(self):
        self.assertEqual(law_num_text(dt.date(1989, 1, 6), 1), "昭和六十四年法律第一号")
        self.assertEqual(law_num_text(dt.date(1989, 1, 11), 1), "平成元年法律第一号")

    def test_mismatched_url_is_dropped(self):
        rows, _, problems = build([session(113, [
            {"法律番号": "1", "題名": "甲法", "リンクURL": f"{BASE}11319890106001.htm"},
            {"法律番号": "3", "題名": "乙法", "リンクURL": f"{BASE}11319890106002.htm"},
        ])])
        self.assertEqual([r["題名"] for r in rows], ["甲法"])
        self.assertTrue(any("一致しない" in p for p in problems))

    def test_gap_in_numbers_is_reported(self):
        _, _, problems = build([session(120, [
            {"法律番号": "1", "題名": "甲法", "リンクURL": f"{BASE}12019910201001.htm"},
            {"法律番号": "3", "題名": "丙法", "リンクURL": f"{BASE}12019910201003.htm"},
        ])])
        self.assertTrue(any("[2]" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
