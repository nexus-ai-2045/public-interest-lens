"""産業×年の「その年の伸び損ね額」を作る（曝露ランキングの足す単位）。

出力：data/derived/exposure-v1/industry-year.csv（Git に置く。数百行）。

定義（産業 i・年 y ごと。OECD 表6の連鎖実質 LR と名目 V）：
    額_q(i, y) = ( 分位_q{ 比較国 c の LR[y] / LR[y-1] } − JPN の LR[y] / LR[y-1] ) × JPN の名目 V[y-1] × 1,000,000
単位は円。q = 0.25 → low、0.5 → median、0.75 → high。正が伸び損ね（比較国より伸びなかった）、負は比較国より伸びた。
比較国は、日本以外で、その産業の y-1 と y の LR がそろう国。3か国未満の年は行を出さず、理由を標準エラーに出す。

この額は「開始前の伸びの差を織り込まない、年ごとの差」である。年を足せば窓を分割しても合計が変わらない
（産業×年を足す単位にして、窓の重なりで同じ年を二重に数えないため）。
macro-v1 の累積額（開始年を基準にした水準の差の累積。開始前5年の伸びの差を織り込んだ反実仮想との差）とは別の量で、
2つの合計は一致しない。曝露ランキングは記述であって因果の推定ではない。

産業は macro.csv に結果=額で出る産業コード（_T を含む。COVID は OECD の差ではないので除く）。
年は、その産業の macro.csv の窓（「1998〜2007年」）が覆う年。
読み方は scripts/source_check.py の Oecd クラスと _quantile を使う（「M+N」のような節の足し算も同じ）。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.source_check import Oecd, _quantile

MACRO = ROOT / "data" / "derived" / "macro-v1" / "macro.csv"
OECD = ROOT / "data" / "acquired" / "oecd-industry" / "industry_va.csv"
OUT = ROOT / "data" / "derived" / "exposure-v1" / "industry-year.csv"
HEADER = ["産業", "年", "low", "median", "high", "比較国", "前年の名目付加価値_百万円"]
MIN_COUNTRIES = 3
QUANTILES = (("low", 0.25), ("median", 0.5), ("high", 0.75))
WINDOW = re.compile(r"^(\d{4})〜(\d{4})年$")


def covered_years(macro: Path) -> dict[str, set[int]]:
    """産業 → macro.csv の窓が覆う年（結果=額、COVID を除く）。"""
    out: dict[str, set[int]] = {}
    with macro.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["結果"] != "額" or row["産業"] == "COVID":
                continue
            m = WINDOW.match(row["窓"])
            if not m:
                raise ValueError(f"窓の形が読めない: {row['id']} {row['窓']}")
            out.setdefault(row["産業"], set()).update(range(int(m[1]), int(m[2]) + 1))
    return out


def build(oecd: Oecd, years_by_industry: dict[str, set[int]]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    countries = sorted({c for (c, _i, _p) in oecd.series if c != "JPN"})
    for industry in sorted(years_by_industry):
        jp = oecd.get("JPN", industry, "LR")
        nominal = oecd.get("JPN", industry, "V")
        others = {c: oecd.get(c, industry, "LR") for c in countries}
        for y in sorted(years_by_industry[industry]):
            if y - 1 not in jp or y not in jp or y - 1 not in nominal:
                skipped.append(f"{industry} {y}: 日本の LR か前年の名目付加価値が無い")
                continue
            used = [c for c, s in others.items() if y - 1 in s and y in s and s[y - 1] > 0]
            if len(used) < MIN_COUNTRIES:
                skipped.append(f"{industry} {y}: 比較国が{len(used)}か国（{MIN_COUNTRIES}か国未満）")
                continue
            ratios = [others[c][y] / others[c][y - 1] for c in used]
            jp_ratio = jp[y] / jp[y - 1]
            base_yen = nominal[y - 1] * 1_000_000
            amounts = {key: round((_quantile(ratios, q) - jp_ratio) * base_yen) for key, q in QUANTILES}
            rows.append({
                "産業": industry, "年": str(y), **{k: str(v) for k, v in amounts.items()},
                "比較国": "・".join(used), "前年の名目付加価値_百万円": f"{nominal[y - 1]:.0f}",
            })
    return rows, skipped


def render(rows: list[dict[str, str]]) -> str:
    import io
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="産業×年の「その年の伸び損ね額」（円）を OECD 表6から作る。")
    parser.add_argument("--macro", type=Path, default=MACRO, help="macro.csv（産業と窓を読む）")
    parser.add_argument("--oecd", type=Path, default=OECD, help="OECD 表6（industry_va.csv）")
    parser.add_argument("--out", type=Path, default=OUT, help="出力先（既定：data/derived/exposure-v1/industry-year.csv）")
    parser.add_argument("--check", action="store_true", help="書かずに、出力先の中身と再生成の結果が一致するか確かめる")
    args = parser.parse_args(argv)
    rows, skipped = build(Oecd(args.oecd), covered_years(args.macro))
    text = render(rows)
    for line in skipped:
        print(f"行なし: {line}", file=sys.stderr)
    if args.check:
        same = args.out.exists() and args.out.read_text(encoding="utf-8") == text
        print("一致" if same else "不一致")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"{len(rows)}行を書きました（行なし {len(skipped)}）：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
