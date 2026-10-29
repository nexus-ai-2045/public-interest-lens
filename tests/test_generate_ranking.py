import unittest

from scripts import source_check


class GenerateRankingTest(unittest.TestCase):
    def test_ranking_is_generated_from_inputs_with_all_laws_approved(self):
        # ranking.json は Git に置かない派生物。入力だけから作れて、承認の記録（全法律・既定の承認日）が付く
        payload = source_check.generate_ranking()
        self.assertEqual(payload["approval"]["scope"], "all-laws")
        self.assertEqual(payload["approval"]["approvedAt"], source_check.GENERATED_APPROVED_AT)
        self.assertGreater(len(payload["laws"]), 0)
        self.assertEqual(payload["counts"], source_check.generate_ranking()["counts"])  # 何度作っても同じ


if __name__ == "__main__":
    unittest.main()
