"""PR の題名と本文を検査する（CI の pr-text と、手元で PR を作る前に同じものを回す）。

落とすもの：
- 題名に日本語（かな・漢字）が無い（AGENTS.md「PR の題名と見出しは日本語」）。
- 本文の見出し（# で始まる行。コードの囲みの中は見ない）に日本語が無い。

使い方：
  python3 scripts/check_pr_text.py --title "題名" [--body-file 本文.md]
  python3 scripts/check_pr_text.py --from-event "$GITHUB_EVENT_PATH"   # CI（pull_request のイベント JSON）
終了コード：合格 0、不合格 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def headings(body: str) -> list[str]:
    out, fenced = [], False
    for line in body.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced and HEADING.match(line):
            out.append(line.strip())
    return out


def problems(title: str, body: str) -> list[str]:
    found = []
    if not JAPANESE.search(title):
        found.append(f"題名が日本語でない：{title!r}（題名は日本語で書く。dependabot の PR も題名を直してから通す）")
    for h in headings(body):
        if not JAPANESE.search(h):
            found.append(f"見出しが日本語でない：{h!r}")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title")
    ap.add_argument("--body-file", type=Path)
    ap.add_argument("--from-event", type=Path, help="GitHub の pull_request イベントの JSON")
    a = ap.parse_args(argv)
    if a.from_event:
        pr = json.loads(a.from_event.read_text(encoding="utf-8"))["pull_request"]
        title, body = pr.get("title") or "", pr.get("body") or ""
    elif a.title is not None:
        title = a.title
        body = a.body_file.read_text(encoding="utf-8") if a.body_file else ""
    else:
        ap.error("--title か --from-event を渡す")
    found = problems(title, body)
    for p in found:
        print(f"不合格：{p}")
    if not found:
        print("合格：PR の題名と本文")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
