"""伸び損ねた原因の軸の額を計算する（cause-axis-v3、docs/計算式.md「伸び損ねた原因の軸の額」）。

産業固有の差：日本の産業の実質の伸びを日本全体の実質の伸びで割った比を、比べる国の中央値と比べ、その年の名目円で換算して2001〜2023年を累計する。
経済全体の差：就業者1人当たりの実質付加価値の伸びを、比べる国の中央値と比べる。
確かさ：置換検定の順位（比べる国を1つずつ「日本の役」にして同じ差を計算し、日本の差が大きい方から何番目か）が3位以内なら「参考」、4位以下は「誤差の範囲」（額は記録だけ）。
成長会計：産業固有の差を、働く人の数・資本・全要素生産性（残り）に分ける。配る額は分ける前の差のまま。

入力：data/acquired/oecd-stan/（scripts/prepare_oecd_stan.py が作る固定入力）
出力：data/derived/cause-axis-v1/
  industry_gap.csv      産業ごとの累計・順位・確かさ・感度（韓国を除く）
  yearly.csv            産業ごとの毎年の比と差（比較画面の折れ線）
  peers.csv             産業ごと・国ごとの比（2000年=1、日本全体の伸びで割った値）
  growth_accounting.csv 成長会計の内訳
  axes.csv              軸ごとの額と扱い
  summary.json          画面用（app/src/cause-axis.json に写す）
使い方（リポジトリのルートで）：python3 scripts/build_cause_axis.py
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

SRC = Path("data/acquired/oecd-stan")
DST = Path("data/derived/cause-axis-v1")
APP_JSON = Path("app/src/cause-axis.json")

VERSION = "cause-axis-v3"
BASE, FIRST, LAST = 2000, 1995, 2023
POST_YEARS = range(BASE + 1, LAST + 1)
ALL_YEARS = range(FIRST, LAST + 1)
CATCHUP_RATIO = 0.8  # 2000年の就業者1人当たり GDP が日本の8割未満の国は追い上げの段階として外す（cause-axis-v1）
EXCLUDED_ALWAYS = {"JPN", "IRL"}  # アイルランドは多国籍企業の計上で情報通信がゆがむ
EXOGENOUS = {"C26": {"KOR"}, "J61": {"KOR"}}  # 他国の支援が強い産業は、支援の強い国を除いた額も感度として出す
RANK_REFERENCE = 3  # 置換検定の順位がこの位以内なら「参考」

# 比の定義。経済全体（_T）は「全体の伸びで割る」と自分自身で割って1になるので、就業者1人当たりの実質の伸びをそのまま使う（文書7章・仕様 cause-axis-v3 の E_t）。
MEASURE_INDUSTRY = "産業の実質付加価値の伸び ÷ 日本・各国それぞれの全体の実質の伸び（2000年＝1）"
MEASURE_TOTAL = "就業者1人当たりの実質付加価値の伸び（2000年＝1。全体の伸びでは割らない）"

INDUSTRY_NAMES = {
    "_T": "経済全体（就業者1人当たり）",
    "J": "情報通信",
    "J62_63": "IT・情報サービス",
    "J58T60": "出版・映像・放送",
    "J61": "通信",
    "C26": "電子機器",
    "M72": "研究開発サービス",
}
GAP_INDUSTRIES = ("J", "J62_63", "J58T60", "J61", "C26", "M72", "_T")
FACTOR_INDUSTRIES = ("J", "C26", "J62_63", "J61", "J58T60", "M72", "_T")
# 軸 → 結ぶ観測。同じ観測に結ぶ軸は本数で等分する（observation-split-v1）。
AXES = [
    ("E1", "大学・研究への公的支出", ["J62_63", "M72"]),
    ("F1", "VC と出口", ["J62_63"]),
    ("G1", "政府の IT 調達", ["J62_63"]),
    ("R1", "配信・著作権の規制", ["J58T60"]),
    ("C2", "通信事業者主導の端末モデル", ["J61", "C26"]),
    ("M1/M2", "金融政策・為替・デフレ／不良債権とゾンビ企業（共有）", ["_T"]),
]


def read(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


class Inputs:
    """固定入力を読み込んだもの。"""

    def __init__(self, src: Path = SRC):
        self.va: dict[tuple[str, str, str], dict[int, float]] = defaultdict(dict)
        for r in read(src / "stan_va.csv"):
            self.va[(r["国"], r["産業"], r["価格"])][int(r["年"])] = float(r["値"])
        self.emp: dict[str, dict[int, float]] = defaultdict(dict)
        for r in read(src / "employment.csv"):
            self.emp[r["国"]][int(r["年"])] = float(r["就業者_千人"])
        self.gdp2000 = {r["国"]: float(r["GDP2000_PPP_百万米ドル"]) for r in read(src / "gdp2000.csv")}
        self.factors: dict[tuple[str, str, str, str], dict[int, float]] = defaultdict(dict)
        for r in read(src / "factors2020.csv"):
            self.factors[(r["国"], r["産業"], r["指標"], r["価格"])][int(r["年"])] = float(r["値"])

    def eligible(self) -> list[str]:
        """比べる国：2000年の就業者1人当たり GDP が日本の8割以上（アイルランドは除く）。"""
        prod = {c: g / self.emp[c][BASE] for c, g in self.gdp2000.items() if self.emp[c].get(BASE)}
        jp = prod["JPN"]
        return sorted(c for c, p in prod.items() if c not in EXCLUDED_ALWAYS and p >= CATCHUP_RATIO * jp)

    def real(self, country: str, industry: str) -> dict[int, float] | None:
        """産業の実質付加価値。日本の J の内訳と M72 は実質が無いので、親（J または全体）の物価で割る（仮定。印を付ける）。"""
        real = self.va.get((country, industry, "L"))
        if real and all(t in real for t in ALL_YEARS):
            return real
        if country != "JPN":
            return None
        parent = "J" if industry.startswith("J") else "_T"
        nominal, p_nom, p_real = (self.va.get((country, i, p)) for i, p in ((industry, "V"), (parent, "V"), (parent, "L")))
        if not (nominal and p_nom and p_real) or not all(t in d for d in (nominal, p_nom, p_real) for t in ALL_YEARS):
            return None
        return {t: nominal[t] / (p_nom[t] / p_real[t]) for t in ALL_YEARS}

    def deflated(self, industry: str) -> bool:
        return self.real("JPN", industry) is not None and not self.va.get(("JPN", industry, "L"))

    def y(self, country: str, industry: str) -> dict[int, float] | None:
        """結果 y：産業固有は ln(産業の実質の伸び) − ln(全体の実質の伸び)、経済全体は ln(就業者1人当たり実質)。1995〜2023年が全部そろう国だけ。"""
        total = self.va.get((country, "_T", "L"))
        if not total or not all(t in total for t in ALL_YEARS):
            return None
        if industry == "_T":
            emp = self.emp.get(country, {})
            if not all(t in emp for t in ALL_YEARS):
                return None
            return {t: math.log(total[t] / emp[t]) for t in ALL_YEARS}
        real = self.real(country, industry)
        if real is None:
            return None
        return {t: math.log(real[t] / real[FIRST]) - math.log(total[t] / total[FIRST]) for t in ALL_YEARS}

    def nominal(self, industry: str) -> dict[int, float]:
        return self.va[("JPN", "_T" if industry == "_T" else industry, "V")]


def cumulative_gap(inputs: Inputs, industry: str, donors: list[str]) -> tuple[float, list[dict]]:
    """日本の累計の差（百万円）と毎年の内訳。差 = 日本の名目 × (exp(比較国の中央値の Δy − 日本の Δy) − 1)。"""
    jp = inputs.y("JPN", industry)
    series = [s for s in (inputs.y(d, industry) for d in donors) if s]
    nominal = inputs.nominal(industry)
    total, rows = 0.0, []
    for t in POST_YEARS:
        peer = statistics.median(s[t] - s[BASE] for s in series)
        own = jp[t] - jp[BASE]
        gap = nominal[t] * (math.exp(peer - own) - 1)
        total += gap
        rows.append({"年": t, "日本の比": math.exp(own), "比較国の中央値の比": math.exp(peer), "差_百万円": gap})
    return total, rows


def placebo_rank(inputs: Inputs, industry: str, donors: list[str]) -> tuple[int, int, str]:
    """置換検定の順位。比べる国を1つずつ「日本の役」にして、残りの国の中央値との差（2023年の Δy）を出し、日本の差が大きい方から何番目か。
    日本の差が負（日本の方が伸びた）なら便益として、負に大きい方から数える。"""
    series = {d: s for d in donors if (s := inputs.y(d, industry))}
    jp = inputs.y("JPN", industry)

    def gap(own: dict[int, float], others: list[dict[int, float]]) -> float:
        return statistics.median(o[LAST] - o[BASE] for o in others) - (own[LAST] - own[BASE])

    jp_gap = gap(jp, list(series.values()))
    placebos = [gap(series[d], [s for k, s in series.items() if k != d]) for d in series]
    if jp_gap >= 0:
        return 1 + sum(1 for p in placebos if p >= jp_gap), len(placebos) + 1, "損失"
    return 1 + sum(1 for p in placebos if p <= jp_gap), len(placebos) + 1, "便益"


def peer_ratios(inputs: Inputs, industry: str, donors: list[str]) -> list[dict]:
    """比較画面用：国ごとの比（2000年=1、全体の伸びで割った産業の実質の伸び）の2023年と推移。"""
    out = []
    for c in ["JPN", *donors]:
        s = inputs.y(c, industry)
        if s:
            out.append({"国": c, "比": {t: math.exp(s[t] - s[BASE]) for t in range(BASE, LAST + 1)}})
    return out


def donors_for(inputs: Inputs, industry: str, eligible: list[str], exclude: set[str] = frozenset()) -> list[str]:
    return [c for c in eligible if c not in exclude and inputs.y(c, industry)]


def industry_results(inputs: Inputs) -> dict[str, dict]:
    eligible = inputs.eligible()
    out = {}
    for ind in GAP_INDUSTRIES:
        donors = donors_for(inputs, ind, eligible)
        total, yearly = cumulative_gap(inputs, ind, donors)
        rank, n, direction = placebo_rank(inputs, ind, donors)
        res = {
            "産業": ind, "名称": INDUSTRY_NAMES[ind], "比較国": donors, "累計_兆円": total / 1e6, "向き": direction,
            "順位": rank, "母数": n, "確かさ": "参考" if rank <= RANK_REFERENCE else "誤差の範囲",
            "日本の実質": "親の物価で割った（仮定）" if inputs.deflated(ind) else "OECD の実質",
            "yearly": yearly, "peers": peer_ratios(inputs, ind, donors),
        }
        if ind in EXOGENOUS:
            sens = donors_for(inputs, ind, eligible, EXOGENOUS[ind])
            res["韓国を除く_累計_兆円"] = cumulative_gap(inputs, ind, sens)[0] / 1e6
            res["韓国を除く_順位"], res["韓国を除く_母数"], _ = placebo_rank(inputs, ind, sens)
        out[ind] = res
    return out


def axis_rows(results: dict[str, dict]) -> list[dict]:
    """軸ごとの額と扱い。同じ観測に結ぶ軸は本数で等分し、同じ軸に損失と便益が結ぶときは相殺した純額を使う。誤差の範囲の産業は額に入れず記録だけ。"""
    shared = defaultdict(int)
    for _, _, inds in AXES:
        for i in inds:
            shared[i] += 1
    rows = []
    for code, name, inds in AXES:
        parts, recorded = [], []
        for i in inds:
            r = results[i]
            (parts if r["確かさ"] == "参考" else recorded).append(i)
        amount = sum(results[i]["累計_兆円"] / shared[i] for i in parts) if parts else None
        row = {
            "軸": code, "名称": name, "結ぶ観測": "・".join(INDUSTRY_NAMES[i] for i in inds),
            "額_兆円": amount, "額に入れた観測": "・".join(parts), "記録だけの観測": "・".join(recorded),
            "同じ観測を共有する軸数": max(shared[i] for i in inds),
        }
        if code == "M1/M2":
            row["扱い"] = "参考（決定の効果の推定ができるまで配らない）" if parts else "記録だけ"
        elif amount is None:
            row["扱い"] = "記録だけ（誤差の範囲）"
        elif amount < 0:
            row["扱い"] = "便益の方が大きい（損失の額はつけない）"
        else:
            row["扱い"] = "参考"
        rows.append(row)
    return rows


def decompose(inputs: Inputs, country: str, industry: str, end: int) -> dict | None:
    """成長会計：2000年→end の対数の伸びを、働く人の数・資本・全要素生産性（残り）に分ける。"""
    f = inputs.factors
    y = f.get((country, industry, "B1G", "L"))
    emp = f.get((country, industry, "EMP", "_Z"))
    cap = f.get((country, industry, "N11NA", "L"))
    pay = f.get((country, industry, "D1", "V"))
    nom = f.get((country, industry, "B1G", "V"))
    if not y or BASE not in y or end not in y:
        return None
    years = [t for t in range(BASE, end + 1) if pay and nom and t in pay and t in nom]
    share = min(0.95, sum(pay[t] / nom[t] for t in years) / len(years)) if years else None
    out: dict[str, float | None] = {"Y": math.log(y[end] / y[BASE])}
    out["L"] = share * math.log(emp[end] / emp[BASE]) if emp and share is not None and BASE in emp and end in emp else None
    out["K"] = (1 - share) * math.log(cap[end] / cap[BASE]) if cap and share is not None and BASE in cap and end in cap else None
    out["TFP"] = out["Y"] - out["L"] - out["K"] if out["L"] is not None and out["K"] is not None else None
    return out


def growth_accounting(inputs: Inputs, end: int = 2019) -> list[dict]:
    """産業固有の差を要素ごとに（産業 − 経済全体）で引き、比べる国の平均と日本の差を出す。平均にするのは内訳の足し算を合わせるため。"""
    keys = ("Y", "L", "K", "TFP")
    pool = [c for c in inputs.eligible() if c != "JPN"]
    rows = []
    for ind in FACTOR_INDUSTRIES:
        jp, jp_total = decompose(inputs, "JPN", ind, end), decompose(inputs, "JPN", "_T", end)
        if not jp or jp["L"] is None or jp["K"] is None:
            rows.append({"産業": ind, "名称": INDUSTRY_NAMES[ind], "印": "日本の就業者・資本の系列が STAN に無い（内訳は出せない）"})
            continue
        rel = {k: jp[k] - (0 if ind == "_T" else jp_total[k]) for k in keys}
        peers = {}
        for c in pool:
            d, t = decompose(inputs, c, ind, end), decompose(inputs, c, "_T", end)
            if d and t and all(d[k] is not None and t[k] is not None for k in keys):
                peers[c] = {k: d[k] - (0 if ind == "_T" else t[k]) for k in keys}
        if not peers:
            rows.append({"産業": ind, "名称": INDUSTRY_NAMES[ind], "印": "比べる国で系列がそろう国が無い"})
            continue
        mean = {k: sum(p[k] for p in peers.values()) / len(peers) for k in keys}
        gap = {k: mean[k] - rel[k] for k in keys}
        share = {k: gap[k] / gap["Y"] for k in ("L", "K", "TFP")} if abs(gap["Y"]) > 1e-9 else None
        flag = "人の数の差が大きい" if share and abs(share["L"]) > 0.5 else "なし"
        rows.append({"産業": ind, "名称": INDUSTRY_NAMES[ind], "比較国": sorted(peers), "期間": f"{BASE}→{end}",
                     "差_全体": gap["Y"], "差_人の数": gap["L"], "差_資本": gap["K"], "差_全要素生産性": gap["TFP"],
                     "割合_人の数": share["L"] if share else None, "割合_資本": share["K"] if share else None,
                     "割合_全要素生産性": share["TFP"] if share else None, "印": flag})
    return rows


def fmt(x, digits: int = 2):
    return "" if x is None else f"{x:.{digits}f}"


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build(src: Path = SRC, dst: Path = DST, app_json: Path | None = APP_JSON) -> dict:
    inputs = Inputs(src)
    results = industry_results(inputs)
    axes = axis_rows(results)
    accounting = growth_accounting(inputs)

    write_csv(dst / "industry_gap.csv",
              ["産業", "名称", "比較国数", "累計_兆円", "向き", "順位", "母数", "確かさ", "韓国を除く_累計_兆円", "韓国を除く_順位", "日本の実質"],
              [[r["産業"], r["名称"], len(r["比較国"]), fmt(r["累計_兆円"]), r["向き"], r["順位"], r["母数"], r["確かさ"],
                fmt(r.get("韓国を除く_累計_兆円")), r.get("韓国を除く_順位", ""), r["日本の実質"]] for r in results.values()])
    write_csv(dst / "yearly.csv", ["産業", "年", "日本の比", "比較国の中央値の比", "差_兆円"],
              [[r["産業"], y["年"], fmt(y["日本の比"], 4), fmt(y["比較国の中央値の比"], 4), fmt(y["差_百万円"] / 1e6, 3)]
               for r in results.values() for y in r["yearly"]])
    write_csv(dst / "peers.csv", ["産業", "国", "年", "比"],
              [[r["産業"], p["国"], t, fmt(v, 4)] for r in results.values() for p in r["peers"] for t, v in p["比"].items()])
    write_csv(dst / "growth_accounting.csv",
              ["産業", "名称", "期間", "比較国", "差_全体", "差_人の数", "差_資本", "差_全要素生産性", "割合_人の数", "割合_資本", "割合_全要素生産性", "印"],
              [[a["産業"], a["名称"], a.get("期間", ""), " ".join(a.get("比較国", [])), *(fmt(a.get(k), 3) for k in ("差_全体", "差_人の数", "差_資本", "差_全要素生産性")),
                *(fmt(a.get(k), 2) for k in ("割合_人の数", "割合_資本", "割合_全要素生産性")), a["印"]] for a in accounting])
    write_csv(dst / "axes.csv", ["軸", "名称", "結ぶ観測", "額_兆円", "額に入れた観測", "記録だけの観測", "同じ観測を共有する軸数", "扱い"],
              [[a["軸"], a["名称"], a["結ぶ観測"], fmt(a["額_兆円"]), a["額に入れた観測"], a["記録だけの観測"], a["同じ観測を共有する軸数"], a["扱い"]] for a in axes])

    summary = {
        "version": VERSION, "base": BASE, "last": LAST,
        "industries": [{
            "code": r["産業"], "name": r["名称"], "measure": MEASURE_TOTAL if r["産業"] == "_T" else MEASURE_INDUSTRY, "trillionYen": round(r["累計_兆円"], 1), "direction": r["向き"], "rank": r["順位"], "of": r["母数"],
            "certainty": r["確かさ"], "peerCount": len(r["比較国"]), "realNote": r["日本の実質"],
            "withoutKorea": None if "韓国を除く_累計_兆円" not in r else {"trillionYen": round(r["韓国を除く_累計_兆円"], 1), "rank": r["韓国を除く_順位"], "of": r["韓国を除く_母数"]},
            "series": [{"year": y["年"], "japan": round(y["日本の比"], 4), "peerMedian": round(y["比較国の中央値の比"], 4)} for y in r["yearly"]],
            "peers": [{"country": p["国"], "ratio2023": round(p["比"][LAST], 3)} for p in r["peers"]],
        } for r in results.values()],
        "axes": [{"code": a["軸"], "name": a["名称"], "observation": a["結ぶ観測"], "trillionYen": None if a["額_兆円"] is None else round(a["額_兆円"], 1),
                  "recordedOnly": a["記録だけの観測"], "sharedBy": a["同じ観測を共有する軸数"], "treatment": a["扱い"]} for a in axes],
        "accounting": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in {
            "code": a["産業"], "name": a["名称"], "period": a.get("期間"), "peers": a.get("比較国"), "gap": a.get("差_全体"),
            "labor": a.get("割合_人の数"), "capital": a.get("割合_資本"), "tfp": a.get("割合_全要素生産性"), "mark": a["印"]}.items()} for a in accounting],
    }
    if app_json is not None:
        app_json.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (dst / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    s = build()
    for i in s["industries"]:
        print(i["code"], i["name"], i["trillionYen"], f'{i["rank"]}/{i["of"]}', i["certainty"], i["direction"])
    for a in s["axes"]:
        print(a["code"], a["trillionYen"], a["treatment"])
