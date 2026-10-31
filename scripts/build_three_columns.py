"""全法律（3,415本）に、額の物差し三欄（設計決定0024）を1行ずつ付ける。数値は作らず、既存の表を結び付けて並べるだけ。

三欄：
  付加価値の変化（本線）  産業の付加価値（GDP）の変化を円で。順位・合計・配分に使うのはこの欄だけ
                        由来：個別の因果の鎖（all-laws-v1 の額あり）／コロナ対応の費用便益（covid-benefit-v1）／全体指標の参考の額（macro-v1、確かさ「参考」で順位に使わない）
  国の収支（別表）        税収の増減見込み（億円、平年度、マイナスは減収）。足さない・使わない
                        由来：毎年の税制改正の増減収見込み（tax-impact-v1）。国の支出（給付・補助の予算額）は次の欄
  採算（参考）            付加価値の変化 ÷ 国の支出。国の支出が一次資料で分かる法律だけ（コロナ対応の給付・補助の支出の規模）

入力：data/derived/{all-laws-v1/outcomes.csv, macro-v1/macro.csv, covid-benefit-v1/benefit.csv, tax-impact-v1/fiscal.csv}
出力：data/derived/three-columns-v1/columns.csv
使い方（リポジトリのルートで）：python3 scripts/build_three_columns.py
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "derived"
OUT = D / "three-columns-v1" / "columns.csv"
HEADER = ["id", "題名", "付加価値の変化（円）", "付加価値の由来", "付加価値の確かさ", "順位に使う", "国の収支（億円）", "国の収支の由来",
          "国の支出（円）", "採算（付加価値÷国の支出）", "採算の注記"]
SIDE_MEDIAN = re.compile(r"(便益|損失)：中央値=(-?\d+)")
ORIGIN_CHAIN = "個別の因果の鎖（段階1〜3）"
ORIGIN_COVID = "コロナ対応の費用便益"
ORIGIN_MACRO = "全体指標の参考の額（産業の付加価値の差）"
ORIGIN_FISCAL = "税制改正の増減収見込み（財務省、平年度）"
COVID_NOTE = "コロナ対応の費用便益の中央値÷支出の規模（中）。移転そのものは便益に数えない。参考"


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def signed_median(text: str) -> int | None:
    """『便益：中央値=…』は正、『損失：中央値=…』は負の符号つきの円。損失の額は正の数で書かれている。"""
    m = SIDE_MEDIAN.search(text)
    if not m:
        return None
    value = abs(int(m.group(2)))
    return value if m.group(1) == "便益" else -value


def middle(text: str) -> int | None:
    """『下・中・上』を「・」で並べた支出の規模から中の値。"""
    parts = [p for p in text.split("・") if p.strip()]
    return int(parts[1]) if len(parts) == 3 and parts[1].lstrip("-").isdigit() else None


def build() -> list[dict[str, str]]:
    outcomes = read(D / "all-laws-v1" / "outcomes.csv")
    macro = {r["id"]: r for r in read(D / "macro-v1" / "macro.csv") if r["結果"] == "額"}
    covid = {r["id"]: r for r in read(D / "covid-benefit-v1" / "benefit.csv") if r["結果"] == "額"}
    fiscal = {r["id"]: r for r in read(D / "tax-impact-v1" / "fiscal.csv") if r["平年度_億円"] != ""}
    rows = []
    for o in outcomes:
        i = o["id"]
        row = {c: "" for c in HEADER}
        row.update(id=i, 題名=o["題名"])
        if o["結果"] == "額あり" and o["経路"] != "財政（税収見込み）":
            value = signed_median(o["損失または便益の額"])
            if value is not None:
                row.update({"付加価値の変化（円）": str(value), "付加価値の由来": ORIGIN_CHAIN, "付加価値の確かさ": o["確かさ"], "順位に使う": "はい"})
        elif i in covid:
            c = covid[i]
            row.update({"付加価値の変化（円）": c["中央値"], "付加価値の由来": ORIGIN_COVID, "付加価値の確かさ": "参考", "順位に使う": "いいえ"})
            spend = middle(c["支出の規模（円）"])
            if spend:
                row["国の支出（円）"] = str(spend)
                row["採算（付加価値÷国の支出）"] = f"{int(c['中央値']) / spend:.4f}"
                row["採算の注記"] = COVID_NOTE
        elif i in macro:
            row.update({"付加価値の変化（円）": macro[i]["中央値"], "付加価値の由来": ORIGIN_MACRO, "付加価値の確かさ": "参考", "順位に使う": "いいえ"})
        if i in fiscal:
            row.update({"国の収支（億円）": fiscal[i]["平年度_億円"], "国の収支の由来": ORIGIN_FISCAL})
        rows.append(row)
    return rows


def main() -> int:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"three-columns-v1: {len(rows)} 本 付加価値 {Counter(r['付加価値の由来'] for r in rows if r['付加価値の由来'])}"
          f" 国の収支 {sum(bool(r['国の収支（億円）']) for r in rows)} 採算 {sum(bool(r['採算（付加価値÷国の支出）']) for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
