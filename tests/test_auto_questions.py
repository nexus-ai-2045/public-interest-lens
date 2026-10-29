"""自動の関与に足した質疑（scripts/build_auto_questions.py → build_auto_involvements.py）が決まりどおりであること。"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data/derived/allocation-v1/questions-auto.csv"
AUTO = ROOT / "data/derived/allocation-v1/involvements-auto.csv"


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class AutoQuestionsTest(unittest.TestCase):
    def test_questions_follow_the_rules(self) -> None:
        rows = read(QUESTIONS)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["行動"], "question")
            self.assertTrue(r["証拠URL"].startswith("https://kokkai.ndl.go.jp/"), r["証拠URL"])
            # 算入するのは支持の質疑だけで、参議院本会議で反対票を入れた人は数えない。
            if r["算入"] == "はい":
                self.assertEqual(r["除外理由"], "")
                self.assertNotEqual(r["参院本会議の賛否"], "N")
            else:
                self.assertTrue(r["除外理由"])

    def test_auto_involvements_carry_only_built_laws(self) -> None:
        auto = read(AUTO)
        built = {r["法律ID"] for r in auto if r["行動"] == "vote"}
        questions = [r for r in auto if r["行動"] == "question"]
        self.assertTrue(questions)
        self.assertTrue({r["法律ID"] for r in questions} <= built)
        expected = {(r["法律ID"], r["氏名"], r["証拠URL"]) for r in read(QUESTIONS) if r["法律ID"] in built}
        self.assertEqual({(r["法律ID"], r["氏名"], r["証拠URL"]) for r in questions}, expected)


if __name__ == "__main__":
    unittest.main()
