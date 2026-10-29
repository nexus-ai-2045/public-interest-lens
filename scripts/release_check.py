#!/usr/bin/env python3
"""リリース前の総点検（L4）。既存の検査を決まった順で回し、1つの結果にまとめる。

本番への配信はしない。配信の手順は docs/operations.md の「リリース」を正本とする。
順番：ループの点検 → 事前チェック（スモーク・E2E つき）→ CI と同じ検査（ローカル）。
どれか1つでも失敗ならリリースしない（終了コード1）。結果は .local/release-check/<日付>.json に残る。

使い方：python3 scripts/release_check.py [--offline] [--skip-verify]
  --offline：preflight の通信先確認を飛ばす。 --skip-verify：local_verify を飛ばす（直前に回したときだけ）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local" / "release-check"


def plan(offline: bool, skip_verify: bool) -> list[tuple[str, list[str]]]:
    py = sys.executable
    steps = [
        ("ループの点検", [py, "scripts/loop_status.py"]),
        ("事前チェック（スモーク・E2E）", [py, "scripts/preflight.py", "--smoke"] + (["--offline"] if offline else [])),
    ]
    if not skip_verify:
        steps.append(("CI と同じ検査", [py, "scripts/local_verify.py"]))
    return steps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args(argv)
    results = []
    for name, cmd in plan(args.offline, args.skip_verify):
        ok = subprocess.run(cmd, cwd=ROOT).returncode == 0
        results.append({"step": name, "ok": ok})
        print(f"{'合格' if ok else '失敗'}  {name}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{date.today().isoformat()}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [r["step"] for r in results if not r["ok"]]
    print("リリース前の総点検：" + ("すべて合格。配信してよい" if not bad else "失敗あり、配信しない（" + "、".join(bad) + "）"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
