"""閣法の所管の省庁（scripts/build_ministry_bills.py）：肩書から省庁を決める決まりと、配布している表がいまの入力から作り直したものと一致すること。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts import build_ministry_bills as mb
from _data_gate import requires_data  # noqa: E402


class MinistryOfTest(unittest.TestCase):
    def test_titles(self) -> None:
        self.assertEqual(mb.ministry_of("通商産業大臣"), ("通商産業省", "経済産業省"))
        self.assertEqual(mb.ministry_of("厚生労働副大臣"), ("厚生労働省", "厚生労働省"))
        self.assertEqual(mb.ministry_of("農林水産政務次官"), ("農林水産省", "農林水産省"))
        self.assertEqual(mb.ministry_of("国務大臣（内閣府特命担当大臣（金融））"), ("金融庁", "金融庁"))
        # 兼務は先頭の役職（説明した立場）を取る。
        self.assertEqual(mb.ministry_of("経済産業大臣・内閣府特命担当大臣（原子力損害賠償・廃炉等支援機構）"), ("経済産業省", "経済産業省"))
        self.assertIsNone(mb.ministry_of("国務大臣"))

    def test_finance_and_fsa(self) -> None:
        # 財務大臣と金融担当の兼務：税・関税・国際機関の法律は財務省、金融の法律は金融庁。
        both = "財務大臣・内閣府特命担当大臣（金融）"
        self.assertEqual(mb.ministry_of(both, "所得税法等の一部を改正する法律案"), ("財務省", "財務省"))
        self.assertEqual(mb.ministry_of(both, "地方法人税法案"), ("財務省", "財務省"))
        self.assertEqual(mb.ministry_of(both, "国際金融公社への加盟に伴う措置に関する法律の一部を改正する法律案"), ("財務省", "財務省"))
        self.assertEqual(mb.ministry_of(both, "株式会社日本政策投資銀行法の一部を改正する法律案"), ("財務省", "財務省"))
        self.assertEqual(mb.ministry_of(both, "金融商品取引法等の一部を改正する法律案"), ("金融庁", "金融庁"))
        self.assertEqual(mb.ministry_of(both, "保険業法の一部を改正する法律案"), ("金融庁", "金融庁"))
        # 兼務でない肩書は題名を見ない。
        self.assertEqual(mb.ministry_of("財務大臣", "金融商品取引法等の一部を改正する法律案"), ("財務省", "財務省"))
        self.assertEqual(mb.ministry_of("内閣府特命担当大臣（金融・経済財政政策）", "所得税法等の一部を改正する法律案"), ("金融庁", "金融庁"))

    def test_every_title_is_registered(self) -> None:
        """会議録の応答は外部資料として登録してから使う（AGENTS.md）。表のどの行にも外部資料ID がある。"""
        with mb.POSITIONS.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(rows)
        for r in rows:
            self.assertRegex(r["外部資料ID"], r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{12}$", r["法律ID"])


class CommittedTableTest(unittest.TestCase):
    @requires_data("speeches")
    def test_committed_table_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out, mb.OUT = mb.OUT, Path(tmp) / "cabinet-bills.csv"
            try:
                mb.build()
                fresh = mb.OUT.read_text(encoding="utf-8")
            finally:
                mb.OUT = out
        self.assertEqual(out.read_text(encoding="utf-8"), fresh, "cabinet-bills.csv が古い。python3 scripts/build_ministry_bills.py build で作り直す")
        with out.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            self.assertEqual(bool(r["所管_今"]), not r["決め方"].startswith("決まらない"), r["法律ID"])


class MissingSpeechesTest(unittest.TestCase):
    """speeches.csv は Git に入っていない取得物。無いときは既存の生成物を残して続ける（無ければ止める）。"""

    def test_missing_speeches_keeps_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            speeches, out = mb.SPEECHES, mb.OUT
            mb.SPEECHES, mb.OUT = Path(tmp) / "none.csv", Path(tmp) / "cabinet-bills.csv"
            try:
                with self.assertRaises(SystemExit):
                    mb.build()
                mb.OUT.write_text("keep", encoding="utf-8")
                mb.build()
                self.assertEqual(mb.OUT.read_text(encoding="utf-8"), "keep")
            finally:
                mb.SPEECHES, mb.OUT = speeches, out


if __name__ == "__main__":
    unittest.main()
