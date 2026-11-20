"""ファイルを空にしてから書かない。一時ファイルへ書いて rename で置き換える。

原因: Path.write_text は開いた瞬間に中身を空にするので、書き出しが途中で切れると切れた JSON が残る。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text(path: Path, text: str, encoding: str = "utf-8", errors: str | None = None, newline: str | None = None) -> None:
    """中身が全部そろってから置き場の名前を付け替える。失敗したときは前のファイルを残す。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, errors=errors, newline=newline) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        raise
