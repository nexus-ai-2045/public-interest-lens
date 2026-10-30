"""未成立法案の本文を読んだ2系統の AI（A：仕組みを1つ選ぶ／B：4つの問いに答える）の出力を1つの表にする。

入力：<dir>/out_A_NN.json（{id: 選択肢}）、<dir>/out_B_NN.json（{id: {q1,q2,q3,q4}}）
出力：data/derived/unenacted-bills-v1/mechanism-labels.csv（id, A, q1〜q4, 一致, 一致した仕組み）
使い方：python3 scripts/merge_mechanism_labels.py <dir>
一致＝A の選択肢が B の答えと矛盾しないとき（下の CHECK）。向きの表は build_unenacted_direction.py。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

DST = Path("data/derived/unenacted-bills-v1/mechanism-labels.csv")
# A の選択肢 → B の答えがこの条件を満たすとき一致（向きを決める6つの仕組みだけ。他は向きを決めない）
CHECK = {
    "規制緩和・競争促進": lambda b: b["q2"] == "はい" and b["q1"] != "はい",
    "民営化": lambda b: b["q4"] == "公的から民間",
    "減税": lambda b: b["q3"] == "減らす",
    "参入・価格・数量の規制強化": lambda b: b["q1"] == "はい" and b["q2"] != "はい",
    "国有化・公営化": lambda b: b["q4"] == "民間から公的",
    "増税": lambda b: b["q3"] == "増やす",
}


def merge(a: dict, b: dict) -> list[dict]:
    rows = []
    for id_ in sorted(set(a) | set(b)):
        la, lb = a.get(id_, ""), b.get(id_, {})
        q = {k: lb.get(k, "") for k in ("q1", "q2", "q3", "q4")}
        q["q4"] = q["q4"].removesuffix("へ")  # 「公的から民間へ」「公的から民間」の両方を同じに扱う
        ok = la in CHECK and bool(lb) and CHECK[la](q)
        rows.append({"id": id_, "A": la, **q, "一致": "一致" if ok else "", "一致した仕組み": la if ok else ""})
    return rows


def main() -> None:
    d = Path(sys.argv[1])
    a, b = {}, {}
    for p in sorted(d.glob("out_A_*.json")):
        a.update(json.loads(p.read_text(encoding="utf-8")))
    for p in sorted(d.glob("out_B_*.json")):
        b.update(json.loads(p.read_text(encoding="utf-8")))
    rows = merge(a, b)
    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["id", "A", "q1", "q2", "q3", "q4", "一致", "一致した仕組み"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"A {len(a)} 本、B {len(b)} 本、一致 {sum(r['一致'] == '一致' for r in rows)} 本 → {DST}")


if __name__ == "__main__":
    main()
