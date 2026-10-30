"""全ての成立法（3,415本）に結果が1つずつ付いていることと、結果の規則の形を確かめる（規則の妥当性ではなく、漏れ・重複・理由の空欄・系列の実在）。"""
import csv
import unittest
from pathlib import Path

from scripts import build_all_laws_outcomes as ol

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = ROOT / "data" / "derived" / "all-laws-v1" / "outcomes.csv"
TOTAL = 3415


def read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def triage_row(**kw):
    base = {"id": "閣法-999-1", "結果": "評価対象", "種類": "実質改正", "分野": "金融", "指標": "貸出残高",
            "A_種類": "実質改正", "B_種類": "実質改正", "A_分野": "金融", "B_分野": "金融"}
    return {**base, **kw}


class EmptyStages(ol.Stages):
    def __init__(self):
        self.agreement, self.impact, self.loss, self.benefit, self.publish = {}, {}, {}, {}, {}


class LedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read(OUTCOMES)

    def test_every_law_has_exactly_one_row_in_triage_order(self):
        triage = read(ROOT / "data" / "derived" / "bill-triage-v1" / "triage.csv")
        self.assertEqual(len(self.rows), TOTAL)
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(set(ids)), TOTAL)
        self.assertEqual(ids, [r["id"] for r in triage])
        self.assertEqual(len(read(ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv")), TOTAL)

    def test_outcome_vocabulary_and_reason_for_every_non_amount_row(self):
        for r in self.rows:
            self.assertIn(r["結果"], ol.OUTCOMES, r["id"])
            self.assertTrue(r["題名"].strip(), r["id"])
            if r["結果"] != "額あり":
                self.assertTrue(r["理由"].strip(), r["id"])
            else:
                self.assertTrue(r["損失または便益の額"].strip(), r["id"])

    def test_undated_market_laws_are_held_with_the_reason(self):
        for r in self.rows:
            if r["経路"] == "市場（施行日待ち）":
                self.assertEqual(r["結果"], "保留", r["id"])
                self.assertEqual(r["施行日"], "", r["id"])
                self.assertIn("施行日が未取得", r["理由"], r["id"])

    def test_macro_rows_are_marked_low_confidence_with_an_existing_series(self):
        macro = [r for r in self.rows if r["経路"].startswith("MA")]
        self.assertTrue(macro)
        for r in macro:
            self.assertEqual(r["確かさ"], ol.MACRO_CONFIDENCE, r["id"])
            self.assertIn(r["指標"], ol.MACRO_INDICATORS, r["id"])
            self.assertEqual(r["結果"], "保留", r["id"])
        for indicator, (path, key) in ol.MACRO_INDICATORS.items():
            self.assertTrue(any(all(row[k] == v for k, v in key.items()) for row in read(ROOT / path)), indicator)

    def test_routine_rows_name_the_rule(self):
        routine = [r for r in self.rows if r["結果"] == "効果なし（定例）"]
        self.assertTrue(routine)
        codes = {sign for sign, *_ in ol.ROUTINE_RULES} | {ol.RT8[0]}
        for r in routine:
            self.assertIn(r["経路"], codes, r["id"])
            self.assertIn("題名の語", r["理由"], r["id"])

    def test_amount_rows_are_exactly_the_loss_rows_with_an_amount(self):
        loss = read(ROOT / "data" / "derived" / "loss-v1-triage-v2" / "loss.csv")
        covid = {r["id"] for r in read(ROOT / "data" / "derived" / "covid-response-v1" / "labels.csv") if r["コロナ対応"] == "はい"}
        with_amount = {r["id"] for r in loss if r["損失または便益の額"].strip()}
        # コロナ対応の法律は、損失表に額があっても台帳では保留にする（費用便益で扱う）
        self.assertEqual({r["id"] for r in self.rows if r["結果"] == "額あり"}, with_amount - covid)
        held = {r["id"]: r for r in self.rows}
        for law_id in with_amount & covid:
            self.assertEqual((held[law_id]["結果"], held[law_id]["経路"]), ("保留", "市場（コロナ対応）"), law_id)

    def test_committed_ledger_is_what_the_script_produces(self):
        # 後段（影響・損失・便益・公開）や施行日台帳を更新したら、python3 scripts/build_all_laws_outcomes.py を再実行する。
        self.assertEqual(self.rows, ol.build())


class DecideTest(unittest.TestCase):
    law = {"題名": "預金保険法の一部を改正する法律案"}

    def test_routine_title_rules(self):
        for title, sign in (("一般職の職員の給与に関する法律の一部を改正する法律案", "RT1"),
                            ("地方交付税法等の一部を改正する法律案", "RT2"),
                            ("平成二十年度における公債の発行の特例に関する法律案", "RT3")):
            r = ol.decide({"題名": title}, triage_row(), "", EmptyStages())
            self.assertEqual((r["結果"], r["経路"]), ("効果なし（定例）", sign), title)
        # RT8 は両系統の種類が定型改正のときだけ
        title = "地震対策緊急整備事業に係る国の財政上の特別措置に関する法律の一部を改正する法律案"
        self.assertEqual(ol.decide({"題名": title}, triage_row(), "", EmptyStages())["経路"], "市場（施行日待ち）")
        fixed = triage_row(A_種類="定型改正", B_種類="定型改正")
        self.assertEqual(ol.decide({"題名": title}, fixed, "", EmptyStages())["経路"], "RT8")

    def test_tb2_uses_the_chosen_line_kind_for_the_routine_rule(self):
        # TB2 で系統2（新規）を採った行は、v1 の A・B が定型改正でも RT8（定例）にしない
        title = "地震対策緊急整備事業に係る国の財政上の特別措置に関する法律の一部を改正する法律案"
        st = EmptyStages()
        st.agreement = {"閣法-999-1": {"結果": "採用", "解消規則": "TB2", "系統1_判定": "評価対象外", "系統1_分野": "対応表なし", "系統1_指標": "",
                                       "系統2_判定": "評価対象", "系統2_分野": "金融", "系統2_指標": "貸出残高"}}
        st.line_pick = {"閣法-999-1": "系統2"}
        st.line_kind = {"系統1": {"閣法-999-1": "定型改正"}, "系統2": {"閣法-999-1": "新規"}}
        fixed = triage_row(種類="定型改正", A_種類="定型改正", B_種類="定型改正")
        r = ol.decide({"題名": title}, fixed, "2020-04-01", st)
        self.assertNotEqual(r["経路"], "RT8")
        self.assertEqual((r["種類"], r["分野"], r["指標"]), ("新規", "金融", "貸出残高"))

    def test_law_without_a_date_is_held(self):
        r = ol.decide(self.law, triage_row(), "", EmptyStages())
        self.assertEqual(r["結果"], "保留")
        self.assertIn("施行日が未取得", r["理由"])

    def test_dated_law_missing_from_v2_tables_is_held_not_dropped(self):
        # 台帳に後から施行日が足された行：v2 の一連を再実行するまでは保留。落とさない。
        r = ol.decide(self.law, triage_row(), "2020-04-01", EmptyStages())
        self.assertEqual(r["結果"], "保留")
        self.assertEqual(r["施行日"], "2020-04-01")
        self.assertTrue(r["理由"])

    def test_no_market_law_gets_macro_proxy_or_explicit_reason(self):
        t = triage_row(結果="評価対象外", 分野=ol.NO_FIELD, 指標="", A_分野=ol.NO_FIELD, B_分野=ol.NO_FIELD)
        r = ol.decide({"題名": "裁判所法の一部を改正する法律案"}, t, "", EmptyStages())
        self.assertEqual((r["指標"], r["確かさ"], r["結果"]), ("公務の付加価値（実質）", ol.MACRO_CONFIDENCE, "保留"))
        r = ol.decide({"題名": "特許法の一部を改正する法律案"}, t, "", EmptyStages())
        self.assertEqual(r["結果"], "測定できない")
        self.assertTrue(r["理由"])
        out = triage_row(結果="評価対象外", 種類="組織手続", 分野=ol.NO_FIELD, A_種類="組織手続", B_種類="組織手続",
                         A_分野=ol.NO_FIELD, B_分野=ol.NO_FIELD)
        r = ol.decide({"題名": "文化財保護法の一部を改正する法律案"}, out, "", EmptyStages())
        self.assertEqual(r["結果"], "評価対象外")


if __name__ == "__main__":
    unittest.main()
