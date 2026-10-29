#!/usr/bin/env python3
"""docs/フィードバックループ.md の5段が、実際に回せる状態かを測る（L5 の「どのループが回っていないか」の点検）。

文書の表（L1〜L5）と、各段が頼る入口・記録の置き場所がそろっているかを見る。
ここで測るのは「回せる仕組みが在るか」と「改善の記録が古びていないか」だけ。ループを回した結果（テストの成否など）は
scripts/local_verify.py と scripts/preflight.py が測る。

使い方：python3 scripts/loop_status.py   （失敗があれば終了コード1。注意は1にしない）
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "フィードバックループ.md"
STALE_DAYS = 31  # L5 は月1。これを超えて記録が無ければ注意
LEVELS = ("L1", "L2", "L3", "L4", "L5")


def loop_rows(text: str) -> dict[str, list[str]]:
    """表の L1〜L5 の行 → セル。"""
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*(L[1-5])\s+[^|]*\|", line)
        if m and m.group(1) not in rows:
            rows[m.group(1)] = [c.strip() for c in line.strip().strip("|").split("|")]
    return rows


def latest_improvement(text: str) -> date | None:
    section = text.split("## 改善の記録", 1)[-1]
    dates = re.findall(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|", section, re.M)
    return max(date.fromisoformat(d) for d in dates) if dates else None


def has_schedule() -> bool:
    return any("schedule:" in p.read_text(encoding="utf-8") for p in (ROOT / ".github" / "workflows").glob("*.yml"))


def check(today: date | None = None) -> list[tuple[str, str, str]]:
    today = today or date.today()
    out: list[tuple[str, str, str]] = []
    text = DOC.read_text(encoding="utf-8")
    rows = loop_rows(text)
    for lv in LEVELS:
        ok = lv in rows and len(rows[lv]) == 5 and all(rows[lv])
        out.append((lv, "合格" if ok else "失敗", "文書の表に周期・回すもの・記録・直す対象がある" if ok else "文書の表に行が無いか、5列が埋まっていない"))
    for lv, paths in {
        "L1": ["scripts/preflight.py", "scripts/local_verify.py"],
        "L2": [".github/workflows/verify.yml", "scripts/roadmap_check.py"],
        "L3": ["scripts/daily_update.py", "docs/学習記録"],
        "L4": ["scripts/release_check.py"],
        "L5": ["scripts/loop_status.py", "docs/ロードマップ.md"],
    }.items():
        missing = [p for p in paths if not (ROOT / p).exists()]
        out.append((lv, "失敗" if missing else "合格", f"入口・記録が無い：{', '.join(missing)}" if missing else "入口・記録の置き場所がある"))
    out.append(("L3", "合格" if has_schedule() else "注意", "定期実行（schedule）のワークフローがある" if has_schedule() else "定期実行のワークフローが main に無い"))
    last = latest_improvement(text)
    if last is None:
        out.append(("L5", "失敗", "改善の記録が1行も無い"))
    else:
        age = (today - last).days
        out.append(("L5", "合格" if age <= STALE_DAYS else "注意", f"改善の記録の最新は {last}（{age}日前）"))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "roadmap_check.py")], capture_output=True, text=True)
    out.append(("L5", "合格" if r.returncode == 0 else "失敗", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "roadmap_check が出力なし"))
    return out


def main() -> int:
    results = check()
    for lv, status, detail in results:
        print(f"{status}  {lv}  {detail}")
    failed = sum(s == "失敗" for _, s, _ in results)
    warn = sum(s == "注意" for _, s, _ in results)
    print(f"ループの点検：合格 {len(results) - failed - warn}、注意 {warn}、失敗 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
