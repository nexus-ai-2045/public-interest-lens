"""技術を止めた側（省庁・審議会・業界団体・天下り・予算・条例）の一次資料データをリポジトリに取り込む。

入力は共有フォルダ blocking-actors/ に置いた系統別の CSV（WebFetch 要約経由の暫定値）。
クラウドから官公庁へ直接は届かないため原本のバイトは無く、全行が「webfetch要約・暫定」。

取り込みでは次をする。
- 個人の氏名の列（発言者名・寄附先の議員名など）は落とし、本文に残った同じ氏名も伏せる。実名は private 側にだけ置く。
- 出典 URL が http(s) で始まらない行は捨てる（一次資料のリンクが必須）。
- 系統ごとに CSV と manifest.csv（行数・入力 sha256）を書く。

使い方: python3 scripts/build_blocking_actors.py --src /mnt/project-files/blocking-actors
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "acquired" / "blocking-actors"

# 個人の氏名が入る列。リポジトリには入れない。
NAME_COLUMNS = {"発言者名", "寄附先の議員名（公職として）", "氏名"}
URL_COLUMN = "出典URL"


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h for h in (reader.fieldnames or []) if h]
        rows = [{k: (r.get(k) or "").strip() for k in header} for r in reader]
    return header, rows


def names_in(header: list[str], rows: list[dict[str, str]]) -> list[str]:
    """氏名列に出た名前（姓だけの表記も含む）を、長い順に返す。"""
    found = set()
    for h in header:
        if h in NAME_COLUMNS:
            for r in rows:
                v = re.sub(r"[（(].*?[）)]", "", r.get(h, "")).strip()
                if len(v) >= 2:
                    found.add(v)
                    found.add(v.replace(" ", "").replace("\u3000", ""))
    return sorted(found, key=len, reverse=True)


def mask(text: str, names: list[str]) -> str:
    """要旨などの本文に残った氏名を「（氏名）」に置き換える。"""
    for n in names:
        text = text.replace(n, "（氏名）")
    return text


def clean(header: list[str], rows: list[dict[str, str]]) -> tuple[list[str], list[dict[str, str]], int]:
    kept = [h for h in header if h not in NAME_COLUMNS]
    names = names_in(header, rows)
    out, dropped = [], 0
    for r in rows:
        if not r.get(URL_COLUMN, "").startswith(("https://", "http://")):
            dropped += 1
            continue
        out.append({k: mask(r[k], names) for k in kept})
    return kept, out, dropped


def build(src: Path, out: Path = OUT) -> list[dict[str, str]]:
    manifest = []
    for path in sorted(src.glob("*/*.csv")):
        header, rows = load_rows(path)
        kept, cleaned, dropped = clean(header, rows)
        rel = Path(path.parent.name) / path.name
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=kept)
            w.writeheader()
            w.writerows(cleaned)
        manifest.append({
            "ファイル": rel.as_posix(),
            "行数": str(len(cleaned)),
            "URLなしで除外": str(dropped),
            "落とした氏名列": "・".join(h for h in header if h in NAME_COLUMNS),
            "入力sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    with (out / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, required=True)
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    for m in build(args.src, args.out):
        print(m["ファイル"], m["行数"], m["URLなしで除外"])


if __name__ == "__main__":
    main()
