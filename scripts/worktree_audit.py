#!/usr/bin/env python3
"""git worktree の状態を一覧化し、安全に消せるものを判定する。

既定は一覧のみ（何も変更しない）。--apply で「マージ済み・変更なし」の worktree を削除する。
--keep PATH（複数可）で触らない worktree を指定する。
"""
import argparse
import os
import subprocess
import sys


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def du_mb(path):
    r = subprocess.run(["du", "-sk", path], capture_output=True, text=True)
    return int(r.stdout.split()[0]) // 1024 if r.stdout else 0


def parse_worktrees(root):
    _, out = git(root, "worktree", "list", "--porcelain")
    items, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    return items


def inspect(root, wt, base):
    path = wt["worktree"]
    info = {"path": path, "branch": wt.get("branch", "").replace("refs/heads/", "") or "(detached)"}
    if not os.path.isdir(path):
        info.update(missing=True, size=0, dirty=0, unpushed=0, merged=False)
        return info
    info["size"] = du_mb(path)
    _, st = git(path, "status", "--porcelain")
    info["dirty"] = len([l for l in st.splitlines() if l.strip()])
    head = wt.get("HEAD", "")
    info["head"] = head[:7]
    info["merged"] = git(root, "merge-base", "--is-ancestor", head, base)[0] == 0
    # 他のどのリモートブランチにも含まれないコミット数
    _, n = git(path, "rev-list", "--count", "HEAD", "--not", "--remotes")
    info["unpushed"] = int(n or 0)
    _, subj = git(path, "log", "-1", "--format=%s")
    info["subject"] = subj[:60]
    heavy = [d for d in ("node_modules", ".next", "app/node_modules", "app/.next", ".venv")
             if os.path.isdir(os.path.join(path, d))]
    info["heavy"] = heavy
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="マージ済み・変更なしを削除する")
    ap.add_argument("--keep", action="append", default=[], help="触らない worktree のパス部分文字列")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args()
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    wts = parse_worktrees(root)[1:]  # 先頭は本体
    rows = [inspect(root, w, args.base) for w in wts]
    print(f"{'size(MB)':>8} {'dirty':>5} {'unpushed':>8} {'merged':>6}  判定  path [branch]")
    safe = []
    for r in rows:
        kept = any(k in r["path"] for k in args.keep)
        if kept:
            v = "保持"
        elif r.get("missing"):
            v = "消去可(欠損)"
        elif r["merged"] and r["dirty"] == 0 and r["unpushed"] == 0:
            v = "消去可"
        else:
            v = "要判断"
        r["verdict"] = v
        if v.startswith("消去可"):
            safe.append(r)
        print(f"{r['size']:>8} {r['dirty']:>5} {r['unpushed']:>8} {str(r['merged']):>6}  {v}  {r['path'].split('/')[-1]} [{r['branch']}] {r.get('subject','')}")
        if r.get("heavy"):
            print(f"{'':>34}重い再生成物: {', '.join(r['heavy'])}")
    print(f"合計 {sum(r['size'] for r in rows)} MB / 消去可 {sum(r['size'] for r in safe)} MB")
    if args.apply:
        for r in safe:
            if r.get("missing"):
                continue
            rc, out = git(root, "worktree", "remove", r["path"])  # --force なし：変更があれば失敗する
            print("remove", r["path"], "OK" if rc == 0 else f"失敗: {out}")
        git(root, "worktree", "prune")


if __name__ == "__main__":
    sys.exit(main())
