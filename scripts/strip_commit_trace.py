#!/usr/bin/env python3
"""コミットメッセージから、開発道具が自動で付ける行（Claude の共著者行・セッション行・セッション URL・生成の注記）を取り除く。

prepare-commit-msg フックから呼ぶ（scripts/install_hooks.py が入れる）。取り除かないと、後段の commit-msg
（repo-preflight の identity_gate）と CI の名義検査が赤になり、PR を作り直すことになる。
セッション行の型は identity_gate の SESSION_TRACE_RES をそのまま使う（型の写しを持たない）。
identity_gate が見つからないときは何もしない（後段の commit-msg が「見つからない」で止める）。

PR 本文にも同じ型が効く（CI の名義検査が claude.ai の URL を落とす）。フックは API 経由の PR 作成に届かないので、
本文は作る前にこのスクリプトを通す：`python3 scripts/strip_commit_trace.py --body < 本文.md > 掃除済み.md`。

使い方：python3 scripts/strip_commit_trace.py <メッセージのファイル>
        python3 scripts/strip_commit_trace.py --body   （標準入力の PR 本文を掃除して標準出力へ）
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 署名行（〜-by:）のうち、AI 開発道具の名義のもの。人の名義の署名行は取り除かず、後段の検査に任せる
TOOL_TRAILER_RE = re.compile(r"^[ \t]*[A-Za-z][A-Za-z0-9-]*-by[ \t]*:.*(?:claude|anthropic|openai|codex|copilot|cursor)", re.I)
GENERATED_RE = re.compile(r"^[ \t]*(?:🤖[ \t]*)?Generated with[ \t].*(?:claude|codex|copilot|cursor)", re.I)


def gate_module():
    home = os.environ.get("REPO_PREFLIGHT_HOME") or os.environ.get("REPO_PREFLIGHT_ROOT") or str(ROOT.parent / "repo-preflight")
    path = Path(home).expanduser() / "scripts" / "identity_gate.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("identity_gate", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["identity_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


def strip(text: str, trace_res) -> str:
    kept = [l for l in text.split("\n") if not (TOOL_TRAILER_RE.match(l) or GENERATED_RE.match(l) or any(r.search(l) for r in trace_res))]
    return re.sub(r"\n+\Z", "\n", "\n".join(kept)) if "".join(kept).strip() else "\n".join(kept)


def main(argv: list[str]) -> int:
    if argv[1:] == ["--body"]:
        mod = gate_module()
        text = sys.stdin.read()
        sys.stdout.write(text if mod is None else strip(text, mod.SESSION_TRACE_RES))
        return 0
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    mod = gate_module()
    if mod is None:
        return 0
    path = Path(argv[1])
    old = path.read_text(encoding="utf-8")
    new = strip(old, mod.SESSION_TRACE_RES)
    if new != old:
        path.write_text(new, encoding="utf-8")
        print("コミットメッセージから自動付与の行を取り除きました", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
