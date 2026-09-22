"""製品目的の後退と架空データの誤配信を検出する。"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductContractTests(unittest.TestCase):
    def test_active_documents_follow_person_ranking_purpose(self):
        prohibited = ("ランキングにはしない", "順位や最終判断として表示しない", "人物評価に見えない")
        for name in ("README.md", "spec-card.md", "human-review-checklist.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertIn("PROJECT_SSOT.md", text)
                for phrase in prohibited:
                    self.assertNotIn(phrase, text)

    def test_private_materials_are_ignored(self):
        self.assertIn(".local/", (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())


if __name__ == "__main__":
    unittest.main()
