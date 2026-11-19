"""作業ツリーのデータが、基準のコミットより大きく減っていないかを確かめる（週2回の自動更新が PR を出す前の守り）。

取得が欠けたまま再計算すると、main より貧しい結果が「差分」として PR になる
（2026-11 の #179・#189・#191：自動の関与の表が 12,721 行から 582 行に減った）。
ここでは Git が追っているファイルだけを、基準のコミットの中身と作業ツリーで比べる。

減ったと判定するもの：
- 消えたファイル・空になったファイル
- CSV：基準が --min-rows 行以上あり、行数か、中身のあるセルの数が --max-drop を超えて減った
  （行は残って中身だけ空になる取得の切れも拾う）
- それ以外（JSON など）：基準が --min-bytes バイト以上あり、大きさが --max-drop-bytes を超えて減った

ロジックを変えて意図して減らすときは、その変更の PR で派生データを作り直して取り込む（基準の側を新しくする）。
自動更新をそれでも通すときは --allow で警告だけにし、減ったファイルの一覧を PR の本文に載せる。

使い方（リポジトリのルートで）：python3 scripts/check_data_shrink.py [--base HEAD] [--allow] [パス ...]
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ["data", "app/public"]
MAX_DROP = 0.10
MIN_ROWS = 50
MAX_DROP_BYTES = 0.30
MIN_BYTES = 10_000


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str


def csv_shape(data: bytes) -> tuple[int, int]:
    """見出しを除いた行数と、中身のあるセルの数。"""
    csv.field_size_limit(sys.maxsize)
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"), newline="")))[1:]
    return len(rows), sum(1 for row in rows for cell in row if cell.strip())


def _dropped(before: int, after: int, max_drop: float) -> bool:
    return after < before * (1 - max_drop)


def judge(path: str, before: bytes, after: bytes | None, *, max_drop: float = MAX_DROP, min_rows: int = MIN_ROWS,
          max_drop_bytes: float = MAX_DROP_BYTES, min_bytes: int = MIN_BYTES) -> Finding | None:
    """基準の中身 before と今の中身 after（消えていれば None）を比べ、大きく減っていれば理由を返す。"""
    if after is None:
        return Finding(path, "ファイルが消えた")
    if before and not after.strip():
        return Finding(path, "ファイルが空になった")
    if path.endswith(".csv"):
        rows_before, cells_before = csv_shape(before)
        rows_after, cells_after = csv_shape(after)
        if rows_before < min_rows:
            return None
        if _dropped(rows_before, rows_after, max_drop):
            return Finding(path, f"行数 {rows_before:,} → {rows_after:,}")
        if _dropped(cells_before, cells_after, max_drop):
            return Finding(path, f"中身のあるセル {cells_before:,} → {cells_after:,}（行数は {rows_before:,} → {rows_after:,}）")
        return None
    if len(before) >= min_bytes and _dropped(len(before), len(after), max_drop_bytes):
        return Finding(path, f"大きさ {len(before):,} → {len(after):,} バイト")
    return None


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def changed(root: Path, base: str, paths: list[str]) -> list[tuple[str, str]]:
    """基準から変わった、Git が追っているファイルの（状態, パス）。名前の変更は「消えた＋増えた」として数える。"""
    out = _git(root, "diff", "--name-status", "--no-renames", "-z", base, "--", *paths).decode("utf-8")
    parts = out.split("\0")
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def check(root: Path = ROOT, base: str = "HEAD", paths: list[str] | None = None, **limits: float) -> list[Finding]:
    findings = []
    for status, path in changed(root, base, paths or DEFAULT_PATHS):
        if status == "A":
            continue
        before = _git(root, "show", f"{base}:{path}")
        after = None if status == "D" else (root / path).read_bytes()
        finding = judge(path, before, after, **limits)
        if finding:
            findings.append(finding)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", default=DEFAULT_PATHS, help="比べる場所（既定は data と app/public）")
    parser.add_argument("--base", default="HEAD", help="基準のコミット（既定は HEAD）")
    parser.add_argument("--max-drop", type=float, default=MAX_DROP, help="CSV の行数・セル数で許す減り方の割合（既定 0.10）")
    parser.add_argument("--min-rows", type=int, default=MIN_ROWS, help="これより行の少ない CSV は割合で見ない（既定 50）")
    parser.add_argument("--max-drop-bytes", type=float, default=MAX_DROP_BYTES, help="CSV 以外の大きさで許す減り方の割合（既定 0.30）")
    parser.add_argument("--min-bytes", type=int, default=MIN_BYTES, help="これより小さい CSV 以外のファイルは割合で見ない（既定 10000）")
    parser.add_argument("--allow", action="store_true", help="減っていても失敗にせず、一覧だけ出す（意図した減少を通すとき）")
    args = parser.parse_args(argv)
    findings = check(ROOT, args.base, args.paths, max_drop=args.max_drop, min_rows=args.min_rows,
                     max_drop_bytes=args.max_drop_bytes, min_bytes=args.min_bytes)
    if not findings:
        print(f"大きく減ったデータなし（基準 {args.base}）")
        return 0
    print(f"基準 {args.base} より大きく減ったデータ {len(findings)}件：")
    for finding in findings:
        print(f"- {finding.path}：{finding.reason}")
    if args.allow:
        print("--allow が付いているので失敗にしない。")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
