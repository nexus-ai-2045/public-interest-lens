import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import split_shared_speeches as split  # noqa: E402


class KeepStampsTest(unittest.TestCase):
    def row(self, body, stamp, url="u"):
        return {"id": "閣法-1-1", "区分": "説明", "抜粋": body, "URL": url, "取得日時": stamp}

    def test_same_content_keeps_old_stamp(self):
        out = split.keep_stamps([self.row("a", "new")], [self.row("a", "old")])
        self.assertEqual("old", out[0]["取得日時"])

    def test_changed_content_gets_new_stamp(self):
        out = split.keep_stamps([self.row("b", "new")], [self.row("a", "old")])
        self.assertEqual("new", out[0]["取得日時"])

    def test_new_row_keeps_its_stamp(self):
        out = split.keep_stamps([self.row("a", "new")], [])
        self.assertEqual("new", out[0]["取得日時"])


if __name__ == "__main__":
    unittest.main()
