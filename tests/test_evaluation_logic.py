"""評価のロジック検査（scripts/check_evaluation_logic.py）の歯止め。
違反が基準（data/derived/evaluation-ledger-v1/logic-baseline.json）より増えたら落ちる。減らしたら基準を下げる。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_evaluation_logic as logic


class EvaluationLogicTest(unittest.TestCase):
    def test_violations_do_not_increase(self):
        base = json.loads(logic.BASELINE.read_text(encoding="utf-8"))
        now = logic.counts(logic.check())
        for rule in logic.RULES:
            self.assertLessEqual(now[rule], base[rule], f"{rule} の違反が基準 {base[rule]} 本から {now[rule]} 本に増えた")

    def test_double_count_and_contradiction_rules_are_zero(self):
        now = logic.counts(logic.check())
        for rule in ("L4", "L5", "L6"):
            self.assertEqual(now[rule], 0, f"{rule} は0本でなければならない")


if __name__ == "__main__":
    unittest.main()
