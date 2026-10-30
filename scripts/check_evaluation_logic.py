"""評価のロジック検査（全件）。数字の検査ではなく、評価どうしが矛盾していないかを規則で調べる。

規則（破ると違反として数える）：
  L1 因果の鎖  額あり・公開候補の法律に、議員の関与（出典 URL つき）が1件以上ある
  L2 範囲      狭い題名（特例・特定など）に、産業全体・経済全体の額を当てていない
  L3 向き      向き（貢献・上昇／悪影響・低下）と、額の符号（中央値）が食い違っていない
  L4 二重計上  同じ法律に個別の額と参考額を両方付けていない
  L5 単位・期間 額に単位と開始前年の水準が書いてあり、参考額の窓の始まりが施行年と合っている
  L6 矛盾      振り分けが評価対象外・効果なしの法律に、額が付いていない

使い方：python3 scripts/check_evaluation_logic.py            違反の本数を出す
        python3 scripts/check_evaluation_logic.py --write-baseline   いまの本数を基準として保存
CI（tests/test_evaluation_logic.py）は、基準より違反が増えたら落ちる。減ったら基準を下げる。
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "derived"
BASELINE = D / "evaluation-ledger-v1" / "logic-baseline.json"
NARROW_WORDS = ("特例", "特定", "臨時", "暫定", "特別措置")
RULES = ("L1", "L2", "L3", "L4", "L5", "L6")


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check() -> dict[str, dict[str, str]]:
    """{規則: {法律ID: 理由}}"""
    outcomes = {r["id"]: r for r in read(D / "all-laws-v1" / "outcomes.csv")}
    macro = {r["id"]: r for r in read(D / "macro-v1" / "macro.csv") if r["結果"] == "額"}
    publish = {r["id"]: r for r in read(D / "publish-v1-triage-v2" / "publish.csv")}
    involved = defaultdict(int)
    for r in read(D / "allocation-v1" / "involvements.csv"):
        if r["証拠URL"].startswith("http"):
            involved[r["法律ID"]] += 1
    viol: dict[str, dict[str, str]] = {k: {} for k in RULES}

    for i, o in outcomes.items():
        has_amount = o["結果"] == "額あり"
        # L1
        if (has_amount or i in publish) and o["公開可否"] != "公開不可" and involved[i] == 0:
            viol["L1"][i] = "公開候補なのに出典つきの関与が無い"
        if has_amount and involved[i] == 0 and i not in viol["L1"]:
            viol["L1"][i] = "個別の額があるが出典つきの関与が無い"
        # L3
        if has_amount:
            m = re.search(r"(便益|損失)：中央値=(-?\d+)", o["損失または便益の額"])
            if m:
                side, v = m.group(1), int(m.group(2))
                good = o["向き"] in ("貢献", "上昇")
                bad = o["向き"] in ("悪影響", "低下")
                if (side == "便益" and good and v < 0) or (side == "損失" and bad and v < 0) \
                        or (side == "便益" and bad and v > 0) or (side == "損失" and good and v > 0):
                    viol["L3"][i] = f"向き「{o['向き']}」と{side}の中央値の符号が逆"
            # L5
            if not o["単位"] or "名目は開始前最後の年" not in o["単位"]:
                viol["L5"][i] = "額に単位または基準年が無い"
        # L4
        if has_amount and i in macro:
            viol["L4"][i] = "個別の額と参考額が両方ある"
        # L6
        if o["結果"] in ("評価対象外", "効果なし（定例）") and (i in macro):
            viol["L6"][i] = f"結果が「{o['結果']}」なのに参考額がある"

    for i, m in macro.items():
        title = outcomes[i]["題名"] if i in outcomes else ""
        # L2
        if (m["産業"] == "_T" or m["分野"] == "経済全体") and any(w in title for w in NARROW_WORDS):
            viol["L2"][i] = "狭い題名に全産業の額"
        # L5
        yr = re.search(r"開始前最後の年（(\d{4})年）", m["計算式の要素"])
        eff = (m["施行日"] or "")[:4]
        if yr and eff.isdigit() and "推定" not in m["施行日の由来"] and abs(int(yr.group(1)) - (int(eff) - 1)) > 1:
            viol["L5"][i] = "窓の基準年が施行年の前年と合わない"
    return viol


def counts(viol) -> dict[str, int]:
    return {k: len(v) for k, v in viol.items()}


def main() -> int:
    viol = check()
    c = counts(viol)
    print(json.dumps(c, ensure_ascii=False))
    if "--write-baseline" in sys.argv:
        BASELINE.write_text(json.dumps(c, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
