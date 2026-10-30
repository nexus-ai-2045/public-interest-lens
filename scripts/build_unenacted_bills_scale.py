"""未成立の提出法案の暫定「規模点」。成立した法律の額（all-laws-v1）とは別の表。

題名だけで分野を決め（triage_v2_line2.triage：D1〜D5・AI 呼び出し0）、その分野の産業の GDP 比（OECD 表6、日本、直近年の名目付加価値）を点にする。
規模点＝「この法案が触れる産業が日本の付加価値の何%か」。円の額・向き（良い悪い）は付けない。確かさは常に「参考」。
入力：data/acquired/bill-census-full/listing.csv（審議状況が「成立」以外）、data/acquired/oecd-industry/industry_va.csv
出力：data/derived/unenacted-bills-v1/scale.csv
使い方（リポジトリのルートで）：python3 scripts/build_unenacted_bills_scale.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
from triage_v2_line2 import triage  # noqa: E402
from build_macro_amounts import INDUSTRY  # noqa: E402

SRC = Path("data/acquired/bill-census-full/listing.csv")
OECD = Path("data/acquired/oecd-industry/industry_va.csv")
DST = Path("data/derived/unenacted-bills-v1/scale.csv")
HEADER = ["id", "提出回次", "種別", "題名", "審議状況", "分野", "指標", "産業", "規模点", "確かさ", "向き", "判定", "理由"]


def shares() -> tuple[dict[str, float], int]:
    """産業コード → 日本の付加価値の対全産業比（%）。複合コード（M+N・R+S）は取得済みの節の合計。"""
    with OECD.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["国"] == "JPN" and r["価格"] == "V"]
    year = max(int(r["年"]) for r in rows)
    val = {r["産業"]: float(r["値"]) for r in rows if int(r["年"]) == year}
    total = val["_T"]
    out = {}
    for code in set(INDUSTRY.values()):
        parts = [val[p] for p in code.split("+") if p in val]
        if parts:
            out[code] = round(100 * sum(parts) / total, 2)
    return out, year


def guess_kind(title: str) -> str:
    return "実質改正" if "の一部を改正する" in title or "等の一部を改正" in title else "新規"


def main() -> None:
    share, year = shares()
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        allrows = list(csv.DictReader(f))
    # 同じ法案が複数の回次に載る（継続審議）。成立した法案は除き、残りは最後に載った回次の1行にする。
    enacted = {(r["種別"], r["提出回次"], r["番号"]) for r in allrows if r["審議状況"] == "成立"}
    last: dict[tuple, dict] = {}
    for r in sorted(allrows, key=lambda r: int(r["掲載回次"])):
        k = (r["種別"], r["提出回次"], r["番号"])
        if k not in enacted:
            last[k] = r
    rows = list(last.values())
    DST.parent.mkdir(parents=True, exist_ok=True)
    n_pt = 0
    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for r in rows:
            title = r["議案件名"]
            t = triage(title, guess_kind(title), "対応表なし")
            code = INDUSTRY.get(t["field"], "")
            pt = share.get(code, "") if t["verdict"] == "評価対象" and code else ""
            n_pt += pt != ""
            if pt != "":
                why = f"題名から分野「{t['field']}」（{t['reason'].split('／', 1)[-1]}）。規模点＝産業{code}の付加価値の対全産業比（OECD表6・日本・{year}年）。円と向きは付けない"
            elif t["verdict"] == "保留":
                why = t["reason"]
            else:
                why = f"点を付けない：{t['verdict']}（{t['kind']}・{t['field'] or '分野不明'}）。産業を特定できない、または定型・組織手続の可能性"
            id_ = f"{r['種別']}-{r['提出回次']}-{r['番号']}"
            w.writerow([id_, r["提出回次"], r["種別"], title, r["審議状況"], t["field"], t["indicator"], code, pt,
                        "参考" if pt != "" else "", "不明" if pt != "" else "", t["verdict"], why])
    print(f"未成立 {len(rows)} 本、規模点あり {n_pt} 本 → {DST}")


if __name__ == "__main__":
    main()
