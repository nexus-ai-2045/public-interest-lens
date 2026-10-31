"""OECD STAN・MSTI の原本 CSV から、原因の軸（cause-axis）に要る分だけを取り出して固定入力にする（task-id oecd-stan）。

原本は OECD の SDMX API（sdmx.oecd.org）から取った CSV（2026-10-23 取得。上限 4M 文字を超えるので Git に入れない）。
取り出すもの（data/acquired/oecd-stan/ に書く）：
- stan_va.csv      : STAN 2025年版の付加価値 B1G（V=名目、L=連鎖実質）。産業は _T・J・J58T60・J61・J62_63・C26・M72。単位は自国通貨（XDC）。
- employment.csv   : MSTI の就業者（TOT_EMP、千人）。比べる国の基準（2000年の就業者1人当たり GDP）と経済全体の差に使う。
- gdp2000.csv      : MSTI の2000年の GDP（購買力平価、百万米ドル）。追い上げの国を外す基準に使う。
- factors2020.csv  : STAN 2020年版の成長会計の入力（B1G 実質・名目、就業者 EMP、実質の純資本ストック N11NA、雇用者報酬 D1）。
                     就業者は単位がまちまち（PS・PS_FTE・H・JB）なので、国ごとに同じ単位に固定する（PS を優先、無ければ JB。H・PS_FTE は使わない）。

使い方：python3 scripts/prepare_oecd_stan.py <原本 CSV のあるディレクトリ>
  ディレクトリには stan_donor.csv・emp_donor.csv・gdp2000_donor.csv・stan2020_all.csv を置く。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

DST = Path("data/acquired/oecd-stan")
INDUSTRIES = ("_T", "J", "J58T60", "J61", "J62_63", "C26", "M72")
FACTOR_MEASURES = ("B1G", "EMP", "N11NA", "D1")
EMP_UNIT_ORDER = ("PS", "JB")  # 就業者の単位。H（時間）・PS_FTE（フルタイム換算）は国・産業で欠けるので使わない


def read(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def write(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def stan_va(src: Path) -> list[list]:
    rows = []
    for r in read(src):
        if r["MEASURE"] != "B1G" or r["PRICE_BASE"] not in ("V", "L") or r["ACTIVITY"] not in INDUSTRIES or not r["OBS_VALUE"]:
            continue
        rows.append([r["REF_AREA"], r["ACTIVITY"], r["PRICE_BASE"], r["TIME_PERIOD"], r["OBS_VALUE"], r["UNIT_MEASURE"]])
    return sorted(rows)


def employment(src: Path) -> list[list]:
    rows = [[r["REF_AREA"], r["TIME_PERIOD"], r["OBS_VALUE"]] for r in read(src) if r["MEASURE"] == "TOT_EMP" and r["OBS_VALUE"]]
    return sorted(rows)


def gdp2000(src: Path) -> list[list]:
    rows = [[r["REF_AREA"], r["OBS_VALUE"]] for r in read(src) if r["MEASURE"] == "GDP" and r["TIME_PERIOD"] == "2000" and r["OBS_VALUE"]]
    return sorted(rows)


def factors2020(src: Path) -> list[list]:
    """成長会計の入力。就業者は国ごと・産業ごとに単位を1つに固定する（単位が混ざると 2000 年と 2019 年の比が意味を失う）。"""
    kept: list[dict] = []
    emp_units: dict[tuple[str, str], set[str]] = {}
    for r in read(src):
        if r["ACTIVITY"] not in INDUSTRIES or r["MEASURE"] not in FACTOR_MEASURES or not r["OBS_VALUE"]:
            continue
        m, p, u = r["MEASURE"], r["PRICE_BASE"], r["UNIT_MEASURE"]
        if m == "B1G" and not (p in ("V", "L") and u == "XDC"):
            continue
        if m == "N11NA" and not (p == "L" and u == "XDC"):
            continue
        if m == "D1" and not (p == "V" and u == "XDC"):
            continue
        if m == "EMP":
            if u not in EMP_UNIT_ORDER:
                continue
            emp_units.setdefault((r["REF_AREA"], r["ACTIVITY"]), set()).add(u)
        kept.append(r)
    pick = {k: next(u for u in EMP_UNIT_ORDER if u in us) for k, us in emp_units.items()}
    rows = []
    for r in kept:
        if r["MEASURE"] == "EMP" and r["UNIT_MEASURE"] != pick[(r["REF_AREA"], r["ACTIVITY"])]:
            continue
        rows.append([r["REF_AREA"], r["ACTIVITY"], r["MEASURE"], r["PRICE_BASE"], r["UNIT_MEASURE"], r["TIME_PERIOD"], r["OBS_VALUE"]])
    return sorted(rows)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    write(DST / "stan_va.csv", ["国", "産業", "価格", "年", "値", "単位"], stan_va(src / "stan_donor.csv"))
    write(DST / "employment.csv", ["国", "年", "就業者_千人"], employment(src / "emp_donor.csv"))
    write(DST / "gdp2000.csv", ["国", "GDP2000_PPP_百万米ドル"], gdp2000(src / "gdp2000_donor.csv"))
    write(DST / "factors2020.csv", ["国", "産業", "指標", "価格", "単位", "年", "値"], factors2020(src / "stan2020_all.csv"))
    for p in sorted(DST.glob("*.csv")):
        print(p, p.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
