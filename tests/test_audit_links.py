"""未結合データの台帳（scripts/audit_links.py）の出力が最新の入力と一致すること。"""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_summary_is_current_and_counts_add_up():
    path = ROOT / "data/derived/link-audit/summary.csv"
    before = path.read_text(encoding="utf-8")
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts/audit_links.py")], check=True, capture_output=True)
        assert path.read_text(encoding="utf-8") == before, "summary.csv が古い。python3 scripts/audit_links.py で作り直す"
    finally:
        path.write_text(before, encoding="utf-8")
    for r in csv.DictReader(open(path, encoding="utf-8")):
        assert int(r["空欄"]) + int(r["台帳に無い"]) <= int(r["行数"]), r["関係"]
