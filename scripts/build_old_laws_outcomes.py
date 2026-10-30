#!/usr/bin/env python3
"""旧法（第77〜141回）のうち施行日が取れた法律に、既存の規則で結果を付ける（R1）。

入口だけを足す。規則は scripts/build_all_laws_outcomes.py の decide()（題名の語の規則・マクロ指標の代理・評価対象外・測定できない）を
そのまま使い、ここでは旧法の施行日と振り分けを読んで decide() に渡す。

入力（全てリポジトリ内）:
  data/acquired/enforcement-dates-old/enforcement_old.csv  施行日（取れた行だけ。後から行が増えてよい）
  data/derived/bill-triage-old/triage.csv                  旧法の振り分け（A・B の一致／保留。ADR 0007）
  data/derived/impact-old/impact.csv                       分野が8分野の旧法の影響の判定（app/scripts/run-impact-old.mjs）
出力:
  data/derived/all-laws-old/outcomes.csv                   施行日のある旧法ごとの結果（列は all-laws-v1/outcomes.csv と同じ）

v2 と同じく2系統の一致を見る：A・B（v1）が一致し、かつ系統2（v2 の基準）の分野が同じものだけを「一致」とする。
振り分けが「保留」の法律と、A・B が一致しても系統2と分野が食い違う法律は、定例の改正の語（RT1〜RT8）に当たらなければ、市場の経路の有無を決めずに「保留」とし、理由を書く。
損失・便益の段（loss・benefit）は旧法ではまだ回していないので、額の出る法律は無い。測れないものは外さず、理由つきで残す。

使い方（リポジトリのルートで）:
  cd app && node scripts/run-impact-old.mjs   # 先に影響の判定（8分野の法律だけ）
  python3 scripts/build_old_laws_outcomes.py
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # python3 scripts/build_old_laws_outcomes.py と直接実行しても scripts を読めるように
    sys.path.insert(0, str(ROOT))

from scripts import build_all_laws_outcomes as base  # noqa: E402
ENFORCEMENT = ROOT / "data" / "acquired" / "enforcement-dates-old" / "enforcement_old.csv"
TRIAGE = ROOT / "data" / "derived" / "bill-triage-old" / "triage.csv"
IMPACT = ROOT / "data" / "derived" / "impact-old" / "impact.csv"
OUT = ROOT / "data" / "derived" / "all-laws-old" / "outcomes.csv"


def agreed(t: dict[str, str]) -> bool:
    """A・B（v1）が一致し、系統2（v2）の分野も同じなら True（app/scripts/run-impact-old.mjs も同じ条件で選ぶ）。"""
    return t["結果"] == "一致" and t.get("系統2_分野", "") == t["分野"]


def decide_old(t: dict[str, str], date: str, impact: dict[str, dict[str, str]]) -> dict[str, str]:
    """旧法1本の結果。t は旧法の triage.csv の行、date は施行日。"""
    stages = SimpleNamespace(agreement={}, line_pick={}, line_kind={}, impact=impact, loss={}, benefit={}, publish={}, covid=set(), institutional={})
    imp = impact.get(t["id"])
    row = {**t, "指標": imp["指標"] if imp else ""}
    if not agreed(t):
        # 2系統が一致していない：市場の経路を決められない。定例の語に当たるものだけ既存の規則で決める。
        rt = base.routine_rule(t["題名"], (t["A_種類"], t["B_種類"]))
        if rt is None:
            if t["結果"] != "一致":
                why = "振り分けの2系統（A・B）の種類・分野が一致せず"
            else:
                why = f"A・B（v1）の分野「{t['分野']}」と系統2（v2）の分野「{t.get('系統2_分野', '')}」が食い違い"
            out = {c: "" for c in base.HEADER}
            out.update(id=t["id"], 題名=t["題名"], 施行日=date, 分野=base.NO_FIELD, 結果="保留", 経路="振り分け保留",
                       理由=f"{why}、市場の経路を決められない（ADR 0007：一致したものだけ採る）")
            return out
        row = {**row, "A_分野": base.NO_FIELD, "B_分野": base.NO_FIELD}
    out = base.decide({"題名": t["題名"]}, row, date, stages)
    if out["経路"] == "市場（v2の後段）":  # 旧法の影響の表（impact-old）を使ったので、v2 の表とは書かない
        out["経路"] = "市場（旧法の影響表）"
    return out


def build(root: Path = ROOT) -> list[dict[str, str]]:
    triage = {r["id"]: r for r in base.read_csv(root / "data" / "derived" / "bill-triage-old" / "triage.csv")}
    impact = {r["id"]: r for r in base.read_csv(root / "data" / "derived" / "impact-old" / "impact.csv")}
    rows = []
    for e in base.read_csv(root / "data" / "acquired" / "enforcement-dates-old" / "enforcement_old.csv"):
        date = e["施行日"].strip()
        if date:
            rows.append(decide_old(triage[e["法令番号"]], date, impact))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="施行日のある旧法（第77〜141回）に結果を付け、data/derived/all-laws-old/outcomes.csv に書く")
    parser.parse_args(argv)
    rows = build()
    base.write(rows, OUT)
    count = Counter(r["結果"] for r in rows)
    print(f"all-laws-old: {len(rows)} 本 " + " ".join(f"{k}={count.get(k, 0)}" for k in base.OUTCOMES))


if __name__ == "__main__":
    main()
