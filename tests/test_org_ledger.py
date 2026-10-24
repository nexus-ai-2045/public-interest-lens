"""団体の帳簿と省庁の抵抗の件数（scripts/build_org_ledger.py）：表がいまの入力から作り直したものと一致し、個人の名前を出さないこと。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts import build_org_ledger as ol


class OrgLedgerTest(unittest.TestCase):
    def test_names(self) -> None:
        self.assertEqual(ol.ministries("厚生労働省・観光庁"), ["厚生労働省", "観光庁"])
        self.assertEqual(ol.ministries("厚生労働省（氏名記載なし）"), ["厚生労働省"])
        self.assertEqual(ol.org_name("日本薬剤師会（議事録の表記）"), "日本薬剤師会")
        self.assertEqual(ol.org_name("日本ホテル協会 専務理事"), "日本ホテル協会")
        self.assertEqual(ol.org_name("（議事録に肩書記載なし）"), "（団体名の記載なし）")

    def test_committed_tables_are_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved = ol.OUT_MINISTRY, ol.OUT_ORG
            ol.OUT_MINISTRY, ol.OUT_ORG = Path(tmp) / "m.csv", Path(tmp) / "o.csv"
            try:
                ol.build()
                fresh = ol.OUT_MINISTRY.read_text(encoding="utf-8"), ol.OUT_ORG.read_text(encoding="utf-8")
            finally:
                ol.OUT_MINISTRY, ol.OUT_ORG = saved
        self.assertEqual((ol.OUT_MINISTRY.read_text(encoding="utf-8"), ol.OUT_ORG.read_text(encoding="utf-8")), fresh,
                         "org-ledger-v1 の表が古い。python3 scripts/build_org_ledger.py で作り直す")

    def test_people_are_not_named(self) -> None:
        with ol.OUT_ORG.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r["区分"] in ("学者", "有識者", "省庁") or r["区分"].startswith("その他（弁護士"):
                    self.assertIn("名前は出さない", r["団体"], r)


if __name__ == "__main__":
    unittest.main()
