#!/usr/bin/env python3
"""CI（.github/workflows/verify.yml）と同じ検査をローカルで回す。

GitHub Actions は課金枠で赤になりがちなので、PR・マージ前の検査をこの1本で代わりにする。
手順は verify.yml の `run:` を読んで実行する（手順の写しを持たない＝CI と食い違わない）。
actions/* の `uses:` 手順と `playwright install` は対象外（ローカルでは Node・Python・内蔵 Chromium が入っている前提）。

使い方：python3 scripts/local_verify.py [--skip e2e,audit] [--list]
  --skip：run の文字列にこの語を含む手順を飛ばす（カンマ区切り）。npm audit は通信が要るので、届かないときだけ飛ばす。
  --list：実行する手順を出すだけ。
終了コード：全手順が成功なら 0、1つでも失敗で 1（失敗しても残りは回す）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"
OUT = ROOT / ".local" / "local-verify"
# CI 専用の手順：ブラウザの取得はクラウド内蔵の Chromium を使うので不要（設計決定0011）
ALWAYS_SKIP = ["playwright install"]


def load_steps(path: Path = WORKFLOW) -> list[dict[str, str]]:
    """verify ジョブの run 手順を (コマンド, 作業ディレクトリ) の並びで返す。

    PyYAML は CI の verify ジョブに入っていない（テストも同じ環境で動く）ので使わず、手順の書き方（1行の `run:` と
    `working-directory:`）だけを標準ライブラリで読む。複数行の run（`|`）は読めないので、見つけたら止まる。
    """
    steps: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_steps = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if re.match(r"\s+steps:\s*$", line):
            in_steps = True
            continue
        if not in_steps:
            continue
        m = re.match(r"\s+- (?:(run|working-directory|uses|name|with)\s*:\s*(.*))?$", line)
        if m:  # 手順の先頭行（`- run: …` など）
            current = {}
            steps.append(current)
            key, value = m.group(1), m.group(2)
        else:
            m = re.match(r"\s{8,}(run|working-directory)\s*:\s*(.*)$", line)
            key, value = (m.group(1), m.group(2)) if m else (None, None)
        if key in ("run", "working-directory") and current is not None:
            if value.strip() in ("|", ">", "|-", ">-"):
                raise SystemExit("verify.yml に複数行の run がある。local_verify.py の読み取りを直す")
            current[key] = value.strip().strip("'\"")
    return [{"run": s["run"], "cwd": s.get("working-directory", ".")} for s in steps if "run" in s]


def select(steps: list[dict[str, str]], skip: list[str]) -> list[dict[str, str]]:
    return [s for s in steps if not any(w and w in s["run"] for w in skip)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip", default="", help="run にこの語を含む手順を飛ばす（カンマ区切り）")
    ap.add_argument("--list", action="store_true", help="実行する手順を出すだけ")
    args = ap.parse_args(argv)
    steps = select(load_steps(), ALWAYS_SKIP + [w.strip() for w in args.skip.split(",")])
    if args.list:
        for s in steps:
            print(f"[{s['cwd']}] {s['run']}")
        return 0
    results = []
    for s in steps:
        t0 = time.time()
        proc = subprocess.run(s["run"], shell=True, cwd=ROOT / s["cwd"])
        ok = proc.returncode == 0
        results.append({"run": s["run"], "cwd": s["cwd"], "ok": ok, "seconds": round(time.time() - t0)})
        print(f"{'合格' if ok else '失敗'}  [{s['cwd']}] {s['run']}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{date.today().isoformat()}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [r for r in results if not r["ok"]]
    print(f"ローカル検査：合格 {len(results) - len(failed)}、失敗 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
