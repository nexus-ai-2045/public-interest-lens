import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_public_pledges as b  # noqa: E402


class ReconcileTest(unittest.TestCase):
    def test_agree_enacted_keeps_common_laws(self):
        a = {"status": "enacted", "lawIds": ["x", "y"]}
        c = {"status": "enacted", "lawIds": ["y", "z"]}
        self.assertEqual(b.reconcile(a, c), ("enacted", ["y"]))

    def test_enacted_without_common_law_is_review(self):
        a = {"status": "enacted", "lawIds": ["x"]}
        c = {"status": "enacted", "lawIds": ["z"]}
        self.assertEqual(b.reconcile(a, c)[0], "review")

    def test_disagreement_and_missing_are_review(self):
        self.assertEqual(b.reconcile({"status": "enacted", "lawIds": ["x"]}, {"status": "no_law_found", "lawIds": []})[0], "review")
        self.assertEqual(b.reconcile(None, {"status": "no_law_found", "lawIds": []})[0], "review")

    def test_agreed_non_enacted(self):
        self.assertEqual(b.reconcile({"status": "no_law_needed", "lawIds": []}, {"status": "no_law_needed", "lawIds": []}), ("no_law", []))
        self.assertEqual(b.reconcile({"status": "no_law_found", "lawIds": []}, {"status": "no_law_found", "lawIds": []}), ("none", []))

    def test_stance(self):
        law = {"shu": {"yes": ["自由民主党・無所属の会"], "no": ["日本共産党"]}}
        self.assertEqual(b.stance(law, "自由民主"), "yes")
        self.assertEqual(b.stance(law, "共産"), "no")
        self.assertEqual(b.stance(law, "立憲"), "none")
        self.assertEqual(b.stance({"shu": None}, "立憲"), "none")


if __name__ == "__main__":
    unittest.main()
