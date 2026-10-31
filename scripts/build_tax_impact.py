"""毎年の税制改正の法律に、政府（財務省）の増減収見込みを直接付ける。

GDP への損失ではなく「国の税収の増減見込み」（億円、平年度と初年度）。成立した法律の損失・便益の額（産業の付加価値）とは別の量で、合計せず、議員への配分にも使わない。
対象：題名が「所得税法等の一部を改正する…」「租税特別措置法等の一部を改正する…」で、施行日が4月1日の法律。年度＝施行日の年。
見込みは data/acquired/tax-revenue-estimates/estimates.csv（財務省「税制改正の概要」の増減収見込額）の個人所得課税・法人課税・資産課税の合計。
消費課税は別の法律（消費税・たばこ税・酒税など）に分かれるので足さない。見込みの表に無い年度は額を付けない（理由を書く）。
入力：data/derived/all-laws-v1/outcomes.csv（題名・施行日）、estimates.csv
出力：data/derived/tax-impact-v1/fiscal.csv
使い方（リポジトリのルートで）：python3 scripts/build_tax_impact.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

OUTCOMES = Path("data/derived/all-laws-v1/outcomes.csv")
EST = Path("data/acquired/tax-revenue-estimates/estimates.csv")
DST = Path("data/derived/tax-impact-v1/fiscal.csv")
TARGET = re.compile(r"^(所得税法|租税特別措置法)等の一部を改正する(等の)?法律案$")
KINDS = ("個人所得課税", "法人課税", "資産課税")
HEADER = ["id", "題名", "年度", "個人所得課税_億円", "法人課税_億円", "資産課税_億円", "平年度_億円", "初年度_億円", "確かさ", "出典URL", "理由"]


def num(s: str) -> int | None:
    s = s.strip()
    return int(s) if s else None


def build() -> list[list]:
    est: dict[int, dict[str, dict]] = {}
    with EST.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            est.setdefault(int(r["年度"]), {})[r["税目"]] = r
    with OUTCOMES.open(encoding="utf-8-sig", newline="") as f:
        laws = [r for r in csv.DictReader(f) if TARGET.match(r["題名"]) and r["施行日"][5:] == "04-01"]
    out = []
    for r in sorted(laws, key=lambda r: r["id"]):
        fy = int(r["施行日"][:4])
        rows = est.get(fy)
        if not rows:
            out.append([r["id"], r["題名"], fy, "", "", "", "", "", "", "", f"{fy}年度の増減収見込みが取得した表に無い"])
            continue
        per = {k: rows.get(k) for k in KINDS}
        full = sum(num(v["平年度_億円"]) or 0 for v in per.values() if v)
        first = sum(num(v["初年度_億円"]) or 0 for v in per.values() if v)
        urls = sorted({v["出典URL"] for v in per.values() if v})
        out.append([r["id"], r["題名"], fy] + [(num(per[k]["平年度_億円"]) if per[k] else "") for k in KINDS] + [full, first, "高", " ".join(urls),
                    f"政府（財務省）の{fy}年度税制改正による国税の増減収見込み（個人所得・法人・資産課税の計、マイナスは減収）。GDP への損失とは別の量"])
    return out


def main() -> None:
    rows = build()
    DST.parent.mkdir(parents=True, exist_ok=True)
    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(rows)
    print(f"税制改正の法律 {len(rows)} 本、見込みあり {sum(1 for r in rows if r[6] != '')} 本 → {DST}")


if __name__ == "__main__":
    main()
