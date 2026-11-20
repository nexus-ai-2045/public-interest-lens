"""Git に置かない派生物（設計決定0022）を、入力から決まった順で作る入口。

作るもの（前の出力が後の入力になる順）：
  inputs：物価の換算表 price-index.json → 公開ランキング ranking.json → 賛否 votes.json
  derived：曝露ランキング（議員の側。設計決定0027・0028）data/derived/exposure-v1/exposure-ranking.json（公開ディレクトリには置かない）→ 法律の一覧 laws.json・laws-detail/・law-names.json
           → 暫定評価 provisional.json → グラフ用の集計 charts.json
既定は、出力が無い・入力（data/ と scripts/）より古い・前の出力を作り直したものだけ作る（--force で全部作り直す）。
ranking.json だけは、入力と出典チェックの結果と中身を結んだ公開ハッシュが一致するときだけ飛ばす。
CI・アプリの prebuild/pretest・sync_main から呼ぶ。環境変数 KOKUZOKU_SKIP_GENERATE=1 なら何もしない（架空入力の検査用）。
公開版のビルド（VITE_PUBLIC_SITE=true の --public-build）はこの変数を無視し、出典チェックから ranking.json を作り直す。
入力は Git の中のファイルだけ。会議録の全文（speeches.csv）は要らない（法律の一覧は表 speech-facts.csv から作る）。

使い方（リポジトリのルートで）：python3 scripts/generate_artifacts.py [--stage inputs|derived] [--force]
"""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.publish_fingerprint import ranking_is_fresh  # noqa: E402

DIST = ROOT / "app" / "public" / "distribution"
PY = sys.executable
LOCK_PATH = ROOT / "data" / "db" / ".generate-artifacts.lock"

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
    # 評価台帳は全法律の結果（all-laws-v1）から作る。成立法が増えたとき（#207 の第222回）に作り直し漏れで台帳が欠けないよう、生成に入れる。
    ("derived", DIST / "ledger-summary.json", [PY, "scripts/build_evaluation_ledger.py", "build"]),
]
# 段の主出力のほかに、同じコマンドが data/ に書く出力。入力に数えると毎回作り直しになる
SIDE_OUTPUTS = {ROOT / "data" / "derived" / "evaluation-ledger-v1" / "ledger.csv"}


# 入力の置き場。取得の原本・データベース・キャッシュは見ない
INPUT_ROOTS = [ROOT / "data", ROOT / "scripts", ROOT / "app" / "src"]
SKIP_DIRS = {"raw", "db", "__pycache__", "generated"}
# 計算のコード（app/src）は入力に数える（曝露ランキングなどは TS で計算する）。テストは出力を変えないので数えない。
SKIP_FILES = re.compile(r"\.test\.tsx?$|\.css$")


def newest_input() -> float:
    newest = 0.0
    # 自分の出力（曝露ランキングは data/ の下に置く）は入力に数えない。数えると毎回いちばん新しい入力になり、全段を作り直してしまう
    outputs = {str(output) for _, output, _ in STEPS} | {str(p) for p in SIDE_OUTPUTS}
    for root in INPUT_ROOTS:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if SKIP_FILES.search(name) or os.path.join(folder, name) in outputs:
                    continue
                newest = max(newest, os.stat(os.path.join(folder, name)).st_mtime)
    return newest


@contextmanager
def exclusive_generation():
    """原因: 共有の sqlite を同時に開き直すと disk I/O error になる。生成は1本ずつにする。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _generate(args: argparse.Namespace, public: bool) -> int:
    newest = newest_input()
    rebuilt = False  # 前の出力の中身が変わったら、後ろは入力が変わったことになる
    for stage, output, command in STEPS:
        if args.stage and stage != args.stage and not public:
            continue
        if output.name == "ranking.json":
            # 原因: mtime が新しければ ranking.json を作り直さないので、確かさを手で「高」にしても dist に入る。
            stale = public or not ranking_is_fresh(output)
        else:
            stale = not output.exists() or output.stat().st_mtime < newest
        if not (args.force or stale or rebuilt):
            continue
        print(f"作る: {output.name}", flush=True)
        before = output.read_bytes() if output.is_file() else None
        done = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL)
        if done.returncode != 0:
            print(f"失敗: {output.name}（{' '.join(command)}）", file=sys.stderr)
            return done.returncode
        after = output.read_bytes() if output.is_file() else None
        if before != after:
            rebuilt = True
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["inputs", "derived"], help="この段だけ作る（既定は両方）")
    parser.add_argument("--force", action="store_true", help="出力があっても作り直す")
    parser.add_argument("--public-build", action="store_true", help="公開版のビルドから呼ぶ。出典チェックの公開ハッシュを確かめる")
    args = parser.parse_args(argv)
    public = args.public_build and os.environ.get("VITE_PUBLIC_SITE") == "true"
    if args.public_build and not public:
        return 0
    # 公開版では prebuild が先に同じ入口を呼ぶ。ビルド本体の --public-build が生成を引き受ける。
    if os.environ.get("VITE_PUBLIC_SITE") == "true" and not args.public_build:
        return 0
    # 原因: KOKUZOKU_SKIP_GENERATE=1 は公開版のビルドでも生成と出典チェックを即 return で飛ばす。
    if os.environ.get("KOKUZOKU_SKIP_GENERATE") == "1" and not public:
        return 0
    with exclusive_generation():
        return _generate(args, public)


if __name__ == "__main__":
    raise SystemExit(main())
