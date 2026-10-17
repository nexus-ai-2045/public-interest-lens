import unittest

from scripts import daily_update


class DailyUpdateTests(unittest.TestCase):
    def test_merge_keeps_missing_rows_and_updates_by_key(self):
        old = [{"種別": "閣法", "提出回次": "1", "番号": "1", "題名": "a"}, {"種別": "閣法", "提出回次": "1", "番号": "2", "題名": "b"}]
        new = [{"種別": "閣法", "提出回次": "1", "番号": "2", "題名": "b2"}, {"種別": "衆法", "提出回次": "2", "番号": "1", "題名": "c"}]
        merged, added, updated = daily_update.merge_rows(old, new, daily_update.CENSUS_KEY)
        self.assertEqual([r["題名"] for r in merged], ["a", "b2", "c"])
        self.assertEqual((added, updated), (1, 1))

    def test_committed_census_is_fully_labeled(self):
        self.assertEqual(daily_update.unlabeled_laws(), [])

    def test_standing_approvals_are_publishable_only(self):
        approved = daily_update.standing_approvals()
        self.assertTrue(approved)
        self.assertEqual(len(approved), len(set(approved)))


if __name__ == "__main__":
    unittest.main()
