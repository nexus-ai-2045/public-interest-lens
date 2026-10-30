"""未成立の提出法案の「向き」（付加価値がプラスかマイナスか）と「提出の点」。もし成立していたら、の別欄。

成立した法律の額（all-laws-v1）や「失わせた額」とは混ぜない。実際の損失は生んでいない。
入力：data/derived/unenacted-bills-v1/scale.csv（判定＝評価対象の行だけ）
出力：data/derived/unenacted-bills-v1/direction.csv
使い方（リポジトリのルートで）：python3 scripts/build_unenacted_direction.py

方針（ねく 2026-10-30：経済だけ・機械的・属性で点を付けない）
- 題名の語だけで決まる狭い規則に限る。規則の外は「不明」で点を付けない（推測で埋めない）。
- 提出の点は ±1 の件数。規模点（産業全体の GDP 比）は掛けない：狭い法案に全産業の額を当てる誤りを繰り返さないため。
- 確かさは常に「低（題名の語）」。成立した法律の点とは別に集計し、合計に入れる重みは集計側で控えめにする。
- 財政支出型（給付・助成など）は付加価値÷国の支出（採算）が題名では分からないので向き「不明」・採算「未計算」。
  対象の国籍・出自・思想で点を付けることはしない（規則に属性の語を入れない。tests が確かめる）。
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

SRC = Path("data/derived/unenacted-bills-v1/scale.csv")
DST = Path("data/derived/unenacted-bills-v1/direction.csv")
HEADER = ["id", "題名", "向き", "提出の点", "規則", "根拠", "確かさ", "採算"]

# (符号, 向き, 正規表現, 根拠)。上から当て、最初の行で決める。向き＝付加価値の変化の符号。
RULES: list[tuple[str, str, str, str]] = [
    ("X1", "不明", r"修正案|停止|凍結|中止", "修正案、または進行中の施策の停止・凍結：向きを題名だけでは決めない"),
    ("N1", "マイナス", r"国有化|国営化|公営化|国による(?:買取|買い取)", "国有・公営化：競争と投資の誘因を弱め、同産業の付加価値を下げる（民営化・競争の実証研究の逆）"),
    ("N2", "マイナス", r"輸入(?:の)?制限|関税(?:率)?の引上げ|関税を引き上げ|新たな税|税率の引上げ|増税", "貿易制限・増税：超過負担（Harberger）で付加価値を下げる"),
    ("N3", "マイナス", r"参入(?:の)?規制|価格(?:の)?統制|公定価格の義務", "参入・価格規制：資源配分をゆがめ付加価値を下げる"),
    ("P1", "プラス", r"民営化|(?:株式)?売却(?:の)?推進", "民営化：競争と効率化で付加価値を上げる（民営化の実証研究）"),
    ("P2", "プラス", r"規制緩和|規制改革|自由化|参入(?:の)?(?:自由|促進)|規制の撤廃|競争(?:の)?促進", "規制緩和・競争促進：参入と価格競争で付加価値を上げる"),
    ("P3", "プラス", r"(?:税|税制).*(?:軽減|減免|廃止|免除|非課税|引下げ)|減税", "減税：超過負担を減らし付加価値を上げる（国の収支は別表）"),
    ("F1", "不明", r"無償化|支給|給付|助成|補助|手当|交付金|基金|支援金|補償", "財政支出型：採算（付加価値÷国の支出）が題名では分からない"),
]
NEG_PAT = [(c, re.compile(p)) for c, _, p, _ in RULES]
BY = {c: (d, w) for c, d, _, w in RULES}
# 規則に載せてはならない語（属性による判定の禁止。tests が確かめる）
FORBIDDEN_WORDS = ("朝鮮", "韓国", "中国", "外国人", "宗教", "信仰", "民族", "国籍")


def judge(title: str) -> tuple[str, str, str]:
    """(向き, 規則符号, 根拠)。組織の設置・手続だけの題名は規則に当たらず不明。"""
    for code, pat in NEG_PAT:
        if pat.search(title):
            d, why = BY[code]
            return d, code, why
    return "不明", "", "規則に当たらない（題名だけでは向きを決めない）"


def main() -> None:
    with SRC.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["判定"] == "評価対象" and r["id"].rsplit("-", 1)[-1]]
    DST.parent.mkdir(parents=True, exist_ok=True)
    n = {"プラス": 0, "マイナス": 0, "不明": 0}
    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for r in rows:
            d, code, why = judge(r["題名"])
            n[d] += 1
            pt = {"プラス": 1, "マイナス": -1}.get(d, 0)
            w.writerow([r["id"], r["題名"], d, pt, code, why, "低（題名の語）", "未計算" if code == "F1" else ""])
    print(f"評価対象 {len(rows)} 本：{n} → {DST}")


if __name__ == "__main__":
    main()
