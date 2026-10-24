#!/usr/bin/env python3
"""第77〜141回の成立法（R1、2,298本）の振り分け：3つの AI のラベルを取り込み、2系統の一致を機械的に決める。

ラベルは scripts/workflows/triage-old-laws-tree.js（Haiku 3系統、題名だけが材料）が付ける。
  A・B  ：v1 の基準（data/derived/bill-triage-v1/spec.md、8分野か対応表なし）
  系統2 ：v2 の基準（bill-triage-v1-line2/criteria.md・criteria-v2-fields.md、8分野＋新分野9つ）

出力（data/derived/bill-triage-old/）:
  labels-A.csv・labels-B.csv・labels-line2.csv（id＝法令番号,題名,種類,分野,理由）
  triage.csv（id,題名,回次,公布日,結果,種類,分野,A_種類,A_分野,B_種類,B_分野,系統2_種類,系統2_分野）

結果の決め方（ADR 0007：2系統の AI が一致したものだけ採る）:
  - A と B の種類・分野がそろい、どちらも保留でなければ「一致」。種類・分野はその値。
  - そろわなければ「保留」（種類・分野は空）。
  - 系統2の列は、施行日がそろった後で v2 の規則（指標・判定）に通すときに使う。ここでは比べない。
施行日と指標・判定はここでは付けない（施行日は scripts/fetch_enforcement_old_egov.py、施行日が取れた分の結果は scripts/build_old_laws_outcomes.py、残りは R16 の後）。

使い方:
  python3 scripts/build_old_laws_triage.py import <木の結果.json>   # ラベル3つを書き、triage.csv を作り直す
  python3 scripts/build_old_laws_triage.py build                    # ラベルから triage.csv だけ作り直す
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "data" / "acquired" / "bill-census-old" / "enacted_old.csv"
OUT = ROOT / "data" / "derived" / "bill-triage-old"
LINES = {"A": "labels-A.csv", "B": "labels-B.csv", "line2": "labels-line2.csv"}
LABEL_HEADER = ["id", "題名", "種類", "分野", "理由"]
TRIAGE_HEADER = ["id", "題名", "回次", "公布日", "結果", "種類", "分野",
                 "A_種類", "A_分野", "B_種類", "B_分野", "系統2_種類", "系統2_分野"]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def import_result(result: Path) -> None:
    """木の結果（{A, B, line2, missing}）を、成立法の台帳の順でラベル3つに書く。欠けた行・余分な行があれば止める。"""
    data = json.loads(result.read_text(encoding="utf-8"))
    data = data.get("result", data)
    if data.get("missing"):
        raise SystemExit(f"返ってこなかったバッチがある：{data['missing']}")
    census = _read(CENSUS)
    ids = [r["法令番号"] for r in census]
    checked = {}
    for key in LINES:  # 3系統すべてを確かめてから書く（途中で止まると世代の違う系統が混ざる）
        items = {x["id"]: x for x in data[key]}
        if set(items) != set(ids) or len(items) != len(data[key]):
            raise SystemExit(f"{key}：台帳の {len(ids)} 本と行が合わない（{len(data[key])} 行）")
        checked[key] = items
    for key, name in LINES.items():
        items = checked[key]
        _write(OUT / name, LABEL_HEADER, [
            {"id": r["法令番号"], "題名": r["題名"], "種類": items[r["法令番号"]]["kind"],
             "分野": items[r["法令番号"]]["field"], "理由": items[r["法令番号"]]["reason"]} for r in census])


def build() -> Counter:
    labels = {key: {r["id"]: r for r in _read(OUT / name)} for key, name in LINES.items()}
    rows, counts = [], Counter()
    for c in _read(CENSUS):
        a, b, l2 = (labels[k][c["法令番号"]] for k in ("A", "B", "line2"))
        agreed = (a["種類"], a["分野"]) == (b["種類"], b["分野"]) and "保留" not in (a["種類"], a["分野"])
        counts["一致" if agreed else "保留"] += 1
        rows.append({"id": c["法令番号"], "題名": c["題名"], "回次": c["回次"], "公布日": c["公布日"],
                     "結果": "一致" if agreed else "保留",
                     "種類": a["種類"] if agreed else "", "分野": a["分野"] if agreed else "",
                     "A_種類": a["種類"], "A_分野": a["分野"], "B_種類": b["種類"], "B_分野": b["分野"],
                     "系統2_種類": l2["種類"], "系統2_分野": l2["分野"]})
    _write(OUT / "triage.csv", TRIAGE_HEADER, rows)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("import").add_argument("result", type=Path)
    sub.add_parser("build")
    args = parser.parse_args()
    if args.command == "import":
        import_result(args.result)
    counts = build()
    print(f"triage.csv：{sum(counts.values())} 本、一致 {counts['一致']}、保留 {counts['保留']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
