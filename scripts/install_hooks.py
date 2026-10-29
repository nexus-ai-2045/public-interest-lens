#!/usr/bin/env python3
"""git フックを入れる（新しいクラウドのセッションごとに1回。何度回しても同じ）。

入れるもの（.git/hooks。Git に入らず、core.hooksPath は替えない）：
- prepare-commit-msg：scripts/strip_commit_trace.py で、Claude の共著者行・セッション行などを自動で取り除く。
- commit-msg・pre-commit・pre-push：リポジトリの .repo-preflight/hooks/ の共通フックをそのまま呼ぶ（検査の写しは持たない）。
  REPO_PREFLIGHT_HOME は未設定ならこのリポジトリの隣の repo-preflight。
- gitleaks が無ければ repo-preflight の固定版を ~/.local/bin に入れる（pre-commit が要る）。

使い方：python3 scripts/install_hooks.py [--check]
  --check：入っているかだけ確かめる（入っていなければ終了コード1）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ("commit-msg", "pre-commit", "pre-push")
ENV = 'export REPO_PREFLIGHT_HOME="${REPO_PREFLIGHT_HOME:-$ROOT/../repo-preflight}"\nexport PATH="$HOME/.local/bin:$PATH"'
HEADER = '#!/bin/sh\n# scripts/install_hooks.py が書いたフック。手で直さず、スクリプトを直して入れ直す。\nROOT="$(git rev-parse --show-toplevel)"\n' + ENV + "\n"


def hooks_dir() -> Path:
    out = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    p = Path(out)
    return p if p.is_absolute() else ROOT / p


def bodies() -> dict[str, str]:
    out = {"prepare-commit-msg": HEADER + 'python3 "$ROOT/scripts/strip_commit_trace.py" "$1"\nexit 0\n'}
    for name in COMMON:
        out[name] = HEADER + f'exec "$ROOT/.repo-preflight/hooks/{name}" "$@"\n'
    return out


def missing(directory: Path | None = None) -> list[str]:
    d = directory or hooks_dir()
    # 実行権限が無いフックは git が呼ばない（検査が黙って飛ぶ）ので、内容が同じでも足りない扱いにする
    return [n for n, body in bodies().items()
            if not (d / n).is_file() or (d / n).read_text(encoding="utf-8") != body or not os.access(d / n, os.X_OK)]


def install(directory: Path | None = None) -> list[str]:
    d = directory or hooks_dir()
    d.mkdir(parents=True, exist_ok=True)
    todo = missing(d)
    for name in todo:
        (d / name).write_text(bodies()[name], encoding="utf-8")
        (d / name).chmod(0o755)
    return todo


def ensure_gitleaks() -> str:
    """pre-commit の秘密情報検査が要る gitleaks を、repo-preflight の固定版（ハッシュ照合つき）で ~/.local/bin に入れる。"""
    dest = Path.home() / ".local" / "bin"
    if shutil.which("gitleaks", path=f"{dest}{os.pathsep}{os.environ.get('PATH', '')}"):
        return "gitleaks：あり"
    home = Path(os.environ.get("REPO_PREFLIGHT_HOME") or ROOT.parent / "repo-preflight")
    installer = home / "scripts" / "install_pinned_gitleaks.py"
    if not installer.is_file():
        return "gitleaks：無い（repo-preflight の install_pinned_gitleaks.py が見つからない）"
    r = subprocess.run([sys.executable, str(installer), "--dest", str(dest)], capture_output=True, text=True)
    return "gitleaks：固定版を入れた" if r.returncode == 0 else "gitleaks：入れられなかった（" + (r.stderr or r.stdout).strip().splitlines()[-1][:120] + "）"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="入っているかだけ確かめる")
    args = ap.parse_args()
    if args.check:
        gap = missing()
        print("フック：そろっている" if not gap else "フック：足りない・古い " + "、".join(gap) + "（python3 scripts/install_hooks.py）")
        return 1 if gap else 0
    done = install()
    print("入れた：" + "、".join(done) if done else "すでにそろっている")
    print(ensure_gitleaks())
    return 0


if __name__ == "__main__":
    sys.exit(main())
