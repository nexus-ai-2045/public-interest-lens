#!/usr/bin/env python3
"""人物台帳（persons.csv）に、1人が2つに分かれた疑い（分裂）と、別人が1つに混ざった疑い（統合）がないかを検べる。

分裂の疑い: 読みが同じで氏名の表記が違う人物IDが2つ以上。字体だけが違う組（斎／齋 など。person_ids.GLYPH_GROUPS）は分裂として扱い、
  person_ids.py が元職の名簿を足すとき同じ人の別表記に結ぶ。字が違う組（伊藤孝恵／伊藤孝江）は別人として一覧に残すだけ。
統合の疑い: 元職の名簿（historical.csv）で、会議録の発言者の読みが複数ある行（同姓同名の疑い）。person_ids.py はこれを台帳に入れない。
出力: data/derived/person-ids/duplicate-suspects.csv と件数。--strict を付けると、字体だけが違う分裂の組が残っていれば終了コード 1。

使い方: python3 scripts/check_roster_duplicates.py [--strict]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.person_ids import canonical, glyph_equal  # noqa: E402

PERSONS = ROOT / "data/derived/person-ids/persons.csv"
HISTORICAL = ROOT / "data/acquired/diet-roster/historical.csv"
OUT = ROOT / "data/derived/person-ids/duplicate-suspects.csv"


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(open(path, encoding="utf-8", newline=""))) if path.exists() else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    by_yomi: dict[str, list[dict[str, str]]] = defaultdict(list)
    for p in rows(PERSONS):
        if p["人物ID"] and p["読み"]:
            by_yomi[re.sub(r"\s+", "", p["読み"])].append(p)
    out = []
    same_house = 0
    for yomi, ps in sorted(by_yomi.items()):
        ids = {p["人物ID"] for p in ps}
        if len(ids) < 2:
            continue
        houses = [p["院"] for p in ps]
        names = [canonical(p["氏名"]) for p in ps]
        glyph = any(names[i] != names[j] and glyph_equal(names[i], names[j]) for i in range(len(ps)) for j in range(i + 1, len(ps)))
        if glyph:
            kind = "読みが同じで字体だけ違う（分裂：同じ人の別表記にすべき）"
        elif len(set(houses)) < len(houses) or "" in houses:
            kind = "読みと院が同じで字が違う（別人。例：伊藤孝恵／伊藤孝江）"
        else:
            kind = "読みが同じで院が違う（別人の可能性が高い）"
        same_house += glyph
        out.append({"種類": kind, "読み": yomi, "人物ID": " / ".join(sorted(ids)), "院": " / ".join(houses)})
    namesake = [h for h in rows(HISTORICAL) if h.get("同姓同名の疑い")]
    for h in namesake:
        out.append({"種類": "会議録の読みが複数（統合の疑い。台帳には入れない）", "読み": h["読み"], "人物ID": h["氏名"], "院": h["院"]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["種類", "読み", "人物ID", "院"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    total = len(rows(PERSONS))
    print(f"台帳{total}人 / 読みが同じ組 {sum(1 for r in out if r['種類'].startswith('読み'))}"
          f"（うち字体だけ違う分裂 {same_house}）/ 統合の疑い（台帳に入れず）{len(namesake)}")
    return 1 if a.strict and same_house else 0


if __name__ == "__main__":
    sys.exit(main())
