import unittest

from scripts import party_subsidy as ps


def reading(**over):
    base = {
        "名称": "自由民主党テスト選挙区支部", "代表者": "山田 太郎", "区分": "政党の支部", "年分": "令和7年分",
        "交付金総額": 12000000, "前年末基金残高": 2000000, "交付金による支出総額": 12000000,
        "交付金支出充当額": 10000000, "基金支出充当額": 2000000, "本年末基金残高": 2000000,
        "交付元": [{"交付をした者": "自由民主党本部", "年月日": "R7/4/28", "金額": 12000000}],
        "支出": {"支部政党交付金": 0, "人件費": 1, "光熱水費": 2, "備品消耗品費": 3, "事務所費": 4, "組織活動費": 5,
                 "選挙関係費": 6, "機関紙誌": 7, "調査研究費": 8, "寄附金": 9, "その他の経費": 10, "合計": 55},
    }
    base.update(over)
    return base


class AdoptTests(unittest.TestCase):
    def test_two_readers_agree_ignoring_spacing(self):
        a, b = reading(), reading(代表者="山田太郎")
        c, how, flows = ps.adopt(a, b, None)
        self.assertEqual(how, "A・B一致")
        self.assertEqual(c["代表者"], "山田太郎")
        self.assertEqual(flows, [("自由民主党本部", "R7/4/28", 12000000)])

    def test_disagreement_needs_third_reader_to_match_one(self):
        a, b = reading(), reading(交付金総額=13000000)
        self.assertIsNone(ps.adopt(a, b, None)[0])
        self.assertEqual(ps.adopt(a, b, reading())[1], "C・A一致")
        self.assertIsNone(ps.adopt(a, b, reading(交付金総額=14000000))[0])

    def test_missing_reader_is_not_adopted(self):
        self.assertIsNone(ps.adopt(reading(), None, None)[0])

    def test_flows_only_kept_when_readers_agree_on_them(self):
        b = reading(交付元=[])
        self.assertEqual(ps.adopt(reading(), b, None)[2], [])


class ArithTests(unittest.TestCase):
    def test_consistent_reading_passes(self):
        self.assertEqual(ps._arith(ps._canon(reading())), [])

    def test_bad_split_is_caught(self):
        self.assertIn("③≠④+⑤", ps._arith(ps._canon(reading(交付金支出充当額=9000000))))

    def test_balance_identity_is_caught(self):
        self.assertIn("①-③+②-⑧≠0", ps._arith(ps._canon(reading(本年末基金残高=1))))

    def test_expense_sum_is_caught(self):
        r = reading()
        r["支出"]["合計"] = 56
        self.assertIn("支出の費目の和≠合計", ps._arith(ps._canon(r)))

    def test_missing_pages_skip_formulas_but_are_partial(self):
        c = ps._canon(reading(支出=None))
        self.assertEqual(ps._arith(c), [])
        self.assertEqual(ps.completeness(c), "一部の頁のみ")
        self.assertEqual(ps.completeness(ps._canon(reading())), "完全")


class NumTests(unittest.TestCase):
    def test_num_accepts_ints_and_comma_strings_only(self):
        self.assertEqual(ps._num("1,200"), 1200)
        self.assertIsNone(ps._num("1.5"))
        self.assertIsNone(ps._num(True))
        self.assertIsNone(ps._num(None))


class DistrictTests(unittest.TestCase):
    def test_kansuji(self):
        self.assertEqual([ps.kansuji(x) for x in ("三", "十", "十九", "二十", "二十一", "7")], [3, 10, 19, 20, 21, 7])

    def test_district_of_lower_house_branch_only(self):
        self.assertEqual(ps.district_of("自由民主党東京都第十九選挙区支部"), "東京19")
        self.assertEqual(ps.district_of("自由民主党北海道第三選挙区支部"), "北海道3")
        self.assertIsNone(ps.district_of("自由民主党山形県参議院選挙区第1支部"))


if __name__ == "__main__":
    unittest.main()
