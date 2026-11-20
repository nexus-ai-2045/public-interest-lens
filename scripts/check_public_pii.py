"""公開データ（app/dist に入るファイル）に、個人情報の形が無いことを検査する。

設計決定0008で出してよいのは、公人としての公開記録（氏名、衆参・委員会の提出・採決・質問・役職）だけ。
私生活（住所・家族・健康）の項目名は出さない。項目名が出してよいものでも、すべての文字列は形で調べる。
形はメール、電話番号、実ホームパス（/Users/ /home/ C:\\Users\\）、鍵の4つ。環境変数では飛ばせない。

使い方：python3 scripts/check_public_pii.py [調べるディレクトリ]
  省略時は app/dist。公開版のビルド、npm test、pytest が同じ scan を呼ぶ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 私生活の項目名（設計決定0008で出してよい公開記録に無い）。産業区分の health は保健衛生なので含めない。
PRIVATE_LIFE_KEY = re.compile(
    r"^(?:address|addr|street|family|families|email|e-mail|phone|tel|telephone|mobile|"
    r"住所|番地|家族|親族|健康|病歴|病名|メール|メールアドレス|電話|電話番号|携帯|携帯電話)$",
    re.IGNORECASE,
)
EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?\.[A-Za-z]{2,}(?![A-Za-z0-9])"
)
PHONE = re.compile(r"(?<!\d)0\d{1,3}-\d{2,4}-\d{3,4}(?!\d)")
# URL のパス（https://例.jp/home/）は実ホームパスではない。直前が英数字・コロン・スラッシュならパスの続きとみなす。
HOME = re.compile(r"(?<![\w:/])(?:/Users/|/home/|[A-Za-z]:[\\/]Users[\\/])")
KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
    r"|AKIA[0-9A-Z]{16}"
    r"|ASIA[0-9A-Z]{16}"
    r"|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test|proj|ant)-[A-Za-z0-9]{10,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
)
SHAPES = (("メール", EMAIL), ("電話番号", PHONE), ("実ホームパス", HOME), ("鍵", KEY))
BINARY_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".sqlite", ".sqlite3", ".zip", ".gz", ".br", ".wasm",
}


def _window(text: str, start: int, end: int) -> str:
    snippet = text[max(0, start - 40): min(len(text), end + 40)].replace("\n", " ")
    return snippet


def _shapes(text: str, where: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text)
    found = []
    for label, pattern in SHAPES:
        for match in pattern.finditer(folded):
            found.append(f"{label}\t{where}\t{_window(folded, match.start(), match.end())}")
    return found


def _walk_json(node: object, where: str, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            name = unicodedata.normalize("NFKC", str(key))
            if PRIVATE_LIFE_KEY.search(name):
                found.append(f"私生活の項目\t{where}.{name}\t{name}")
            found.extend(_shapes(name, f"{where}.{name}"))
            _walk_json(value, f"{where}.{name}", found)
    elif isinstance(node, list):
        for value in node:
            _walk_json(value, f"{where}[]", found)
    elif isinstance(node, str):
        found.extend(_shapes(node, where))


def _scan_file(path: Path, root: Path) -> list[str]:
    if path.suffix.lower() in BINARY_SUFFIX:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    relative = path.relative_to(root).as_posix()
    if path.suffix.lower() == ".json":
        try:
            found: list[str] = []
            _walk_json(json.loads(text), relative, found)
            return found
        except json.JSONDecodeError:
            pass
    return _shapes(text, relative)


def scan(root: Path) -> list[str]:
    """root 以下の公開ファイルを調べ、見つかった個人情報の形を返す。環境変数は見ない。"""
    root = root.resolve()
    if not root.exists():
        return [f"調べる場所が無い\t{root}\t"]
    if root.is_file():
        return _scan_file(root, root.parent)
    found: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        found.extend(_scan_file(path, root))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", default=str(ROOT / "app" / "dist"), help="調べるディレクトリ（既定は app/dist）")
    args = parser.parse_args(argv)
    found = scan(Path(args.root))
    if found:
        print(f"公開データに個人情報の形が {len(found)} 件ある。公開版のビルドを止める。", file=sys.stderr)
        for line in found:
            print(line, file=sys.stderr)
        return 1
    print(f"公開データの個人情報の形は 0 件（{args.root}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
