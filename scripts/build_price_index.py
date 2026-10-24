"""物価の換算表 `app/public/distribution/price-index.json` を作る（計算方法の仕様 price-v1）。

日本の全産業の総付加価値（OECD 表6、B1G）の名目（V）を実質（LR、2020年基準の連鎖）で割った値を、
GDP デフレーター（付加価値の物価）として年ごとに出す。画面はこれで「開始前の年の円」を「最新年の円」に直す。
入力はリポジトリ内の data/acquired/oecd-industry/industry_va.csv だけ。

使い方（リポジトリのルートで）：python3 scripts/build_price_index.py [--check]
--check は書き込まず、ファイルが入力と一致しなければ終了コード1で止まる。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "acquired" / "oecd-industry" / "industry_va.csv"
OUTPUT = ROOT / "app" / "public" / "distribution" / "price-index.json"


def deflators(path: Path = INPUT) -> tuple[dict[int, float], str]:
    """年 → 日本の付加価値の物価（2020年＝100）。名目と実質の両方がある年だけ。"""
    values: dict[int, dict[str, float]] = {}
    source = ""
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["国"] != "JPN" or row["産業"] != "_T" or row["価格"] not in ("V", "LR"):
                continue
            values.setdefault(int(row["年"]), {})[row["価格"]] = float(row["値"])
            source = row["出典URL"]
    out = {year: round(100 * v["V"] / v["LR"], 3) for year, v in sorted(values.items()) if v.get("LR") and "V" in v}
    return out, source


def build(path: Path = INPUT) -> dict:
    table, source = deflators(path)
    if not table:
        raise SystemExit(f"日本の名目・実質の付加価値が見つかりません: {path}")
    return {
        "schema": "price-index/v1",
        "rule": "price-v1",
        "country": "JPN",
        "measure": "総付加価値（B1G）の名目÷実質（2020年＝100）",
        "latestYear": max(table),
        "sourceUrl": source,
        "deflator": {str(year): value for year, value in table.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print("price-index.json が入力と一致しません。python3 scripts/build_price_index.py で作り直してください", file=sys.stderr)
            return 1
        print("price-index.json は入力と一致")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"書きました: {OUTPUT.relative_to(ROOT)}（{len(json.loads(text)['deflator'])}年分）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
