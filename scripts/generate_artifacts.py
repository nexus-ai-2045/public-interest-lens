"""Git に置かない派生物（設計決定0022）を、入力から決まった順で作る入口。

作るもの（前の出力が後の入力になる順）：
  inputs：物価の換算表 price-index.json → 公開ランキング ranking.json → 賛否 votes.json
  derived：議員ページ members.json → 全議員の表 members-reference.json → グラフ用の集計 charts.json
既定は、出力が無いものだけ作る（--force で全部作り直す）。CI・アプリの prebuild/pretest・sync_main から呼ぶ。
入力は Git の中のファイルだけ。会議録の全文（speeches.csv）は要らない。

使い方（リポジトリのルートで）：python3 scripts/generate_artifacts.py [--stage inputs|derived] [--force]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "app" / "public" / "distribution"
PY = sys.executable
ATTRIBUTIONS = Path(tempfile.gettempdir()) / "reference-attributions.csv"

# (段, 出力, コマンド)
STEPS = [
    ("inputs", DIST / "price-index.json", [PY, "scripts/build_price_index.py"]),
    ("inputs", DIST / "ranking.json", [PY, "scripts/source_check.py", "--generate-ranking"]),
    ("inputs", DIST / "votes.json", [PY, "scripts/build_public_votes.py"]),
    ("derived", DIST / "members.json", ["node", "scripts/build_public_members.mjs"]),
    ("derived", DIST / "members-reference.json", ["node", "scripts/build_reference_members.mjs", "--attributions", str(ATTRIBUTIONS)]),
    ("derived", DIST / "charts.json", [PY, "scripts/build_database.py"]),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["inputs", "derived"], help="この段だけ作る（既定は両方）")
    parser.add_argument("--force", action="store_true", help="出力があっても作り直す")
    args = parser.parse_args(argv)
    for stage, output, command in STEPS:
        if args.stage and stage != args.stage:
            continue
        if output.exists() and not args.force:
            continue
        print(f"作る: {output.name}", flush=True)
        done = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL)
        if done.returncode != 0:
            print(f"失敗: {output.name}（{' '.join(command)}）", file=sys.stderr)
            return done.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
