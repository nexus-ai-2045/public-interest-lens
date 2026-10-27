"""計算方法の版と実際の生成ソースを、端末名・時刻・Git履歴から独立して記録する。"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    from scripts.path_guard import inside_without_links
except ModuleNotFoundError:
    from path_guard import inside_without_links

ROOT = Path(__file__).resolve().parents[1]


def generation_metadata(sources: list[str], *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    spec = inside_without_links(root, root / "app/src/method-spec.ts")
    if spec is None:
        raise ValueError("計算方法の定義がリポジトリの外を参照しています")
    versions = re.findall(r"^export const SPEC_VERSION = '(method-spec-v[0-9]+\.[0-9]+(?:\.[0-9]+)?)';$", spec.read_text(encoding="utf-8"), re.M)
    if len(versions) != 1:
        raise ValueError("計算方法の版を一意に特定できません")
    hashes = {}
    for name in sorted(set(sources) | {"app/src/method-spec.ts", "scripts/generation_provenance.py", "scripts/path_guard.py"}):
        path = inside_without_links(root, root / name)
        if path is None:
            raise ValueError("生成ソースがリポジトリの外を参照しています")
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"methodSpecVersion": versions[0], "codeHashes": hashes}
