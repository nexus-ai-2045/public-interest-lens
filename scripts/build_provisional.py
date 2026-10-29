"""他国の政策カードと、日本の直近の法律への暫定評価（provisional-v1）を作る。

入力（すべてリポジトリ内）:
  data/foreign-policy-v1/cards.json            政策カードの定義（窓・比較国・4条件）。結果を見る前に固定した。
  data/acquired/foreign-policy-v1/*            世界銀行 WDI と OECD STAN の取得値（取得日は fetch の記録に従う）
  data/derived/provisional-v1/matches.csv      日本の法律と政策カードの「同種」判定（2系統の一致だけ）
  app/public/distribution/laws.json            日本の法律の一覧

出力: app/public/distribution/provisional.json

考え方（docs/adr/0016）:
  政策カード  = 他国の政策1件の、産業の伸びの差の差（比較国ごとに出し、最小〜最大を幅にする）
  暫定の額    = 同種と判定した他国の政策の「幅」 × 日本のその産業の規模。点推定・移植係数は作らない。
  確かさは「低」固定。本順位（確かな額）には入れない別枠。負の効果を 0 で切らない（幅が0をまたぐなら向き不定）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "data" / "foreign-policy-v1" / "cards.json"
ACQ = ROOT / "data" / "acquired" / "foreign-policy-v1"
THEORY = ROOT / "data" / "theory-v1" / "results.json"
NEAR = ROOT / "data" / "derived" / "provisional-v1" / "near_misses.csv"
MATCHES = ROOT / "data" / "derived" / "provisional-v1" / "matches.csv"
LAWS = ROOT / "app" / "public" / "distribution" / "laws.json"
OUTPUT = ROOT / "app" / "public" / "distribution" / "provisional.json"
VERSION = "provisional-v1"
RECENT_FROM_YEAR = 2022  # 直近4年（2026-10 時点）。この年以降の法律を暫定の対象にする
MIN_COMPARATORS = 3
JPY_UNIT = 1_000_000  # OECD STAN の UNIT_MULT=6（百万）


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_wb(path: Path) -> dict[str, dict[int, float]]:
    data: dict[str, dict[int, float]] = {}
    for row in json.loads(path.read_text())[1]:
        if row["value"] is not None:
            data.setdefault(row["countryiso3code"], {})[int(row["date"])] = float(row["value"])
    return data


def load_stan(path: Path) -> dict[tuple[str, str], dict[int, float]]:
    """(国, 価格基準) → 年 → 値。"""
    data: dict[tuple[str, str], dict[int, float]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["OBS_VALUE"]:
                mult = 10 ** int(row["UNIT_MULT"] or 0)
                data.setdefault((row["REF_AREA"], row["PRICE_BASE"]), {})[int(row["TIME_PERIOD"])] = float(row["OBS_VALUE"]) * mult
    return data


def load_stan_all(path: Path) -> dict[tuple[str, str, str], dict[int, float]]:
    """(国, 産業, 価格基準) → 年 → 値。"""
    data: dict[tuple[str, str, str], dict[int, float]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["OBS_VALUE"]:
                mult = 10 ** int(row["UNIT_MULT"] or 0)
                data.setdefault((row["REF_AREA"], row["ACTIVITY"], row["PRICE_BASE"]), {})[int(row["TIME_PERIOD"])] = float(row["OBS_VALUE"]) * mult
    return data


def growth_change(series: dict[int, float], start: int, pre: int, post: int, kind: str) -> float | None:
    """開始前の平均の伸びから開始後の平均の伸びへの変化（対数）。足りない年があれば None。"""
    if kind == "wb_growth":
        pre_years = range(start - pre + 1, start + 1)
        post_years = range(start + 1, start + post + 1)
        if any(y not in series for y in [*pre_years, *post_years]):
            return None
        before = statistics.mean(math.log(1 + series[y] / 100) for y in pre_years)
        after = statistics.mean(math.log(1 + series[y] / 100) for y in post_years)
        return after - before
    # 水準の系列（割合）
    needed = [start - pre, start, start + post]
    if any(y not in series or series[y] <= 0 for y in needed):
        return None
    return (math.log(series[start + post]) - math.log(series[start])) / post - (math.log(series[start]) - math.log(series[start - pre])) / pre


def build_card(card: dict, window: dict, crisis: list[int], wb: dict, wb_ind: dict, stan_j: dict, stan_t: dict, stan_s: dict) -> dict:
    start, pre, post = card["start_year"], window["pre_years"], window["post_years"]
    kind = card["measure"]["kind"]

    def series(country: str) -> dict[int, float]:
        if kind == "oecd_real":
            return stan_s.get((country, card["measure"]["activity"], "L"), {})
        if kind == "oecd_share":
            part = stan_j.get((country, "V"), {})
            total = stan_t.get((country, "V"), {})
            return {y: part[y] / total[y] for y in part if y in total and total[y]}
        source = wb_ind if card["measure"]["indicator"] == "NV.IND.TOTL.KD.ZG" else wb
        return source.get(country, {})

    own = growth_change(series(card["country"]), start, pre, post, kind)
    rows = []
    for country in card["comparators"]:
        other = growth_change(series(country), start, pre, post, kind)
        if own is None or other is None:
            continue
        diff = own - other
        rows.append({"country": country, "diff": diff, "gap": math.exp(post * diff) - 1})
    years = list(range(start - pre + 1, start + post + 1))
    result = {
        "id": card["id"], "country": card["country"], "countryName": card["country_name"], "title": card["title"], "startYear": start,
        "purpose": card["purpose"], "targetIndustry": card["target_industry"], "instrument": card["instrument"], "startLevel": card["start_level"],
        "measure": card["measure"]["label"], "comparators": card["comparators"], "applicableToJapan": card["applicable_to_japan"],
        "applicabilityNote": card["applicability_note"], "sourceCertainty": card["source_certainty"], "source": card["source"],
        "window": {"pre": [start - pre + 1, start], "post": [start + 1, start + post]},
        "crisisYears": [y for y in years if y in crisis],
    }
    if own is None or len(rows) < MIN_COMPARATORS:
        result["status"] = "unmeasured"
        result["reason"] = "窓の年の観測がそろう比較国が3か国に満たない"
        return result
    gaps = [row["gap"] for row in rows]
    result.update({
        "status": "measured",
        "comparatorsUsed": [row["country"] for row in rows],
        # 開始後の窓の終わりでの、反実仮想（比較国と同じ伸び）との水準の差。比較国ごとの値の最小〜最大が幅。
        "effect": {"low": min(gaps), "high": max(gaps), "perComparator": {row["country"]: round(row["gap"], 4) for row in rows}},
        "spansZero": min(gaps) < 0 < max(gaps),
    })
    return result


def main() -> int:
    spec = json.loads(CARDS.read_text())
    wb = load_wb(ACQ / "wb_manf_zg.json")
    wb_ind = load_wb(ACQ / "wb_industry_zg.json")
    stan_j = load_stan(ACQ / "oecd_stan_J59_60.csv")
    stan_t = load_stan(ACQ / "oecd_stan_total_V.csv")
    stan_s = load_stan_all(ACQ / "oecd_stan_policy_sectors.csv")
    cards = [build_card(card, spec["window"], spec["crisis_years"], wb, wb_ind, stan_j, stan_t, stan_s) for card in spec["cards"]]
    by_id = {card["id"]: card for card in cards}

    # 日本の産業の規模（円）。最新年の名目付加価値。
    content = stan_j[("JPN", "V")]
    content_year = max(content)
    jp_manf = json.loads((ACQ / "wb_jpn_manf_nominal.json").read_text())[1]
    manf_row = next(row for row in jp_manf if row["value"] is not None)
    sizes = {
        "content": {"year": content_year, "yen": content[content_year], "label": "映像・音響・放送（OECD STAN J59_60、名目）"},
        "manufacturing": {"year": int(manf_row["date"]), "yen": float(manf_row["value"]), "label": "製造業（世界銀行 NV.IND.MANF.CN、名目）"},
    }
    for key, activity, label in [("energy", "D", "電気・ガス・蒸気・空調供給（OECD STAN D、名目）"), ("health", "Q", "保健衛生・社会事業（OECD STAN Q、名目）"), ("finance", "K", "金融・保険（OECD STAN K、名目）"), ("post", "H53", "郵便・宅配（OECD STAN H53、名目）")]:
        series_v = stan_s[("JPN", activity, "V")]
        latest = max(series_v)
        sizes[key] = {"year": latest, "yen": series_v[latest], "label": label}
    industry_of = {card["id"]: card["japan_industry"] for card in spec["cards"]}

    laws = {law["id"]: law for law in json.loads(LAWS.read_text())["laws"]}
    matches: dict[str, list[str]] = {}
    if MATCHES.exists():
        with MATCHES.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                matches.setdefault(row["law_id"], []).append(row["card_id"])

    recent = [law for law in laws.values() if (law["year"] or 0) >= RECENT_FROM_YEAR]
    items = []
    for law_id, card_ids in matches.items():
        law = laws.get(law_id)
        if not law or (law["year"] or 0) < RECENT_FROM_YEAR or law["step"] == "published":
            continue
        used = [by_id[c] for c in card_ids if by_id[c]["status"] == "measured" and by_id[c]["applicableToJapan"]]
        if not used:
            continue
        industries = {industry_of[card["id"]] for card in used}
        if len(industries) != 1:
            continue
        size = sizes[industries.pop()]
        low = min(card["effect"]["low"] for card in used) * size["yen"]
        high = max(card["effect"]["high"] for card in used) * size["yen"]
        direction = "benefit" if low > 0 else "loss" if high < 0 else "unclear"
        items.append({
            "id": law["id"], "title": law["title"], "what": law.get("what"), "year": law["year"], "field": law["field"],
            "cards": [card["id"] for card in used], "amount": {"low": low, "high": high}, "direction": direction,
            "size": {"year": size["year"], "yen": size["yen"], "label": size["label"]},
            "marks": ["暫定（他国の実績を当てた幅）", "確かさ：低", "本順位に入れない", "点推定なし", *(["向きが定まらない（幅が0をまたぐ）"] if direction == "unclear" else [])],
        })
    # 並べ方：向きが決まるものを先に、その中は0に近い側の端が大きい順（上限だけを大きく見せない）
    rank = {"loss": 0, "benefit": 0, "unclear": 1}
    items.sort(key=lambda item: (rank[item["direction"]], -min(abs(item["amount"]["low"]), abs(item["amount"]["high"])) if item["direction"] != "unclear" else 0, item["id"]))

    near = []
    if NEAR.exists():
        with NEAR.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                law = laws.get(row["law_id"])
                if law:
                    near.append({"id": law["id"], "title": law["title"], "cardId": row["card_id"], "reason": row["reason"]})

    output = {
        "schema": "provisional/v1", "version": VERSION, "window": spec["window"],
        "inputs": {"cards": sha(CARDS), **({"theory": sha(THEORY)} if THEORY.exists() else {}), **{path.name: sha(path) for path in sorted(ACQ.iterdir()) if path.is_file()}, "laws": sha(LAWS)},
        "recentFromYear": RECENT_FROM_YEAR,
        "counts": {"recent": len(recent), "provisional": len(items), "unmeasured": len(recent) - len(items)},
        "cards": cards, "sizes": sizes, "items": items, "nearMisses": near, "theory": json.loads(THEORY.read_text(encoding="utf-8")) if THEORY.exists() else None,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"cards={len(cards)} measured={sum(c['status'] == 'measured' for c in cards)} recent={len(recent)} provisional={len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
