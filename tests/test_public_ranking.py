import json
import unittest

from scripts.build_public_ranking import OUTPUT, build


class PublicRankingTests(unittest.TestCase):
    def test_committed_file_matches_inputs(self):
        committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(committed, build(committed["approval"]["approvedLaws"], committed["approval"]["approvedAt"] or ""))

    def test_unapproved_build_has_no_amounts(self):
        payload = build([], "")
        self.assertEqual(payload["laws"], [])
        self.assertNotIn("people", payload)
        self.assertEqual(payload["counts"]["published"], 0)
        self.assertIn("APPROVAL", {item["reasonCode"] for item in payload["held"]})
        for item in payload["held"]:
            self.assertEqual(set(item), {"id", "title", "side", "reasonCode", "reason"})

    def test_only_publishable_laws_can_be_approved(self):
        with self.assertRaises(ValueError):
            build(["衆法-189-20"], "2026-10-17")
        with self.assertRaises(ValueError):
            build(["衆法-186-35"], "")

    def test_approved_law_carries_range_and_sources(self):
        payload = build(["衆法-186-35"], "2026-10-17")
        law = payload["laws"][0]
        self.assertEqual(law["side"], "benefit")
        self.assertLessEqual(law["amountLowYen"], law["amountMedianYen"])
        self.assertLessEqual(law["amountMedianYen"], law["amountHighYen"])
        self.assertTrue(law["sources"])
        self.assertNotIn(law["id"], {item["id"] for item in payload["held"]})


if __name__ == "__main__":
    unittest.main()
