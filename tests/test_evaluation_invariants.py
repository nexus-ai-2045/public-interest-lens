"""評価エンジンの数え方の不変条件（性質テスト）。

hypothesis は依存に無いので、規則の直積・固定種の乱数・現行データ照合で網羅する。
C2（参考額の確かさに段階語が残る）は、額の種類から印を出す関数で直す。
保存済みの台帳は再生成しないので、現行データの観測は残る。
"""
from __future__ import annotations

import csv
import random
import unittest
from itertools import product
from pathlib import Path

from scripts.build_evaluation_ledger import site_values
from scripts.evaluation_rules import (
    CERTAINTY_MARKS,
    KIND_CONFIRMED,
    KIND_FISCAL,
    KIND_NONE,
    KIND_REFERENCE,
    STAGE_TO_MARK,
    VERDICT_FAIL,
    amount_demoted,
    amount_kind_of,
    certainty_mark,
    is_demoted,
    narrow_whole_economy,
    sign_conflict,
)
from scripts import build_macro_amounts as macro

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "derived"


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class DemotionInvariantsTest(unittest.TestCase):
    """I3：参考への降格規則の性質。"""

    VERDICTS = ("合格", "不合格", "未検証", "")
    REACHES = (
        "",
        "評価対象外",
        "参考額（産業の付加価値の差）",
        "額（個別の因果の鎖）",
        "保留",
        "測定できない",
        "効果なし（定例）",
        "国の収支の額（GDP とは別欄）",
        "参考額",
        "額（個別",
    )
    CERTS = ("", "参考", "低", "中", "高", "段階1", "段階2", "段階3", "低（マクロ指標で代理）")

    def test_amount_demoted_implies_is_demoted(self) -> None:
        for v, r, c in product(self.VERDICTS, self.REACHES, self.CERTS):
            if amount_demoted(v, r, c):
                self.assertTrue(is_demoted(v, r, c), f"{v}|{r}|{c}")

    def test_evaluation_excluded_never_amount_demoted(self) -> None:
        for v, c in product(self.VERDICTS, self.CERTS):
            self.assertFalse(amount_demoted(v, "評価対象外", c), f"{v}|{c}")

    def test_only_fail_verdict_is_demoted(self) -> None:
        for v, r, c in product(self.VERDICTS, self.REACHES, self.CERTS):
            if is_demoted(v, r, c) or is_demoted(v, r, c, in_ranking=True):
                self.assertEqual(v, VERDICT_FAIL, f"{v}|{r}|{c}")

    def test_fail_with_reference_reach_is_amount_demoted(self) -> None:
        self.assertTrue(amount_demoted(VERDICT_FAIL, "参考額（産業の付加価値の差）", "参考"))
        self.assertTrue(amount_demoted(VERDICT_FAIL, "額（個別の因果の鎖）", "段階3"))


class SignAndNarrowBoundaryTest(unittest.TestCase):
    """L2・L3 の境界。C3：なぜ壊れるか — sign_conflict の条件が4通りだけで中央値0と悪影響＋負の便益を含まない。"""

    def test_sign_conflict_zero_median_is_not_conflict(self) -> None:
        # C3：中央値0は現行の4条件のどれにも当たらない
        self.assertIsNone(sign_conflict("貢献", "便益：中央値=0"))
        self.assertIsNone(sign_conflict("悪影響", "損失：中央値=0"))

    def test_sign_conflict_bad_direction_with_negative_benefit_is_not_conflict(self) -> None:
        # C3：悪影響＋便益で負は「便益かつ悪影響かつ value>0」に当たらない
        self.assertIsNone(sign_conflict("悪影響", "便益：中央値=-3"))

    def test_sign_conflict_detects_clear_opposites(self) -> None:
        self.assertEqual(sign_conflict("貢献", "便益：中央値=-1"), "便益")
        self.assertEqual(sign_conflict("悪影響", "便益：中央値=1"), "便益")
        self.assertEqual(sign_conflict("貢献", "損失：中央値=5"), "損失")

    def test_narrow_words_cover_documented_prefixes(self) -> None:
        for title in ("特例法", "特定産業法", "臨時法", "暫定措置", "特別措置法"):
            self.assertTrue(narrow_whole_economy(title, "_T", "経済全体"), title)
        # 「特別」単独は語表に無い（特別措置のみ）
        self.assertFalse(narrow_whole_economy("特別法", "_T", "経済全体"))


class DataInvariantsTest(unittest.TestCase):
    """I2：評価対象外が額の行に入らない（現行データ）。I3 の語彙ずれは C2 として数えるだけ。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.outcomes = {r["id"]: r for r in _read(D / "all-laws-v1" / "outcomes.csv")}
        cls.macro = _read(D / "macro-v1" / "macro.csv")
        cls.ledger = _read(D / "evaluation-ledger-v1" / "ledger.csv")

    def test_macro_amount_rows_exclude_skip_outcomes(self) -> None:
        for r in self.macro:
            if r["結果"] != "額":
                continue
            o = self.outcomes.get(r["id"])
            self.assertIsNotNone(o, r["id"])
            self.assertNotIn(o["結果"], macro.SKIP, r["id"])

    def test_ledger_evaluation_excluded_has_no_amount_fields(self) -> None:
        for r in self.ledger:
            if r["到達点"] != "評価対象外":
                continue
            self.assertFalse((r.get("額（円）") or "").strip(), r["id"])
            self.assertFalse((r.get("付加価値の変化（円）") or "").strip(), r["id"])

    def test_individual_amount_and_macro_amount_do_not_overlap(self) -> None:
        # L4：個別の額（outcomes 額あり・財政以外）と macro 額の二重無し
        individual = {
            i
            for i, o in self.outcomes.items()
            if o["結果"] == "額あり" and o.get("経路") != "財政（税収見込み）"
        }
        macro_amt = {r["id"] for r in self.macro if r["結果"] == "額"}
        self.assertEqual(individual & macro_amt, set())

    def test_c2_live_ledger_still_has_stage_certainty_on_reference_amounts(self) -> None:
        # 保存済み台帳には C2 が残っている（この変更では再生成しない。0 なら台帳を作り直したか確かめる）
        n = sum(
            1
            for r in self.ledger
            if r["到達点"].startswith("参考額") and str(r.get("確かさ", "")).startswith("段階")
        )
        self.assertGreater(n, 0, "C2 が消えた。正規化が入ったかデータを確認する")


class CounterexampleC2RootCauseTest(unittest.TestCase):
    """C2：参考額の印は、outcomes の確かさ欄（段階語・代理の注記）ではなく額の種類から決める。"""

    def _site(self, certainty: str, *, result: str = "保留", stage: str = "", route: str = "市場",
              amount: str = "", macro: bool = True):
        o = {
            "id": "閣法-0-0",
            "確かさ": certainty,
            "段階": stage,
            "種類": "実質改正",
            "分野": "",
            "結果": result,
            "経路": route,
            "損失または便益の額": amount,
        }
        m = {
            "結果": "額",
            "中央値": "1",
            "分野": "金融",
            "分野の由来": "テスト",
        }
        src = {
            "agree": {},
            "tie": {},
            "macro": {o["id"]: m} if macro else {},
            "econ": {},
            "field": {},
            "corr": {},
        }
        return site_values(o, src)

    def test_c2_reference_amount_mark_is_reference_for_every_non_mark(self) -> None:
        # 原因は段階1だけの特別扱いではない。空でない outcomes の確かさが参考額の印を上書きしていた。
        for word in ("段階1", "段階2", "段階3", "段階1・参考", "低（マクロ指標で代理）", "高（段階3）"):
            v = self._site(word)
            self.assertEqual(v["到達点"], "参考額（産業の付加価値の差）", word)
            self.assertEqual(v["確かさ"], "参考", word)

    def test_c2_desired_reference_amount_certainty_is_reference(self) -> None:
        v = self._site("段階1")
        self.assertEqual(v["到達点"], "参考額（産業の付加価値の差）")
        self.assertEqual(v["確かさ"], "参考")

    def test_confirmed_amount_mark_follows_stage(self) -> None:
        for stage, mark in STAGE_TO_MARK.items():
            v = self._site(stage, result="額あり", stage=stage, route="市場（v2の後段）",
                           amount="損失：中央値=1", macro=False)
            self.assertEqual(v["到達点"], "額（個別の因果の鎖）", stage)
            self.assertEqual(v["確かさ"], mark, stage)

    def test_no_amount_does_not_keep_a_stage_word(self) -> None:
        v = self._site("段階1", macro=False)
        self.assertEqual(v["到達点"], "保留")
        self.assertEqual(v["確かさ"], "")

    def test_fiscal_amount_mark_is_high(self) -> None:
        v = self._site("高", result="額あり", route="財政（税収見込み）", amount="1", macro=False)
        self.assertEqual(v["到達点"], "国の収支の額（GDP とは別欄）")
        self.assertEqual(v["確かさ"], "高")


class CertaintyMarkVocabularyTest(unittest.TestCase):
    """印は ADR 0008 の高・中・低・参考だけ。段階語は印にならない。"""

    def test_amount_kind_follows_reach(self) -> None:
        self.assertEqual(amount_kind_of("参考額（産業の付加価値の差）"), KIND_REFERENCE)
        self.assertEqual(amount_kind_of("額（個別の因果の鎖）"), KIND_CONFIRMED)
        self.assertEqual(amount_kind_of("国の収支の額（GDP とは別欄）"), KIND_FISCAL)
        for reach in ("保留", "測定できない", "効果なし（定例）", "評価対象外", ""):
            self.assertEqual(amount_kind_of(reach), KIND_NONE, reach)

    def test_marks_stay_inside_adr_0008(self) -> None:
        cases = [
            (KIND_REFERENCE, "段階1", "参考"),
            (KIND_REFERENCE, "段階2", "参考"),
            (KIND_REFERENCE, "段階3", "参考"),
            (KIND_REFERENCE, "", "参考"),
            (KIND_CONFIRMED, "段階3", "高"),
            (KIND_CONFIRMED, "段階2", "中"),
            (KIND_CONFIRMED, "段階1", "低"),
            (KIND_FISCAL, "", "高"),
            (KIND_FISCAL, "段階1", "高"),
            (KIND_NONE, "段階1", ""),
            (KIND_NONE, "低（マクロ指標で代理）", ""),
        ]
        for kind, stage, expected in cases:
            got = certainty_mark(kind, stage)
            self.assertEqual(got, expected, f"{kind}|{stage}")
            if got:
                self.assertIn(got, CERTAINTY_MARKS, f"{kind}|{stage}")
            self.assertFalse(str(got).startswith("段階"), f"{kind}|{stage}")

    def test_unknown_stage_or_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            certainty_mark(KIND_CONFIRMED, "段階4")
        with self.assertRaises(ValueError):
            certainty_mark(KIND_CONFIRMED, "高（段階3）")
        with self.assertRaises(ValueError):
            certainty_mark("段階1")


class DeterministicRulesSmokeTest(unittest.TestCase):
    """I4 の規則側：同じ引数なら同じ真偽。"""

    def test_demotion_is_stable_under_repeated_calls(self) -> None:
        rng = random.Random(20261120)
        for _ in range(200):
            v = rng.choice(DemotionInvariantsTest.VERDICTS)
            r = rng.choice(DemotionInvariantsTest.REACHES)
            c = rng.choice(DemotionInvariantsTest.CERTS)
            a = is_demoted(v, r, c)
            b = amount_demoted(v, r, c)
            self.assertEqual(a, is_demoted(v, r, c))
            self.assertEqual(b, amount_demoted(v, r, c))


if __name__ == "__main__":
    unittest.main()
