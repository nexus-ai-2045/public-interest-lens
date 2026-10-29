"""バックテスト v2：外国の同種の政策の研究から、日本の過去の研究の向きを当てられるか（設計決定0021）。

入力（すべて data/evidence/ にあり、固定してから測る）:
  backtest_cases.json            日本の事例（正解）。研究の国が日本で、2系統が一致した便益の向きが +1/-1 のもの
  backtest_foreign_pool.json     外国の研究のプール（出典つき）
  backtest_foreign_labels.json   プールの結果指標の種類・便益の向き・出来事（2系統の独立ラベル）
  backtest_foreign_match.json    日本の研究ごとの「同種」判定（2系統の独立判定）
計算式（method-spec）は使わない。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "data" / "evidence"
POOL = EVID / "backtest_foreign_pool.json"
LABELS = EVID / "backtest_foreign_labels.json"
MATCH = EVID / "backtest_foreign_match.json"

TARGET = 0.95
MIN_N = 10
MIN_GROUPS = 5

LEVELS = [
    ("T0", "本命：外国の同種の研究（目的・産業・手段・開始時期の水準・結果指標の種類が同じ）から日本の向きを当てる",
     "目的・産業・手段が同じ／開始年の差20年以内で高所得国／結果指標の種類が同じ"),
    ("T1", "緩めた参考1：開始時期の条件を外す", "目的・産業・手段が同じ／結果指標の種類が同じ（時期は問わない）"),
    ("T2", "緩めた参考2：結果指標の種類の条件を外す", "目的・産業・手段が同じ／開始年の差20年以内で高所得国（結果指標の種類は問わない）"),
]


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


def targets(cases: list[dict]) -> list[dict]:
    out = []
    for c in cases:
        a = c["labels"]["agreed"]
        if a["country"] == "日本" and a["benefit_sign"] in (1, -1) and c["link"] and c["group"]:
            out.append(c)
    return out


def _agreed(line1: dict, line2: dict) -> dict:
    out = {}
    for key in ("outcome_class", "benefit_sign"):
        out[key] = line1[key] if line1[key] == line2[key] else None
    return out


def foreign_labels(pool: list[dict], labels: dict) -> dict[str, dict]:
    """プールの各研究の合意ラベルと出来事（2系統のどちらかが同じ名前を付けた研究どうしをつなぐ）。"""
    ent = labels["entries"]
    parent = {e["id"]: e["id"] for e in pool}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for line in ("line1", "line2"):
        first: dict[str, str] = {}
        for e in pool:
            slug = ent[e["id"]][line]["cluster"]
            if slug in first:
                parent[find(e["id"])] = find(first[slug])
            else:
                first[slug] = e["id"]
    out = {}
    for e in pool:
        i = e["id"]
        ag = _agreed(ent[i]["line1"], ent[i]["line2"])
        held = []
        if ag["outcome_class"] is None:
            held.append("結果指標の種類")
        if ag["benefit_sign"] is None and ent[i]["line1"]["benefit_sign"] != ent[i]["line2"]["benefit_sign"]:
            held.append("便益の向き")
        out[i] = {**ag, "event": find(i), "held": held, "usable": ag["outcome_class"] is not None and ag["benefit_sign"] in (1, -1, 0)}
    return out


def agreed_matches(match: dict, target_id: str) -> dict[str, dict]:
    """2系統が一致して a,b,c を満たすとした外国の研究と、d の合意（両方 true のときだけ true）。"""
    t = match["targets"].get(target_id, {"line1": [], "line2": []})
    one = {x["fg"]: x["d"] for x in t["line1"]}
    two = {x["fg"]: x["d"] for x in t["line2"]}
    return {fg: {"d": bool(one[fg] and two[fg])} for fg in one if fg in two}


def predict(target: dict, level: str, pool_by_id: dict, flab: dict, match: dict) -> dict:
    t_class = target["labels"]["agreed"]["outcome_class"]
    used = []
    for fg, m in agreed_matches(match, target["id"]).items():
        lab = flab[fg]
        if not lab["usable"]:
            continue
        same_class = lab["outcome_class"] == t_class
        ok = {"T0": m["d"] and same_class, "T1": same_class, "T2": m["d"]}[level]
        if ok:
            e = pool_by_id[fg]
            used.append({"fg": fg, "authors": e["authors"], "year": e["year"], "country": e["country"], "outcome_class": lab["outcome_class"], "sign": lab["benefit_sign"], "event": lab["event"]})
    if not used:
        return {"predicted": None, "reason": "同種の外国の研究が無い", "foreign": []}
    by_event: dict[str, set[int]] = {}
    for u in used:
        by_event.setdefault(u["event"], set()).add(u["sign"])
    signs = set()
    for s in by_event.values():
        signs |= s if len(s) == 1 else {None}
    if len(signs) == 1 and None not in signs:
        return {"predicted": signs.pop(), "reason": None, "foreign": used}
    return {"predicted": None, "reason": "外国の研究の向きが割れた", "foreign": used}


def _stats(level: str, name: str, definition: str, items: list[dict], total: int) -> dict:
    scored = [x for x in items if x["predicted"] is not None]
    n = len(scored)
    k = sum(1 for x in scored if x["hit"])
    ci = wilson(k, n)
    rate = k / n if n else None
    groups = len({x["group"] for x in scored})
    if n < MIN_N or groups < MIN_GROUPS:
        verdict = "判定不能"
    else:
        verdict = "達成" if rate >= TARGET else "未達"
    pos = sum(1 for x in scored if x["truth"] == 1)
    base = max(pos, n - pos) / n if n else None
    return {
        "level": level, "name": name, "definition": definition, "n": n, "hits": k, "rate": rate,
        "wilson95": list(ci) if ci else None, "groups": groups, "verdict": verdict,
        "targets": total, "coverage": n / total if total else None, "baseline": base,
        "cases": [{k2: v for k2, v in x.items() if k2 != "group"} | {"group": x["group"]} for x in items],
    }


def run(cases: list[dict]) -> dict:
    pool = json.loads(POOL.read_text(encoding="utf-8"))["entries"]
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    match = json.loads(MATCH.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in pool}
    flab = foreign_labels(pool, labels)
    tg = targets(cases)
    levels = []
    for lv, name, definition in LEVELS:
        items = []
        for c in tg:
            p = predict(c, lv, by_id, flab, match)
            truth = c["labels"]["agreed"]["benefit_sign"]
            items.append({
                "id": c["id"], "group": c["group"], "policy": c["policy"], "source": f"{c['source']['authors'].split(';')[0]} {c['source']['year']}",
                "outcome_class": c["labels"]["agreed"]["outcome_class"], "truth": truth, "predicted": p["predicted"],
                "hit": p["predicted"] is not None and p["predicted"] == truth, "reason": p["reason"],
                "foreign": [{k: v for k, v in u.items() if k != "event"} for u in p["foreign"]],
            })
        levels.append(_stats(lv, name, definition, items, len(tg)))
    # 結果指標の種類ごとの T0（届かない種類は暫定値を出さない：設計決定0021の8）
    by_class = {}
    for cls in sorted({x["outcome_class"] for x in levels[0]["cases"] if x["outcome_class"]}):
        sub = [x for x in levels[0]["cases"] if x["outcome_class"] == cls]
        scored = [x for x in sub if x["predicted"] is not None]
        k = sum(1 for x in scored if x["hit"])
        n = len(scored)
        by_class[cls] = {"targets": len(sub), "n": n, "hits": k, "rate": k / n if n else None,
                         "verdict": "判定不能" if n < MIN_N else ("達成" if k / n >= TARGET else "未達"),
                         "provisional_value": "出さない"}
    held = sorted(i for i, v in flab.items() if v["held"])
    split = 0
    for t in match["targets"].values():
        a = {x["fg"] for x in t["line1"]}
        b = {x["fg"] for x in t["line2"]}
        split += len(a ^ b)
    return {
        "schema": "backtest-transplant/v1",
        "target": TARGET, "min_n": MIN_N, "min_groups": MIN_GROUPS,
        "pool": {"entries": len(pool), "usable": sum(1 for v in flab.values() if v["usable"]),
                 "labels_held": held, "events": len({v["event"] for v in flab.values()}),
                 "from_cases": sum(1 for e in pool if e["origin"].startswith("cases:")), "from_search": sum(1 for e in pool if e["origin"].startswith("search:"))},
        "match_splits": split,
        "levels": levels,
        "headline": levels[0],
        "by_outcome_class": by_class,
        "note": "向きの一致だけを測る。外国の効果の大きさ（額）を日本に移す精度は測らない。基準は、予測が出せた事例で毎回最頻の向きを答えたときの一致率。",
    }
