"""採決ごとの会派（scripts/build_vote_parties.py）が、いまの投票の記録から作り直したものと一致し、回次の途中の会派の移動を採決ごとに引く。"""
from __future__ import annotations

import csv
import unittest

from scripts import build_vote_parties


class VotePartiesTest(unittest.TestCase):
    def test_committed_file_is_current(self) -> None:
        with build_vote_parties.OUT.open(encoding="utf-8", newline="") as f:
            committed = list(csv.DictReader(f))
        self.assertEqual(committed, build_vote_parties.build(), "vote-parties.csv が古い。python3 scripts/build_vote_parties.py で作り直す")

    def test_party_is_taken_per_vote(self) -> None:
        # 同じ回次の名簿に会派が2つある議員でも、その採決の時の会派になる（第189回の脇雅史は、この採決では自由民主党）。
        rows = {(r["投票ID"], r["議員名"]): r["会派"] for r in build_vote_parties.build()}
        self.assertEqual(rows[("189-0529-v001", "脇雅史")], "自由民主党")


if __name__ == "__main__":
    unittest.main()
