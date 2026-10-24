#!/usr/bin/env python3
"""docs/ロードマップ.md の「残りの項目」表と docs/adr/ の形を検査し、残りの件数を出す。

- 各行に担当と状態があり、状態は決まった4つのどれか。
- 「済」の行には根拠がある。
- ADR は 0001 から欠番なしで並び、本文に日付と状態がある。

使い方：python3 scripts/roadmap_check.py   （問題があれば終了コード1）
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "ロードマップ.md"
ADR_DIR = ROOT / "docs" / "adr"
STATES = ("済", "進行中", "未着手", "ねくさん待ち")


def _table_lines(text: str) -> list[str]:
    """残りの項目の表のデータ行（見出し行と区切り行を除く）。"""
    if "## 残りの項目" not in text:
        return []
    section = text.split("## 残りの項目", 1)[1].split("\n## ", 1)[0]
    # 見出し行から節の終わりまでを表とみなし、空でない行はすべて行として扱う（先頭の | が欠けた行や、空行の後の行も拾う）
    lines, in_table = [], False
    for raw in section.splitlines():
        line = raw.strip()
        in_table = in_table or line.startswith("|")
        if in_table and line:
            lines.append(line)
    return [l for l in lines[1:] if not re.fullmatch(r"[|\s:-]+", l)]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip("|").split("|")]


def roadmap_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for line in _table_lines(text):
        cells = _cells(line)
        if line.startswith("|") and line.endswith("|") and len(cells) == 5 and re.fullmatch(r"R\d+", cells[0]):
            rows.append(dict(zip(("id", "item", "owner", "state", "evidence"), cells)))
    return rows


def check_roadmap(text: str) -> list[str]:
    problems = []
    for line in _table_lines(text):
        cells = _cells(line)
        framed = line.startswith("|") and line.endswith("|")
        if not framed or len(cells) != 5 or not re.fullmatch(r"R\d+", cells[0]):
            problems.append(f"形の崩れた行（| で始まり | で終わる、列は5つ、番号は R+数字）：{line}")
    rows = roadmap_rows(text)
    if not rows:
        return ["残りの項目の表が見つからない"]
    ids = [r["id"] for r in rows]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"{dup}：番号が重複")
    numbers = sorted({int(i[1:]) for i in ids})
    # 末尾の行が消えても気づけるよう、最後の番号は表とは別の行で宣言する。
    declared = re.search(r"最後の番号\s*[:：]\s*R(\d+)", text)
    if not declared:
        problems.append("「最後の番号：R…」の行が無い（末尾の行が消えたことを検出するために要る）")
        last = numbers[-1]
    else:
        last = int(declared.group(1))
        if numbers[-1] != last:
            problems.append(f"最後の番号の宣言 R{last} と表の最後 R{numbers[-1]} が違う（行を足したら宣言も上げる）")
    missing = sorted(set(range(1, max(last, numbers[-1]) + 1)) - set(numbers))
    if missing:
        problems.append("欠番（消えた行）：" + "・".join(f"R{n}" for n in missing))
    for r in rows:
        if not r["owner"]:
            problems.append(f"{r['id']}：担当が空")
        if r["state"] not in STATES:
            problems.append(f"{r['id']}：状態「{r['state']}」は {'・'.join(STATES)} のどれでもない")
        if r["state"] == "済" and not r["evidence"]:
            problems.append(f"{r['id']}：済なのに根拠が空")
    return problems


def check_adrs(adr_dir: Path) -> list[str]:
    problems = []
    files = sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    for stray in sorted(set(adr_dir.glob("*.md")) - set(files)):
        if stray.name.lower() not in {"readme.md", "template.md"}:
            problems.append(f"{stray.name}：ADR のファイル名は「4桁の番号-名前.md」にする")
    numbers = [int(f.name[:4]) for f in files]
    if not files:
        problems.append("ADR が1件も無い")
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"ADR の番号が欠番か重複：{numbers}")
    for f in files:
        # 題の直後（先頭6行以内）に「日付：」で始まる行を置き、同じ行に「状態：」を書く
        meta = [l for l in f.read_text(encoding="utf-8").splitlines()[:6] if re.match(r"日付\s*[:：]", l)]
        if not meta:
            problems.append(f"{f.name}：題の直後に「日付：」の行が無い")
        elif not re.match(r"日付\s*[:：]\s*[^。、\s]", meta[0]):
            problems.append(f"{f.name}：「日付：」の値が空")
        elif not re.search(r"状態\s*[:：]\s*[^。、\s]", meta[0]):
            problems.append(f"{f.name}：「日付：」の行に「状態：」とその値が無い")
    return problems


def main() -> int:
    text = ROADMAP.read_text(encoding="utf-8")
    problems = check_roadmap(text) + check_adrs(ADR_DIR)
    counts = Counter(r["state"] for r in roadmap_rows(text))
    print("ロードマップ：" + "、".join(f"{s} {counts.get(s, 0)}" for s in STATES))
    for p in problems:
        print(f"問題：{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
