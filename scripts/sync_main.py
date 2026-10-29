#!/usr/bin/env python3
"""作業ブランチを最新の main に載せ直し、main が進んで古くなった生成物を作り直す（マージ前の定型）。

main が進むたびに、charts.json など「Git に入れた生成物」が古くなってテストが赤になり、手で作り直していた。
手順：未コミットが無いことを確かめる → origin/main を rebase → 生成物だけが衝突したら main 側を取り、作り直して続ける
→ 作り直しで差分が出たら1コミットにする。生成物以外が衝突したら rebase を中止して理由を出す（人・担当スレッドが直す）。
生成の入口は GENERATED に1行足すだけで増やせる（Git の中のデータだけから作れるものに限る。rebuild_public.py は
非公開の作業データが要るので入れない）。force push はしない。push は人が `git push --force-with-lease` で行う。

使い方：python3 scripts/sync_main.py [--base origin/main]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# (生成物のパス, 作り直すコマンドを順に)。入力は Git の中のファイルだけ。
# build_database.py は Git に入れない members.json を読むので、先に作る（CI の verify と同じ順）
GENERATED = [
    ("app/public/distribution/charts.json", [["node", "scripts/build_public_members.mjs"], [sys.executable, "scripts/build_database.py"]]),
]


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=check)


def conflicted() -> list[str]:
    return [p for p in git("diff", "--name-only", "--diff-filter=U").stdout.split("\n") if p]


def regenerate() -> list[str]:
    for _, cmds in GENERATED:
        for cmd in cmds:
            subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return [p for p in git("diff", "--name-only").stdout.split("\n") if p]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args()
    if git("status", "--porcelain").stdout.strip():
        print("未コミットの変更がある。コミットか退避をしてから回す", file=sys.stderr)
        return 1
    remote, _, branch = args.base.partition("/")
    git("fetch", "-q", remote, branch)
    generated = {p for p, _ in GENERATED}
    while git("rebase", args.base, check=False).returncode != 0:
        files = conflicted()
        if not files or not set(files) <= generated:
            git("rebase", "--abort", check=False)
            print("生成物以外が衝突した。rebase を中止した：" + "、".join(files or ["（衝突ファイルなし）"]), file=sys.stderr)
            return 1
        for f in files:  # rebase 中の ours は載せ先（main）側。作り直すので main 側を取る
            git("checkout", "--ours", "--", f)
            git("add", "--", f)
        regenerate()
        git("add", "-A")
        done = subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=ROOT, capture_output=True, text=True)
        if done.returncode != 0 and not conflicted():
            print((done.stderr or done.stdout).strip(), file=sys.stderr)
            return 1
    changed = regenerate()
    if changed:
        git("add", "-A")
        git("commit", "-q", "-m", "main に合わせて生成物を作り直す：" + "、".join(changed))
        print("生成物を作り直してコミットした：" + "、".join(changed))
    else:
        print("main に載せ直した。生成物は最新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
