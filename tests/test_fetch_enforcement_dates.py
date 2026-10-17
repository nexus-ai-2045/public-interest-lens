import unittest

from scripts import fetch_enforcement_dates as f


class EnforcementDatesTests(unittest.TestCase):
    def test_kanji_round_trip(self):
        for n in (1, 4, 10, 11, 25, 100, 105, 116, 210):
            self.assertEqual(f.from_kanji(f.to_kanji(n)), n)
        self.assertEqual(f.to_kanji(116), "百十六")

    def test_law_num_and_id(self):
        own = f.parse_law_num("平成十年法律第二十五号")
        self.assertEqual(own, ("平成", 10, 25))
        self.assertEqual(f.law_id_of(*own), "410AC0000000025")
        self.assertEqual(f.format_law_num(*own), "平成十年法律第二十五号")
        self.assertEqual(f.parse_law_num("平成元年法律第四号"), ("平成", 1, 4))

    def test_wareki(self):
        parts = f.parse_wareki("平成28年 6月 3日")
        self.assertEqual(f.wareki_to_iso(parts), "2016-06-03")

    def test_amended_titles(self):
        self.assertEqual(f.amended_titles("預金保険法の一部を改正する法律案"), ["預金保険法"])
        self.assertEqual(f.amended_titles("船員法等の一部を改正する法律案"), ["船員法等"])
        self.assertIsNone(f.amended_titles("中部国際空港の設置及び管理に関する法律案"))

    def test_pick_main(self):
        self.assertEqual(f.pick_main(["2020-04-01"]), ("2020-04-01", ""))
        self.assertEqual(f.pick_main(["2020-04-01", "2020-04-01", "2021-04-01"])[0], "2020-04-01")
        self.assertEqual(f.pick_main(["2020-04-01", "2021-04-01"])[0], "")
        self.assertEqual(f.pick_main([]), ("", ""))


if __name__ == "__main__":
    unittest.main()
