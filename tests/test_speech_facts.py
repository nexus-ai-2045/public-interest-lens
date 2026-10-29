import unittest

from scripts.build_speech_facts import derive


def row(law_id, explain="", oppose=""):
    return {"id": law_id, "説明のURL": explain, "説明の発言者": "甲" if explain else "", "説明の日付": "2020-01-01" if explain else "",
            "反対のURL": oppose, "反対の発言者": "乙" if oppose else "", "反対の日付": "2020-02-02" if oppose else ""}


class SpeechFactsTest(unittest.TestCase):
    def test_law_without_any_speech_is_left_out(self):
        self.assertEqual(derive({"閣法-1-1": row("閣法-1-1")}, set()), [])

    def test_speech_used_by_one_bill_is_not_shared(self):
        rows = derive({"閣法-1-1": row("閣法-1-1", "u1", "u2")}, set())
        self.assertEqual(rows[0]["区別できない"], "")
        self.assertEqual(rows[0]["説明の発言者"], "甲")

    def test_speech_used_by_two_bills_is_shared_unless_split_with_the_current_url(self):
        speeches = {"閣法-1-1": row("閣法-1-1", "u1"), "閣法-1-2": row("閣法-1-2", "u1")}
        self.assertEqual([r["区別できない"] for r in derive(speeches, set())], ["説明", "説明"])
        split = {("閣法-1-1", "説明", "u1")}
        self.assertEqual([r["区別できない"] for r in derive(speeches, split)], ["", "説明"])
        stale = {("閣法-1-1", "説明", "old-url")}
        self.assertEqual([r["区別できない"] for r in derive(speeches, stale)], ["説明", "説明"])


if __name__ == "__main__":
    unittest.main()
