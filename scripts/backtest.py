#!/usr/bin/env python3
"""計算式のバックテスト（backtest-v2）。答えの分かっている事例（学術文献の事後評価）を正解にして、現行の計算の向きを当てる。

正解   data/evidence/backtest_cases.json   事例集の「照合＝一致」49件。識別・指標・便益の向きは2系統が一致したラベルだけ使う
対応表 data/evidence/backtest_mapping.json 政策グループ → 現行の計算の法律（結果を見る前に固定）
予測   app/public/distribution/laws.json   法律ごとの向き（side：loss＝国賊側／benefit＝国士側）と参考の額
定義   docs/adr/0020-backtest-accuracy-definition.md（v1・v1.1）、docs/adr/0021-backtest-transplant-v2.md（v2：外国の研究から日本の向きを当てる）

使い方:
  python3 scripts/backtest.py                          今のデータで測って表示する（書かない。CI はこれを毎回回す）
  python3 scripts/backtest.py --snapshot v1 --date 2026-10-29   結果を data/evidence/backtest/v1.json に固定し、配布用を更新
  python3 scripts/backtest.py --publish                snapshots から app/public/distribution/backtest.json を作り直す
  python3 scripts/backtest.py --json                   結果を JSON で標準出力に出す
実装が済んだあとの測定は、新しい名前で --snapshot <名前> --date <日付> を回すだけでよい（固定済みの名前は上書きしない）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_transplant as tr  # noqa: E402  v2：外国の研究から日本の向きを当てる（設計決定0021）

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "evidence" / "backtest_cases.json"
MAPPING = ROOT / "data" / "evidence" / "backtest_mapping.json"
ALIGN = ROOT / "data" / "evidence" / "backtest_alignment.json"
IMPACT = ROOT / "data" / "derived" / "impact-v1-triage-v2" / "impact.csv"
LAWS = ROOT / "app" / "public" / "distribution" / "laws.json"
SPEC = ROOT / "app" / "src" / "method-spec.ts"
SNAP_DIR = ROOT / "data" / "evidence" / "backtest"
PUBLIC = ROOT / "app" / "public" / "distribution" / "backtest.json"
DOC = ROOT / "docs" / "バックテスト.md"
VERSION = "backtest-v2"
TARGET = 0.95   # 合格の線（ねく 2026-10-29）
MIN_N = 10      # これ未満は判定しない（評価方法設計書 5.3）
COMPARABLE = {"output", "employment"}   # 現行の計算の指標（産業の付加価値）と同じ向きで読める結果指標
STRONG = {"strong"}
SOLID = {"strong", "medium"}

LEVELS = [
    ("L0", "本命", "識別が強い（差の差・操作変数・RCT）／日本の研究／結果が生産か雇用／研究の対象がその法律の出来事そのもの"),
    ("L1", "条件を緩めた参考1", "識別が強いか中程度／日本の研究／結果が生産か雇用／出来事そのもの、または同じ政策分野"),
    ("L2", "条件を緩めた参考2", "日本の研究で、法律と結べて、向きが定まるもの全部（価格や余剰も便益の向きに直して比べる）"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def spec_version() -> str:
    m = re.search(r"SPEC_VERSION\s*=\s*'([^']+)'", SPEC.read_text(encoding="utf-8"))
    return m.group(1) if m else "不明"


def matched_laws(group: str | None, mapping: dict, laws: list[dict]) -> list[dict]:
    spec = mapping["groups"].get(group or "")
    if not spec:
        return []
    return [x for x in laws if x.get("side") in ("loss", "benefit") and x["year"] in spec["law_years"] and any(w in x["title"] for w in spec["title_any"])]


def predict(group: str | None, mapping: dict, laws: list[dict]) -> dict:
    """政策の予測の向き：該当する法律の向き（benefit=+1、loss=-1）の多数。同数なら 0（当たりに数えない）。"""
    found = matched_laws(group, mapping, laws)
    total = sum(1 if x["side"] == "benefit" else -1 for x in found)
    return {"laws": [{"id": x["id"], "year": x["year"], "side": x["side"], "certainty": x.get("certainty")} for x in found], "sign": (total > 0) - (total < 0)}


def classify(case: dict, mapping: dict, laws: list[dict]) -> dict:
    """1件を採点の段に振り分ける。外れた最初の理由を残す。"""
    a = case["labels"]["agreed"]
    out = {"id": case["id"], "policy": case["policy"], "source": f"{case['source']['authors']} ({case['source']['year']})", "reason": None, "levels": [], "predicted": None, "truth": None, "hit": None}
    if "country" not in case["labels"]["held"] and a["country"] != "日本":
        out["reason"] = "日本の研究ではない（現行の計算は日本の法律だけ）"
        return out
    if case["labels"]["held"]:
        out["reason"] = "ラベル保留（2系統の判定が割れた：" + "・".join(case["labels"]["held"]) + "）"
        return out
    if case["group"] is None or case["link"] is None:
        out["reason"] = "日本の法律に当てられない"
        return out
    pred = predict(case["group"], mapping, laws)
    out["predicted"] = pred
    if not pred["laws"]:
        out["reason"] = "対応する法律が現行の計算に無い（法律の一覧は1998年以降）"
        return out
    if a["benefit_sign"] == 0:
        out["reason"] = "正解の向きが定まらない（有意でない・混在・記述のみ）"
        return out
    out["truth"] = a["benefit_sign"]
    out["hit"] = pred["sign"] == a["benefit_sign"]
    out["levels"].append("L2")
    if a["design"] in SOLID and a["outcome_class"] in COMPARABLE:
        out["levels"].append("L1")
        if a["design"] in STRONG and case["link"] == "event":
            out["levels"].append("L0")
    return out


def summarize(items: list[dict], level: str, laws_total: int) -> dict:
    scored = [x for x in items if level in x["levels"]]
    k = sum(1 for x in scored if x["hit"])
    n = len(scored)
    ci = wilson(k, n)
    rate = k / n if n else None
    if n < MIN_N:
        verdict = "判定不能"
    else:
        verdict = "達成" if rate >= TARGET else "未達"
    always_benefit = sum(1 for x in scored if x["truth"] == 1)
    return {
        "level": level, "n": n, "hits": k, "rate": rate,
        "wilson95": list(ci) if ci else None,
        "verdict": verdict,
        "baseline_always_benefit_rate": (always_benefit / n) if n else None,
        "cases": [{"id": x["id"], "policy": x["policy"], "source": x["source"], "truth": x["truth"], "predicted": x["predicted"]["sign"], "hit": x["hit"], "laws": x["predicted"]["laws"]} for x in scored],
    }


ALIGNED_LEVELS = [
    ("M0", "本命（v1.1）", "識別が強い／日本の研究／研究の結果指標が計算の指標と同じ／計算がその指標で判定を出している"),
    ("M1", "条件を緩めた参考1（v1.1）", "識別が強いか中程度／結果指標が計算の指標と同じか近い代理／計算が判定を出している"),
    ("M2", "条件を緩めた参考2（v1.1）", "日本の研究で、結果指標が計算の指標と同じか近い代理で、計算が判定を出しているもの全部"),
]
STAGED = ("段階1", "段階2", "段階3")
GOOD = {"貢献": 1, "上昇": 1, "悪影響": -1, "低下": -1}


def load_alignment() -> dict:
    """研究の結果指標 → 計算の指標。2系統（私とHaiku）が一致した分だけ使う。"""
    doc = json.loads(ALIGN.read_text(encoding="utf-8"))
    out = {}
    for cid, one in doc["line1"].items():
        two = doc["line2"].get(cid)
        agree = two is not None and one["alignment"] == two["alignment"] and one["indicator"] == two["indicator"]
        out[cid] = {"alignment": one["alignment"] if agree else "保留", "indicator": one["indicator"] if agree else None, "line1": one, "line2": two}
    return out


def load_impact() -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    with IMPACT.open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            rows.setdefault(r["id"], []).append(r)
    return rows


def classify_aligned(case: dict, base: dict, align: dict, impact: dict) -> dict:
    """指標をそろえた判定：研究の結果指標と同じ指標で、法律ごとの影響の判定（段階1以上）の向きを読む。"""
    a = case["labels"]["agreed"]
    out = {"id": case["id"], "policy": case["policy"], "source": base["source"], "reason": None, "levels": [], "truth": None, "predicted": None, "hit": None, "indicator": None, "alignment": None}
    if base["predicted"] is None:   # 日本の研究でない・ラベル保留・法律に当てられない
        out["reason"] = base["reason"]
        return out
    laws = base["predicted"]["laws"]
    if not laws:   # 対象期間外など。指標の対応の集計に入れない
        out["reason"] = base["reason"] or "対応する法律が現行の計算に無い"
        return out
    al = align.get(case["id"])
    if al is None:
        out["reason"] = "日本の研究ではない（現行の計算は日本の法律だけ）"
        return out
    out["alignment"], out["indicator"] = al["alignment"], al["indicator"]
    if al["alignment"] == "保留":
        out["reason"] = "指標の対応が保留（2系統の判定が割れた）"
        return out
    if al["alignment"] == "none":
        out["reason"] = "計算に同じ指標が無い"
        return out
    signs = []
    for law in laws:
        for row in impact.get(law["id"], []):
            if row["指標"] == al["indicator"] and row["判定"] in STAGED and row["向き"] in GOOD:
                signs.append(GOOD[row["向き"]])
    if not signs:
        out["reason"] = "計算がその指標で判定を出していない（保留・比較群なし・系列なし）"
        return out
    if a["benefit_sign"] == 0:
        out["reason"] = "正解の向きが定まらない（有意でない・混在・記述のみ）"
        return out
    total = sum(signs)
    out["predicted"] = (total > 0) - (total < 0)
    out["truth"] = a["benefit_sign"]
    out["hit"] = out["predicted"] == out["truth"]
    out["levels"].append("M2")
    if a["design"] in SOLID:
        out["levels"].append("M1")
        if a["design"] in STRONG and al["alignment"] == "same":
            out["levels"].append("M0")
    return out


def summarize_aligned(items: list[dict], level: str) -> dict:
    scored = [x for x in items if level in x["levels"]]
    return _level_stats(level, scored, [{"id": x["id"], "policy": x["policy"], "source": x["source"], "truth": x["truth"], "predicted": x["predicted"], "hit": x["hit"], "indicator": x["indicator"], "alignment": x["alignment"]} for x in scored])


def _level_stats(level: str, scored: list[dict], cases: list[dict]) -> dict:
    k = sum(1 for x in scored if x["hit"])
    n = len(scored)
    ci = wilson(k, n)
    rate = k / n if n else None
    verdict = "判定不能" if n < MIN_N else ("達成" if rate >= TARGET else "未達")
    return {"level": level, "n": n, "hits": k, "rate": rate, "wilson95": list(ci) if ci else None, "verdict": verdict, "cases": cases}


def run() -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    laws_doc = json.loads(LAWS.read_text(encoding="utf-8"))
    laws = laws_doc["laws"]
    items = [classify(c, mapping, laws) for c in cases["cases"]]
    reasons: dict[str, int] = {}
    for x in items:
        key = x["reason"].split("（")[0] if x["reason"] else None
        if key:
            reasons[key] = reasons.get(key, 0) + 1
    align = load_alignment()
    impact = load_impact()
    aligned_items = [classify_aligned(c, b, align, impact) for c, b in zip(cases["cases"], items)]
    aligned_levels = [summarize_aligned(aligned_items, lv) for lv, _, _ in ALIGNED_LEVELS]
    for entry, (_, name, definition) in zip(aligned_levels, ALIGNED_LEVELS):
        entry["name"], entry["definition"] = name, definition
    jp_linked = [x for x in aligned_items if x["alignment"] is not None]
    gap_alignment: dict[str, int] = {}
    for x in jp_linked:
        gap_alignment[x["alignment"]] = gap_alignment.get(x["alignment"], 0) + 1
    gap_none: dict[str, int] = {}
    for c, x in zip(cases["cases"], aligned_items):
        if x["alignment"] == "none":
            k = c["labels"]["agreed"]["outcome_class"] or "保留"
            gap_none[k] = gap_none.get(k, 0) + 1
    gap_reasons: dict[str, int] = {}
    for x in aligned_items:
        if x["reason"] and x["alignment"] is not None:
            gap_reasons[x["reason"].split("（")[0]] = gap_reasons.get(x["reason"].split("（")[0], 0) + 1
    levels = [summarize(items, lv, len(laws)) for lv, _, _ in LEVELS]
    for entry, (_, name, definition) in zip(levels, LEVELS):
        entry["name"], entry["definition"] = name, definition
    return {
        "schema": "backtest/v1",
        "version": VERSION,
        "spec_version": spec_version(),
        "target": TARGET,
        "min_n": MIN_N,
        "inputs": {"cases": sha(CASES), "mapping": sha(MAPPING), "alignment": sha(ALIGN), "impact": sha(IMPACT), "laws": sha(LAWS), "laws_total": len(laws), "foreign_pool": sha(tr.POOL), "foreign_labels": sha(tr.LABELS), "foreign_match": sha(tr.MATCH)},
        "cases_total": len(items),
        "funnel": {
            "total": len(items),
            "excluded_by_reason": reasons,
            "scorable_l2": levels[2]["n"],
            "scorable_l1": levels[1]["n"],
            "scorable_l0": levels[0]["n"],
        },
        "headline": levels[0],
        "headline_aligned": aligned_levels[0],
        "levels": levels,
        "aligned_levels": aligned_levels,
        "transplant": tr.run(cases["cases"]),
        "alignment_gap": {
            "japan_linked_cases": len(jp_linked),
            "by_alignment": gap_alignment,
            "none_by_outcome_class": gap_none,
            "stopped_by": gap_reasons,
            "reading": "『計算に同じ指標が無い』の件数が多い。研究が見ている集団・指標（賃金、特定集団の雇用、価格・余剰、手数料）を計算側に足さないと、同じものを測れない。",
        },
        "amount_and_interval": {
            "status": "測れない",
            "n": 0,
            "reason": "正解は『生産性が年1.6%上がった』『料金が23bp下がった』のような指標ごとの効果で、現行の計算が出す法律ごとの円の額（全産業か産業の付加価値の差）とは単位も範囲も違う。円に直せる件数が0なので、額の誤差と、予測区間が正解を含む割合は出せない。暫定の区間（設計書5.1）を出す計算が入った後の測定で測る。",
        },
        "excluded": [{"id": x["id"], "policy": x["policy"], "source": x["source"], "reason": x["reason"]} for x in items if x["reason"]],
    }


def render(result: dict) -> str:
    h = result["headline_aligned"]
    lines = [f"バックテスト {result['version']}（計算式 {result['spec_version']}）事例 {result['cases_total']} 件"]
    for lv in result["levels"] + result["aligned_levels"]:
        rate = "—" if lv["rate"] is None else f"{lv['rate'] * 100:.0f}%"
        ci = "" if not lv["wilson95"] else f"（95%区間 {lv['wilson95'][0] * 100:.0f}〜{lv['wilson95'][1] * 100:.0f}%）"
        lines.append(f"  {lv['level']} {lv['name']}: 向きの一致 {lv['hits']}/{lv['n']} = {rate}{ci} → {lv['verdict']}")
    lines.append(f"  除外の理由: {result['funnel']['excluded_by_reason']}")
    lines.append(f"  指標の対応（日本の研究で法律と結べた {result['alignment_gap']['japan_linked_cases']} 件）: {result['alignment_gap']['by_alignment']}、止まった理由 {result['alignment_gap']['stopped_by']}")
    t = result["transplant"]
    for lv in t["levels"]:
        rate = "—" if lv["rate"] is None else f"{lv['rate'] * 100:.0f}%"
        lines.append(f"  {lv['level']} {lv['name']}: 向きの一致 {lv['hits']}/{lv['n']} = {rate}（出せた割合 {lv['n']}/{lv['targets']}、政策 {lv['groups']} グループ）→ {lv['verdict']}")
    lines.append(f"  額・区間: {result['amount_and_interval']['status']}")
    lines.append(f"  本命の判定（v1.1・指標をそろえた M0）: {h['verdict']}（合格の線 {result['target'] * 100:.0f}%、判定に要る件数 {result['min_n']}）")
    lines.append(f"  本命の判定（v2・外国の研究から当てる T0）: {t['headline']['verdict']}（件数 {result['min_n']} 以上かつ政策 {t['min_groups']} グループ以上）")
    return "\n".join(lines)


def snapshot_files() -> list[Path]:
    return sorted(SNAP_DIR.glob("*.json"))


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def render_transplant_doc(t: dict) -> list[str]:
    """v2：外国の同種の研究から日本の向きを当てる（設計決定0021）の節。"""
    sign = {1: "便益（国士側）", -1: "損失（国賊側）", 0: "効果なし", None: "—"}
    pool = t["pool"]
    out = ["", "### 外国の研究から日本の向きを当てる（v2、設計決定0021）", "",
           "日本の研究（向きが +1／−1 で定まるもの）を正解とし、**外国の同種の政策の研究だけ**から向きを当てられるかを測る。現行の計算は使わない。同種の判定とラベルは、日本の結果を見せない2系統が独立に付け、一致したものだけ使う。",
           f"外国の研究のプール：{pool['entries']} 件（事例集の外国の研究 {pool['from_cases']} 件＋日本の結果を見せずに調査員が集めた {pool['from_search']} 件）。ラベルが2系統で一致して使えるのは {pool['usable']} 件、割れて外したのは {len(pool['labels_held'])} 件。因果識別を確認できず測定から外したのは {len(pool.get('excluded', []))} 件（{'・'.join(pool.get('excluded', [])) or 'なし'}）。同種の判定が2系統で割れた組は {t['match_splits']} 組。", "",
           "| 段 | 条件 | 向きの一致 | 一致率（Wilson 95%区間） | 予測を出せた割合 | 政策グループ | 基準 | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for lv in t["levels"]:
        ci = "" if not lv["wilson95"] else f"（{pct(lv['wilson95'][0])}〜{pct(lv['wilson95'][1])}）"
        out.append(f"| {lv['level']} {lv['name']} | {lv['definition']} | {lv['hits']}/{lv['n']} | {pct(lv['rate'])}{ci} | {lv['n']}/{lv['targets']} | {lv['groups']} | {pct(lv['baseline'])} | {lv['verdict']} |")
    out += ["", f"合格は一致率{pct(t['target'])}以上、かつ予測を出せた事例が{t['min_n']}件以上・政策が{t['min_groups']}グループ以上。基準は、予測を出せた事例で毎回最頻の向きを答えたときの一致率。", "",
            "結果指標の種類ごとの本命（T0）：" + "、".join(f"{k} {v['hits']}/{v['n']}（対象 {v['targets']} 件、{v['verdict']}、暫定の向き・額は{v['provisional_value']}）" for k, v in t["by_outcome_class"].items()) + "。", "",
            "| 日本の事例 | 研究 | 正解の向き | 本命(T0)の予測 | 使った外国の研究（向き） |", "|---|---|---|---|---|"]
    for c in t["levels"][0]["cases"]:
        used = "、".join(f"{f['authors'].split(',')[0].split(';')[0]} {f['year']}（{sign[f['sign']]}）" for f in c["foreign"]) or "—"
        pred = sign[c["predicted"]] if c["predicted"] is not None else f"出せない（{c['reason']}）"
        out.append(f"| {c['policy'].split('（')[0]} | {c['source']} | {sign[c['truth']]} | {pred} | {used} |")
    out += ["", t["note"], ""]
    return out


def render_doc(runs: list[dict]) -> str:
    out = [
        "# バックテスト（計算式の精度）",
        "",
        "このファイルは `python3 scripts/backtest.py --publish` が `data/evidence/backtest/*.json` から作ります。手で直さないでください。",
        "定義と限界は [設計決定0020](adr/0020-backtest-accuracy-definition.md)、目標は精度95%（[評価方法設計書](評価方法設計書.md) 5章）。",
        "",
        "## 結果の読み方",
        "",
        "- 正解：学術文献の事後評価（答えの分かっている事例集、原文と一致した49件）。ラベルは2系統が独立に付け、一致したものだけ使う。",
        "- 予測：現行の計算が出す、その政策に当たる法律の向き（国賊側／国士側）。",
        "- 一致率：正解の向きと計算の向きが同じだった割合。件数が10件未満なら「判定不能」で、95%に届いたとも届かないとも言わない。",
        "- 本命（L0）の条件が厳しく件数が足りないので、条件を緩めた数字（L1・L2）も並べる。どれも同じデータ、同じ規則で出している。",
        "- v2（T0〜T2）：外国の同種の政策の研究だけから日本の向きを当てる。予測が出せなかった事例は外れに数えず、出せた割合（カバー率）を併記する。基準は毎回最頻の向きを答えたときの一致率。",
        "",
    ]
    for r in runs:
        out += [f"## {r['label']}（{r['date']}、計算式 {r['spec_version']}）", "", r.get("note", ""), ""]
        out += ["| 段 | 条件 | 向きの一致 | 一致率（Wilson 95%区間） | 判定 |", "|---|---|---|---|---|"]
        for lv in r["levels"]:
            ci = "" if not lv["wilson95"] else f"（{pct(lv['wilson95'][0])}〜{pct(lv['wilson95'][1])}）"
            out.append(f"| {lv['level']} {lv['name']} | {lv['definition']} | {lv['hits']}/{lv['n']} | {pct(lv['rate'])}{ci} | {lv['verdict']} |")
        if r.get("aligned_levels"):
            out += ["", "### 指標をそろえた測り直し（v1.1）", "", "研究の結果指標と同じ指標で、法律ごとの影響の判定（段階1以上）の向きを読む。判定を出していないものは外し、外れとは数えない。", "",
                    "| 段 | 条件 | 向きの一致 | 一致率（Wilson 95%区間） | 判定 |", "|---|---|---|---|---|"]
            for lv in r["aligned_levels"]:
                ci = "" if not lv["wilson95"] else f"（{pct(lv['wilson95'][0])}〜{pct(lv['wilson95'][1])}）"
                out.append(f"| {lv['level']} {lv['name']} | {lv['definition']} | {lv['hits']}/{lv['n']} | {pct(lv['rate'])}{ci} | {lv['verdict']} |")
            g = r["alignment_gap"]
            out += ["", f"日本の研究で法律と結べた {g['japan_linked_cases']} 件の指標の対応：" + "、".join(f"{k} {v}件" for k, v in g["by_alignment"].items()) + "。",
                    "計算に同じ指標が無かった事例の結果指標：" + "、".join(f"{k} {v}件" for k, v in g["none_by_outcome_class"].items()) + "。",
                    "指標がそろった後に止まった理由：" + ("、".join(f"{k} {v}件" for k, v in g["stopped_by"].items()) or "なし") + "。", g["reading"], ""]
            if r["aligned_levels"][2]["cases"]:
                out += ["| 事例 | 研究 | 使った指標 | 正解の向き | 計算の向き | 一致 |", "|---|---|---|---|---|---|"]
                sign2 = {1: "便益（国士側）", -1: "損失（国賊側）", 0: "同数"}
                out += [f"| {c['policy']} | {c['source']} | {c['indicator']}（{c['alignment']}） | {sign2[c['truth']]} | {sign2[c['predicted']]} | {'○' if c['hit'] else '×'} |" for c in r["aligned_levels"][2]["cases"]]
                out.append("")
        if r.get("transplant"):
            out += render_transplant_doc(r["transplant"])
        f = r["funnel"]
        out += ["", f"事例 {f['total']} 件のうち採点できなかった理由：" + "、".join(f"{k} {v}件" for k, v in f["excluded_by_reason"].items()) + "。", ""]
        out += ["額の誤差・予測区間が正解を含む割合：**" + r["amount_and_interval"]["status"] + "**。" + r["amount_and_interval"]["reason"], ""]
        out += ["### 採点した事例（L2＝条件を緩めた参考2の全件）", "", "| 事例 | 研究 | 正解の向き | 計算の向き | 一致 | 使った法律 |", "|---|---|---|---|---|---|"]
        sign = {1: "便益（国士側）", -1: "損失（国賊側）", 0: "同数"}
        for c in r["levels"][2]["cases"]:
            laws = "・".join(f"{x['id']}（{x['year']}年・{'便益' if x['side'] == 'benefit' else '損失'}）" for x in c["laws"])
            out.append(f"| {c['policy']} | {c['source']} | {sign[c['truth']]} | {sign[c['predicted']]} | {'○' if c['hit'] else '×'} | {laws} |")
        out += ["", "### 採点しなかった事例", "", "| 事例 | 研究 | 理由 |", "|---|---|---|"]
        out += [f"| {e['policy']} | {e['source']} | {e['reason']} |" for e in r["excluded"]]
        out.append("")
    return "\n".join(out)


def publish() -> dict:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in snapshot_files()]
    runs.sort(key=lambda r: (r["date"], r["label"]))
    doc = {"schema": "backtest-runs/v1", "runs": runs}
    PUBLIC.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    DOC.write_text(render_doc(runs), encoding="utf-8")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", help="結果を固定する名前（例 v1）")
    parser.add_argument("--date", help="測った日 YYYY-MM-DD（--snapshot と一緒に）")
    parser.add_argument("--note", default="", help="この測定の位置づけ（例 v1 時点：実装前）")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.publish:
        publish()
        print(f"{PUBLIC.relative_to(ROOT)} と {DOC.relative_to(ROOT)} を作り直した")
        return 0
    result = run()
    if args.snapshot:
        if not args.date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            print("--date YYYY-MM-DD が要る", file=sys.stderr)
            return 2
        result = {**result, "label": args.snapshot, "date": args.date, "note": args.note}
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        if (SNAP_DIR / f"{args.snapshot}.json").exists():
            print(f"{args.snapshot} は固定済み。基準の測定を上書きしないので、新しい名前（例 v2）で測る", file=sys.stderr)
            return 2
        (SNAP_DIR / f"{args.snapshot}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        publish()
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
