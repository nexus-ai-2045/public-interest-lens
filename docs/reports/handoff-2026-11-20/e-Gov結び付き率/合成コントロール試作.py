"""合成コントロールの試作（測定だけ）。OECD 表6 の実質付加価値（LR）で、日本の産業×窓について
合成対照との差と、今の基準との差を並べる。numpy なしの純 Python。

合成対照との差は、期末の対数差（日本−合成）。正は日本の方が伸びた。
中央値との差は scripts/source_check.recompute の median（円、累積。正は伸び損ね）。
符号が同じは、この2つを「日本が基準より高いか」に揃えた向きが一致するか。
置換の p 値は、比較国を1つずつ処置国にした RMSPE の比（事後の RMSE / 事前の RMSE）の順位。
事前の RMSE が float64 の eps の平方根以下のときは、比を計算せず「判定できない」とする。
日本と比較国で同じ規則。比が決まらない比較国は、日本の比の方が大きいとは数えない
（分子に残し、分母からは外さない。外すと p が小さくなる）。

使い方（リポジトリのルートで）:
  python3 docs/reports/handoff-2026-11-20/e-Gov結び付き率/合成コントロール試作.py \\
    data/acquired/oecd-industry/industry_va.csv \\
    docs/reports/handoff-2026-11-20/e-Gov結び付き率/合成コントロール試作_結果.csv
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.source_check import Oecd, recompute  # noqa: E402

FIELDS = [
    "窓の始め", "窓の終わり", "産業", "比較国の数", "合成対照との差", "中央値との差",
    "符号が同じ", "処置前のRMSE", "比の判定", "判定の理由", "置換のp値",
    "プラセボの比が判定できない数", "重み上位",
]
WINDOWS = (2000, 2005, 2010, 2015)
# 対数差はおおよそ 1 の桁。これ以下の処置前 RMSE は丸めの残差と区別できず、
# 事後との比は割り算として決まらない（無限大にも NaN にもしない）。
PRE_RMSE_FLOOR = math.sqrt(sys.float_info.epsilon)
UNDETERMINED = "判定できない"
UNDETERMINED_REASON = "処置前のRMSEが数値の下限以下で、事後を事前で割る比が決まらない"


class RatioJudgment(NamedTuple):
    ratio: float | None
    status: str
    reason: str


def rmspe_ratio(pre_rmse: float, post_rmse: float) -> RatioJudgment:
    """事後/事前の比。下限以下の事前 RMSE は比にしない。日本とプラセボで同じ。"""
    if not math.isfinite(pre_rmse) or pre_rmse <= PRE_RMSE_FLOOR:
        return RatioJudgment(None, UNDETERMINED, UNDETERMINED_REASON)
    return RatioJudgment(post_rmse / pre_rmse, "計算した", "")


def permutation_p(pre_rmse: float, post_rmse: float, placebo: list[tuple[float, float]]) -> dict:
    """置換の p 値。日本の比が決まらなければ p 値も「判定できない」。
    比が決まらない比較国は、日本の比がそれより大きいとは言えないので分子に残す。
    分母は比較国の数のまま（外すと p が小さくなる）。"""
    japan = rmspe_ratio(pre_rmse, post_rmse)
    judged = [rmspe_ratio(pre, post) for pre, post in placebo]
    rows = [{"比": item.ratio, "比の判定": item.status, "判定の理由": item.reason} for item in judged]
    undetermined = sum(item.status != "計算した" for item in judged)
    if japan.status != "計算した":
        return {
            "比": None,
            "比の判定": japan.status,
            "判定の理由": japan.reason,
            "置換のp値": UNDETERMINED,
            "プラセボ": rows,
            "プラセボの比が判定できない数": undetermined,
        }
    as_extreme = sum(
        item.status != "計算した" or item.ratio >= japan.ratio for item in judged
    )
    return {
        "比": japan.ratio,
        "比の判定": japan.status,
        "判定の理由": "",
        "置換のp値": (1 + as_extreme) / (1 + len(judged)),
        "プラセボ": rows,
        "プラセボの比が判定できない数": undetermined,
    }


def _solve_linear(matrix: list[list[float]], rhs: list[float], pivot_tol: float = 1e-12):
    """部分ピボットのガウス消去。ピボットが潰れたら None（階数不足）。"""
    size = len(rhs)
    rows = [matrix[i][:] + [rhs[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < pivot_tol:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        for j in range(col, size + 1):
            rows[col][j] /= scale
        for row in range(size):
            if row == col:
                continue
            factor = rows[row][col]
            if factor == 0.0:
                continue
            for j in range(col, size + 1):
                rows[row][j] -= factor * rows[col][j]
    return [rows[i][size] for i in range(size)]


def _constrained_weights(donors: list[list[float]], target: list[float]):
    """和が1の等式つき最小二乗。非負は見ない。階数不足なら None。"""
    width = len(donors)
    if width == 0:
        return None
    length = len(target)
    gram = [[0.0] * (width + 1) for _ in range(width + 1)]
    rhs = [0.0] * (width + 1)
    for a in range(width):
        for b in range(a, width):
            dot = sum(donors[a][t] * donors[b][t] for t in range(length))
            gram[a][b] = dot
            gram[b][a] = dot
        gram[a][width] = 1.0
        gram[width][a] = 1.0
        rhs[a] = sum(donors[a][t] * target[t] for t in range(length))
    rhs[width] = 1.0
    solved = _solve_linear(gram, rhs)
    if solved is None:
        return None
    return solved[:-1]


def _squared_error(weights: list[float], donors: list[list[float]], target: list[float]) -> float:
    return sum(
        (sum(weights[j] * donors[j][t] for j in range(len(donors))) - target[t]) ** 2
        for t in range(len(target))
    )


def _gradient(weights: list[float], donors: list[list[float]], target: list[float]) -> list[float]:
    residual = [
        sum(weights[j] * donors[j][t] for j in range(len(donors))) - target[t] for t in range(len(target))
    ]
    return [2.0 * sum(residual[t] * donors[j][t] for t in range(len(target))) for j in range(len(donors))]


def fit(donors: list[list[float]], target: list[float], it: int = 3000, tol: float = 1e-9) -> list[float]:
    """単体（重み≥0、和1）上の最小二乗。有効制約法。
    自由な重みを和1で解き、負ならその境界まで戻して制約を足す。全部非負なら、
    ゼロに固定した重みの乗数が負のものを1つ外す。KKT を満たすか、同じ制約の組に戻ったら止める。
    it=0 は初期の均等重み。反復を増やすと二乗誤差は増えない。"""
    k = len(donors)
    if k == 0:
        return []
    weights = [1.0 / k] * k
    active: set[int] = set()
    seen: set[frozenset[int]] = set()
    for _ in range(it):
        key = frozenset(active)
        if key in seen:
            break
        seen.add(key)
        free = [j for j in range(k) if j not in active]
        if not free:
            break
        solved = _constrained_weights([donors[j] for j in free], target)
        if solved is None:
            active.add(free[-1])
            continue
        if all(value >= -tol for value in solved):
            weights = [0.0] * k
            for index, value in zip(free, solved):
                weights[index] = max(value, 0.0)
            total = sum(weights)
            weights = [value / total for value in weights]
            grad = _gradient(weights, donors, target)
            lagrange = sum(grad[j] for j in free) / len(free)
            violators = [j for j in active if grad[j] - lagrange < -tol]
            if not violators:
                break
            active.remove(min(violators, key=lambda j: grad[j] - lagrange))
            continue
        candidate = [0.0] * k
        for index, value in zip(free, solved):
            candidate[index] = value
        alpha = 1.0
        blocking = None
        for j in free:
            if candidate[j] < -tol and candidate[j] < weights[j]:
                bound = weights[j] / (weights[j] - candidate[j])
                if 0.0 <= bound < alpha:
                    alpha = bound
                    blocking = j
        if blocking is None:
            for j in free:
                if candidate[j] < 0.0:
                    active.add(j)
            weights = [max(candidate[j], 0.0) for j in range(k)]
            total = sum(weights) or 1.0
            weights = [value / total for value in weights]
            continue
        weights = [weights[j] + alpha * (candidate[j] - weights[j]) for j in range(k)]
        weights[blocking] = 0.0
        active.add(blocking)
        total = sum(weights)
        weights = [value / total for value in weights]
    return weights


def production_median_yen(oecd: Oecd, industry: str, start: str, end_year: int, countries: list[str]):
    """今の基準。定義は source_check.recompute だけが持つ。円の累積で、正は伸び損ね。"""
    result = recompute(oecd, industry, start, end_year, countries)
    if result is None:
        return None
    return result["median"]


def same_direction(synth_log_gap: float, median_yen: float) -> bool:
    """合成の期末対数差（正＝日本の方が伸びた）と、本番の中央値（正＝伸び損ね）の向きが同じか。"""
    return (synth_log_gap > 0) == (median_yen < 0)


def log_series(table: dict, country: str, industry: str, years: list[int], base: int):
    series = table.get((country, industry), {})
    if any(year not in series for year in years) or base not in series:
        return None
    if series[base] <= 0 or any(series[year] <= 0 for year in years):
        return None
    return [math.log(series[year]) - math.log(series[base]) for year in years]


def fit_gap(target: list[float], pool: list[list[float]], npre: int):
    weights = fit([series[:npre] for series in pool], target[:npre])
    synthetic = [sum(weights[j] * pool[j][t] for j in range(len(pool))) for t in range(len(target))]
    pre = statistics.mean((target[t] - synthetic[t]) ** 2 for t in range(npre))
    post = statistics.mean((target[t] - synthetic[t]) ** 2 for t in range(npre, len(target)))
    gap = target[-1] - synthetic[-1]
    return weights, gap, math.sqrt(pre), math.sqrt(post)


def build_rows(oecd: Oecd) -> list[dict]:
    table = {(country, industry): series for (country, industry, price), series in oecd.series.items() if price == "LR"}
    industries = sorted({industry for country, industry in table if country == "JPN" and industry != "_T"}) + ["_T"]
    rows = []
    for start_year in WINDOWS:
        pre = list(range(start_year - 6, start_year))
        post = list(range(start_year, min(start_year + 10, 2024)))
        years = pre + post
        base = start_year - 1
        npre = len(pre)
        for industry in industries:
            japan = log_series(table, "JPN", industry, years, base)
            if not japan:
                continue
            donors = {}
            for country, donor_industry in table:
                if country == "JPN" or donor_industry != industry:
                    continue
                series = log_series(table, country, industry, years, base)
                if series:
                    donors[country] = series
            if len(donors) < 4:
                continue
            names = sorted(donors)
            pool = [donors[name] for name in names]
            weights, gap, pre_rmse, post_rmse = fit_gap(japan, pool, npre)
            gap = round(gap, 4)
            median = production_median_yen(oecd, industry, f"{start_year}-01-01", post[-1], names)
            if median is None:
                raise SystemExit(f"本番の中央値を計算できない: {industry} {start_year}")
            placebo_pairs = []
            for index in range(len(names)):
                others = [pool[k] for k in range(len(names)) if k != index] + [japan]
                _, _, pre_p, post_p = fit_gap(pool[index], others, npre)
                placebo_pairs.append((pre_p, post_p))
            judged = permutation_p(pre_rmse, post_rmse, placebo_pairs)
            p_value = judged["置換のp値"]
            if isinstance(p_value, float):
                p_value = round(p_value, 3)
            top = sorted(range(len(names)), key=lambda j: -weights[j])[:3]
            rows.append({
                "窓の始め": start_year,
                "窓の終わり": post[-1],
                "産業": industry,
                "比較国の数": len(names),
                "合成対照との差": gap,
                "中央値との差": median,
                "符号が同じ": same_direction(gap, median),
                "処置前のRMSE": round(pre_rmse, 4),
                "比の判定": judged["比の判定"],
                "判定の理由": judged["判定の理由"],
                "置換のp値": p_value,
                "プラセボの比が判定できない数": judged["プラセボの比が判定できない数"],
                "重み上位": ";".join(f"{names[j]}:{weights[j]:.2f}" for j in top),
            })
    return rows


def _p_at_most(row: dict, threshold: float) -> bool:
    p_value = row["置換のp値"]
    return isinstance(p_value, (int, float)) and not isinstance(p_value, bool) and p_value <= threshold


def summarize(rows: list[dict]) -> dict:
    disagree = [f"{row['窓の始め']} {row['産業']}" for row in rows if not row["符号が同じ"]]
    undetermined = [row for row in rows if row["比の判定"] != "計算した"]
    small = [row for row in rows if _p_at_most(row, 0.1)]
    return {
        "産業×窓": len(rows),
        "向きが本番の中央値と同じ": sum(bool(row["符号が同じ"]) for row in rows),
        "向きが違う組": disagree,
        "置換のp値0.1以下": len(small),
        "置換のp値0.1以下の組": [f"{row['窓の始め']} {row['産業']}" for row in small],
        "比が判定できない": len(undetermined),
        "比が判定できない組": [f"{row['窓の始め']} {row['産業']}" for row in undetermined],
        "比が判定できない理由": sorted({row["判定の理由"] for row in undetermined}),
        "プラセボで比が判定できない": sum(row["プラセボの比が判定できない数"] for row in rows),
        "処置前RMSE0.02以下": sum(1 for row in rows if row["処置前のRMSE"] <= 0.02),
        "差の中央値（合成・期末の対数。正は日本の方が伸びた）": round(
            statistics.median(row["合成対照との差"] for row in rows), 4
        ),
        "差の中央値（本番の中央値・円。正は伸び損ね）": statistics.median(row["中央値との差"] for row in rows),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit(
            "使い方: 合成コントロール試作.py <industry_va.csv> <結果.csv>"
        )
    rows = build_rows(Oecd(Path(args[0])))
    with Path(args[1]).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summarize(rows), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
