"""人物台帳に、字体だけが違う分裂（斎藤／齋藤 など）が残っていないこと。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_glyph_only_splits_in_persons():
    done = subprocess.run([sys.executable, str(ROOT / "scripts/check_roster_duplicates.py"), "--strict"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout
