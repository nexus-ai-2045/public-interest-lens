"""scripts/estimate_field_expansion.py の確認：既存の分野を変えないこと、規則（D1・D2・D5・語の包含）、本数の整合、出力の形。
語の表の妥当性（適合率）は確かめない。"""
import csv
import tempfile
import unittest
from pathlib import Path

from scripts import estimate_field_expansion as est


class ClassifyTest(unittest.TestCase):
    def test_new_field_when_no_existing_word(self):
        c = est.classify("農業経営基盤強化促進法等の一部を改正する法律案")
        self.assertEqual((c["kind"], c["field"], c["word"]), ("新", "農林水産", "農業"))
        self.assertEqual(est.NEW_FIELDS[c["field"]][0], "農林水産業の付加価値")

    def test_existing_field_wins_even_when_new_word_comes_first(self):
        # 「保険」は既存の金融の語。新分野の「介護」が前にあっても、既存の規則どおり既存分野（既存の結果を変えない）。
        c = est.classify("介護保険法の一部を改正する法律案")
        self.assertEqual((c["kind"], c["field"]), ("既存", "金融"))

    def test_no_word_stays_without_table(self):
        c = est.classify("公職選挙法の一部を改正する法律案")
        self.assertEqual((c["kind"], c["field"]), (est.NO_FIELD, est.NO_FIELD))

    def test_earliest_new_word_decides(self):
        c = est.classify("農業のための大学の整備に関する法律案")
        self.assertEqual((c["field"], c["word"]), ("農林水産", "農業"))
        c = est.classify("大学のための農業の整備に関する法律案")
        self.assertEqual((c["field"], c["word"]), ("教育", "大学"))

    def test_longer_word_at_same_position_is_a_rephrase_not_a_tie(self):
        # 「建築士」（専門）は「建築」（建設）の延長。同じ位置なら長い語を採り、保留にしない。
        c = est.classify("建築士法の一部を改正する法律案")
        self.assertEqual((c["field"], c["word"]), ("専門サービス・研究開発", "建築士"))
        c = est.classify("土地改良法の一部を改正する法律案")
        self.assertEqual((c["field"], c["word"]), ("農林水産", "土地改良"))

    def test_same_position_different_fields_is_held(self):
        saved = est.NEW_WORDS
        try:
            est.NEW_WORDS = [("教育", "共通語", "代理"), ("建設", "共通語", "代理")]
            c = est.classify("共通語の法律案")
            self.assertEqual((c["kind"], c["field"]), (est.HOLD, est.HOLD))
        finally:
            est.NEW_WORDS = saved

    def test_d2_drops_the_trailing_establishment_law(self):
        # 設置法の部分に新分野の語があっても、最初の法律で決める（D2）。
        c = est.classify("公職選挙法及び農林水産省設置法の一部を改正する法律案")
        self.assertTrue(c["d2"])
        self.assertEqual(c["field"], est.NO_FIELD)

    def test_new_field_words_do_not_collide_with_existing_words(self):
        existing = {w for _, w in est.EXISTING_WORDS}
        shared = [w for _, w, _ in est.NEW_WORDS if w in existing]
        self.assertEqual(shared, [])


class EstimateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.targets = est.load_targets()
        cls.rows = est.estimate(cls.targets)

    def test_targets_are_the_substantive_laws_without_a_field(self):
        self.assertEqual(len(self.targets), 1662)
        self.assertEqual(len({t["id"] for t in self.targets}), 1662)

    def test_every_law_gets_exactly_one_result_and_counts_add_up(self):
        self.assertEqual(len(self.rows), len(self.targets))
        new = [r for r in self.rows if r["新分野"] in est.NEW_FIELDS]
        existing = [r for r in self.rows if r["新分野"].startswith("（既存の規則で）")]
        rest = [r for r in self.rows if r["新分野"] in (est.NO_FIELD, est.HOLD)]
        self.assertEqual(len(new) + len(existing) + len(rest), len(self.rows))
        self.assertGreater(len(new), 0)

    def test_indicator_is_filled_only_for_new_fields(self):
        for r in self.rows:
            if r["新分野"] in est.NEW_FIELDS:
                self.assertEqual(r["指標"], est.NEW_FIELDS[r["新分野"]][0])
                self.assertTrue(r["一致した語"])
                self.assertIn(r["対応"], ("直接", "代理"))
            else:
                self.assertEqual(r["指標"], "")

    def test_remaining_laws_carry_a_reason(self):
        for r in self.rows:
            if r["新分野"] == est.NO_FIELD:
                self.assertTrue(r["備考"])

    def test_existing_fields_do_not_change(self):
        n, changed, _ = est.regression()
        self.assertGreater(n, 0)
        self.assertEqual(changed, 0)

    def test_write_has_the_documented_columns(self):
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d) / "sub" / "estimate.csv"
            est.write(self.rows[:5], dst)
            with dst.open(encoding="utf-8", newline="") as f:
                got = list(csv.DictReader(f))
        self.assertEqual(list(got[0].keys()), est.HEADER)
        self.assertEqual(est.HEADER[:5], ["id", "題名", "新分野", "指標", "一致した語"])
        self.assertEqual(len(got), 5)

    def test_committed_estimate_matches_the_script(self):
        with est.OUT.open(encoding="utf-8", newline="") as f:
            committed = list(csv.DictReader(f))
        self.assertEqual(len(committed), len(self.rows))
        self.assertEqual([r["新分野"] for r in committed], [r["新分野"] for r in self.rows])


if __name__ == "__main__":
    unittest.main()
