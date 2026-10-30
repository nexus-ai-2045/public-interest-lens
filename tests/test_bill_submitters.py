"""未成立法案の提出者を人物IDに結ぶ処理の検査（data/derived/unenacted-bills-v1/submitters.csv の整合）。"""
from __future__ import annotations

import csv
from pathlib import Path

from scripts.build_bill_submitters import kan

ROOT = Path(__file__).resolve().parents[1]


def test_kan_numbers():
    assert kan("三") == 3 and kan("十二") == 12 and kan("百五") == 105 and kan("7") == 7


def test_every_unenacted_member_bill_has_one_row_and_reason_when_unlinked():
    scale = [r["id"] for r in csv.DictReader(open(ROOT / "data/derived/unenacted-bills-v1/scale.csv", encoding="utf-8"))
             if r["種別"] in ("衆法", "参法")]
    rows = list(csv.DictReader(open(ROOT / "data/derived/unenacted-bills-v1/submitters.csv", encoding="utf-8")))
    assert [r["id"] for r in rows] == scale
    for r in rows:
        assert r["筆頭の人物ID"] or r["結べなかった理由"], r["id"]
