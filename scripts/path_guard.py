"""パスの包含判定の唯一の実装。比較する両辺を実体パスへそろえてから判定する。"""

from __future__ import annotations

import sys
from pathlib import Path

_FOLD_CASE = sys.platform in {"darwin", "win32"}


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _same(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if _FOLD_CASE:
        return tuple(part.casefold() for part in left) == tuple(part.casefold() for part in right)
    return left == right


def inside_without_links(root: Path, path: Path) -> Path | None:
    canonical_root = root.resolve()
    lexical = path.absolute()
    canonical = lexical.resolve()
    if canonical == canonical_root or not canonical.is_relative_to(canonical_root):
        return None
    depth = len(canonical.relative_to(canonical_root).parts)
    if len(lexical.parts) < depth or not _same(lexical.parts[-depth:], canonical.parts[-depth:]):
        return None
    for node in (lexical, *lexical.parents[: depth - 1]):
        if _is_link(node):
            return None
    return canonical
