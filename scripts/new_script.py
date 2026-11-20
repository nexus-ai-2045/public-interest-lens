"""scripts/ に新しい入口を雛形から作る。

雛形は最初から argparse で --help を解釈し、docstring を説明に使う。
入口を手で書き始めず、これで作ってから中身を足す（AGENTS.md のルール表）。

使い方：python3 -m scripts.new_script 名前 "1行の説明"
  名前は英小文字・数字・_ だけ（例：build_foo）。同じ名前のファイルがあれば作らずに止まる。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
NAME = re.compile(r"^[a-z][a-z0-9_]*$")

TEMPLATE = '''"""{summary}

使い方：python3 -m scripts.{name} [--dry-run]
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="書き込まずに、何をするかだけ出す")
    args = ap.parse_args(argv)
    if args.dry_run:
        print("ドライラン：まだ何もしない")
        return 0
    raise NotImplementedError("中身を書く")


if __name__ == "__main__":
    sys.exit(main())
'''


def render(name: str, summary: str) -> str:
    return TEMPLATE.format(name=name, summary=summary.strip())


def create(name: str, summary: str, root: Path = SCRIPTS) -> Path:
    if not NAME.match(name):
        raise ValueError(f"名前は英小文字・数字・_ だけ：{name!r}")
    if not summary.strip():
        raise ValueError("1行の説明を渡す")
    path = root / f"{name}.py"
    if path.exists():
        raise FileExistsError(f"もうある：{path.name}")
    path.write_text(render(name, summary), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="入口の名前（例：build_foo）")
    ap.add_argument("summary", help="1行の説明（docstring の先頭になる）")
    a = ap.parse_args(argv)
    try:
        path = create(a.name, a.summary)
    except (ValueError, FileExistsError) as error:
        print(f"作らなかった：{error}", file=sys.stderr)
        return 1
    print(f"作った：scripts/{path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
