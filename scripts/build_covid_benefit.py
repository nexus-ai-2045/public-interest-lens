"""コロナ対応の法律に、支出の規模（一次資料）から費用便益で額を付ける（covid-benefit-v1）。

背景：macro-v1 は、コロナ対応の法律に額を付けなかった。全体指標の差はコロナの落ち込みそのもので、その法律の効果ではないから。
比べるべきは「コロナはあったが、その法律が無かった場合」で、定説（財政乗数・雇用維持の効果）では落ち込みを和らげる向き（便益）。
そこで法律に直接結びつく支出の規模を官公庁の一次資料から取り（data/acquired/covid-spending/）、定番の費用便益の式で便益の額にする。

式（設計決定0014 決定12、app/src/method-spec.ts の covid-benefit-v1）：
  B^(q) = S^(q) × a^(q) × m^(q)        q ∈ {下, 中, 上}
  S：法律に結びつく支出の規模（円）。a：法律への帰属割合。m：支出が付加価値に回る割合（乗数）。
  移転そのものは便益にも損失にも数えない（費用便益の定番）。数えるのは、移転が守った・下支えした消費や雇用の分だけ。
  財源調達の超過負担（死荷重）は、官公庁の単価が見つからなかったので差し引いていない（総便益）。
  幅の下・中・上は、帰属と乗数の仮定の幅。確かさは常に「参考」（議員への配分に使わない）。
規模は取れたが換算の乗数・単価が定番の資料に無い法律は、額を出さず規模と理由を残す。

入力：data/acquired/covid-spending/spending.csv（項目ごとの金額・出典URL・原文の抜粋）、data/derived/covid-benefit-v1/rules.csv（法律ごとの式の入力）
出力：data/derived/covid-benefit-v1/benefit.csv
使い方：python3 scripts/build_covid_benefit.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPENDING = ROOT / "data" / "acquired" / "covid-spending" / "spending.csv"
RULES = ROOT / "data" / "derived" / "covid-benefit-v1" / "rules.csv"
LABELS = ROOT / "data" / "derived" / "covid-response-v1" / "labels.csv"
OUT = ROOT / "data" / "derived" / "covid-benefit-v1" / "benefit.csv"
HEADER = ["id", "題名", "型", "結果", "窓", "中央値", "第1四分位", "第3四分位", "支出の規模（円）", "帰属", "乗数", "計算式の要素", "根拠", "理由"]
QUANTILES = ("下", "中", "上")
ITEM = re.compile(r"\[([^\]]+)\]")
SAFE = re.compile(r"[0-9.+\-*/() ]+")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def evaluate(expr: str, items: dict[str, int]) -> float:
    """[項目ID] を金額に置き換えた四則演算だけを計算する。"""
    def sub(m: re.Match[str]) -> str:
        if m.group(1) not in items:
            raise ValueError(f"支出の項目がありません: {m.group(1)}")
        return str(items[m.group(1)])

    text = ITEM.sub(sub, expr)
    if not SAFE.fullmatch(text):
        raise ValueError(f"式に使えない文字があります: {expr}")
    return float(eval(text, {"__builtins__": {}}, {}))  # noqa: S307 四則演算と数字だけ（上で検査済み）


def build() -> list[dict[str, str]]:
    items = {r["項目ID"]: int(r["金額（円）"]) for r in _read(SPENDING)}
    titles = {r["id"]: r["題名"] for r in _read(LABELS)}
    rows = []
    for rule in _read(RULES):
        row = {h: "" for h in HEADER}
        row.update({"id": rule["id"], "題名": titles.get(rule["id"], ""), "型": rule["型"], "結果": rule["結果"], "理由": rule["理由"]})
        if rule["結果"] == "額":
            s = [evaluate(rule[f"支出_{q}"], items) for q in QUANTILES]
            a = [evaluate(rule[f"帰属_{q}"], items) for q in QUANTILES]
            m = [float(rule[f"乗数_{q}"]) for q in QUANTILES]
            b = [x * y * z for x, y, z in zip(s, a, m)]
            if not b[0] <= b[1] <= b[2] or b[1] <= 0 or not all(0 <= v <= 1 for v in a):
                raise ValueError(f"幅の並びか帰属割合が不正です: {rule['id']} {b} {a}")
            # macro-v1 と同じ符号：負が便益。第1四分位が最も大きい便益、第3四分位が最も小さい便益。
            row.update({
                "窓": rule["窓"], "中央値": str(-round(b[1])), "第1四分位": str(-round(b[2])), "第3四分位": str(-round(b[0])),
                "支出の規模（円）": "・".join(str(round(v)) for v in s), "帰属": "・".join(f"{v:.4g}" for v in a),
                "乗数": "・".join(f"{v:.4g}" for v in m),
                "計算式の要素": "支出の規模 × 帰属 × 乗数（下・中・上）：" + "／".join(f"{round(x)}円×{y:.4g}×{z:.4g}" for x, y, z in zip(s, a, m)),
                "根拠": rule["根拠"],
            })
        rows.append(row)
    return rows


def main() -> int:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    amounted = [r for r in rows if r["結果"] == "額"]
    print(f"額 {len(amounted)}本／理由 {len(rows) - len(amounted)}本")
    for r in amounted:
        print(r["id"], r["中央値"], r["第1四分位"], r["第3四分位"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
