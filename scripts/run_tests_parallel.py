#!/usr/bin/env python3
"""tests/ の試験モジュールを、1本ずつ別プロセスで並列に回す（CI の verify が使う）。

`python -m unittest discover -s tests` と同じ試験を、同じ import の形（tests/ を先頭の探索先に置く）で回す。
試験は1本も外さない：tests/test_*.py をすべて並べ、全モジュールの結果を集める。1つでも失敗すれば終了コード 1。
単独プロセスでは約6分かかるので、CPU の数だけ並列にして待ち時間を縮める（試験はどれも一時ディレクトリで動く前提）。

使い方：python scripts/run_tests_parallel.py [--jobs N] [モジュール名 ...]
  モジュール名を渡すとその試験だけ回す（例：test_evaluation_logic）。渡さなければ tests/test_*.py のすべて。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


# 1本で試験時間のほぼ全部（node の段を何度も回す）を占めるモジュール。試験1件ずつ別プロセスに分ける
PER_TEST = {"test_triage_version_pipeline"}


def modules() -> list[str]:
    return sorted(p.stem for p in TESTS.glob("test_*.py"))


def targets(names: list[str]) -> list[str]:
    """回す単位の並び。PER_TEST のモジュールは試験の ID（モジュール.クラス.メソッド）に展開する。"""
    out: list[str] = []
    for n in names:
        if n not in PER_TEST:
            out.append(n)
            continue
        sys.path.insert(0, str(TESTS))
        import unittest

        def ids(suite):
            for t in suite:
                if isinstance(t, unittest.TestSuite):
                    yield from ids(t)
                else:
                    yield t.id()

        out.extend(ids(unittest.defaultTestLoader.loadTestsFromName(n)))
    return out


def run_one(name: str) -> tuple[str, int, str, float]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(TESTS), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    t0 = time.time()
    # モジュール単位は discover で回す（import 時の SkipTest を discover と同じく skip 扱いにするため）。試験 ID は名前指定
    cmd = [sys.executable, "-m", "unittest", "-v", name] if name.count(".") >= 2 else [
        sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", f"{name}.py", "-v"]
    proc = subprocess.run(
        cmd,
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return name, proc.returncode, proc.stdout + proc.stderr, time.time() - t0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2, help="並列数（既定は CPU の数）")
    ap.add_argument("names", nargs="*", help="回す試験モジュール名（省略で全部）")
    args = ap.parse_args(argv)
    names = args.names or modules()
    if not names:
        print("tests/test_*.py が1本も見つからない", file=sys.stderr)
        return 1
    # 長い試験を先に始めると全体が早く終わる。ファイルが大きいほど遅い傾向なので大きい順に並べる
    names = targets(names)
    names = sorted(names, key=lambda n: (0 if n.split(".")[0] in PER_TEST else 1, -(TESTS / f"{n.split('.')[0]}.py").stat().st_size))
    t0 = time.time()
    ran = skipped = 0
    failed: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        for name, code, out, sec in ex.map(run_one, names):
            m = re.search(r"Ran (\d+) tests?", out)
            n = int(m.group(1)) if m else 0
            s = re.search(r"skipped=(\d+)", out)
            ran += n
            skipped += int(s.group(1)) if s else 0
            code = 0 if code == 5 and n == 0 else code  # 試験が0件のモジュールは、discover と同じく成功にする
            print(f"{'ok  ' if code == 0 else 'FAIL'} {name}（{n}件、{sec:.1f}秒）", flush=True)
            if code != 0:
                failed.append((name, out))
    for name, out in failed:
        print(f"\n===== {name} =====\n{out}")
    print(f"\n{len(names)}単位・{ran}件（skip {skipped}件）・{time.time() - t0:.0f}秒・失敗モジュール {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
