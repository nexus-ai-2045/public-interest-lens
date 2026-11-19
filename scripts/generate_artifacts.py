"""Git に置かない派生物（設計決定0022）を、入力から決まった順で作る入口。

作るもの（前の出力が後の入力になる順）：
  inputs：物価の換算表 price-index.json → 公開ランキング ranking.json → 賛否 votes.json
  derived：曝露ランキング（議員の側。設計決定0027・0028）data/derived/exposure-v1/exposure-ranking.json（公開ディレクトリには置かない）→ 法律の一覧 laws.json・laws-detail/・law-names.json
           → 暫定評価 provisional.json → グラフ用の集計 charts.json
既定は、出力が無い・入力（data/ と scripts/）より古い・前の出力を作り直したものだけ作る（--force で全部作り直す）。
CI・アプリの prebuild/pretest・sync_main から呼ぶ。環境変数 KOKUZOKU_SKIP_GENERATE=1 なら何もしない（架空入力の検査用）。
入力は Git の中のファイルだけ。会議録の全文（speeches.csv）は要らない（法律の一覧は表 speech-facts.csv から作る）。

使い方（リポジトリのルートで）：python3 scripts/generate_artifacts.py [--stage inputs|derived] [--force]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "app" / "public" / "distribution"
PY = sys.executable

# (段, 出力, コマンド)
STEPS = [
    ("inputs", DIST / "price-index.json", [PY, "scripts/build_price_index.py"]),
    ("inputs", DIST / "ranking.json", [PY, "scripts/source_check.py", "--generate-ranking"]),
    ("inputs", DIST / "votes.json", [PY, "scripts/build_public_votes.py"]),
    # 曝露ランキングは公開ディレクトリ（app/public/）に置かない：ビルドに乗ると、画面を隠していても公開サイトから取れてしまう。
    # 表示を解く（設計決定0008 のねくの確認の後）ときに、公開データへ移す。
    ("derived", ROOT / "data" / "derived" / "exposure-v1" / "exposure-ranking.json", ["node", "scripts/build_exposure_ranking.mjs"]),
    ("derived", DIST / "laws.json", [PY, "scripts/build_laws_catalog.py"]),
    ("derived", DIST / "law-outcomes.json", [PY, "scripts/build_law_outcomes_view.py"]),
    ("derived", DIST / "provisional.json", [PY, "scripts/build_provisional.py"]),
    ("derived", DIST / "unenacted.json", [PY, "scripts/build_public_unenacted.py"]),
    ("derived", DIST / "charts.json", [PY, "scripts/build_database.py"]),
]


# 入力の置き場。取得の原本・データベース・キャッシュは見ない
INPUT_ROOTS = [ROOT / "data", ROOT / "scripts", ROOT / "app" / "src"]
SKIP_DIRS = {"raw", "db", "__pycache__", "generated"}
# 計算のコード（app/src）は入力に数える（曝露ランキングなどは TS で計算する）。テストは出力を変えないので数えない。
SKIP_FILES = re.compile(r"\.test\.tsx?$|\.css$")


def newest_input() -> float:
    newest = 0.0
    # 自分の出力（曝露ランキングは data/ の下に置く）は入力に数えない。数えると毎回いちばん新しい入力になり、全段を作り直してしまう
    outputs = {str(output) for _, output, _ in STEPS}
    for root in INPUT_ROOTS:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if SKIP_FILES.search(name) or os.path.join(folder, name) in outputs:
                    continue
                newest = max(newest, os.stat(os.path.join(folder, name)).st_mtime)
    return newest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["inputs", "derived"], help="この段だけ作る（既定は両方）")
    parser.add_argument("--force", action="store_true", help="出力があっても作り直す")
    args = parser.parse_args(argv)
    if os.environ.get("KOKUZOKU_SKIP_GENERATE") == "1":
        return 0
    newest = newest_input()
    rebuilt = False  # 前の出力を作り直したら、後ろは入力が変わったことになる
    for stage, output, command in STEPS:
        if args.stage and stage != args.stage:
            continue
        stale = not output.exists() or output.stat().st_mtime < newest
        if not (args.force or stale or rebuilt):
            continue
        rebuilt = True
        print(f"作る: {output.name}", flush=True)
        done = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL)
        if done.returncode != 0:
            print(f"失敗: {output.name}（{' '.join(command)}）", file=sys.stderr)
            return done.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
