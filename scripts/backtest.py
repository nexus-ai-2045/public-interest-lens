#!/usr/bin/env python3
"""計算式のバックテスト（backtest-v1）。答えの分かっている事例（学術文献の事後評価）を正解にして、現行の計算の向きを当てる。

正解   data/evidence/backtest_cases.json   事例集の「照合＝一致」49件。識別・指標・便益の向きは2系統が一致したラベルだけ使う
対応表 data/evidence/backtest_mapping.json 政策グループ → 現行の計算の法律（結果を見る前に固定）
予測   app/public/distribution/laws.json   法律ごとの向き（side：loss＝国賊側／benefit＝国士側）と参考の額
定義   docs/adr/0020-backtest-accuracy-definition.md

使い方:
  python3 scripts/backtest.py                          今のデータで測って表示する（書かない。CI はこれを毎回回す）
  python3 scripts/backtest.py --snapshot v1 --date 2026-10-29   結果を data/evidence/backtest/v1.json に固定し、配布用を更新
  python3 scripts/backtest.py --publish                snapshots から app/public/distribution/backtest.json を作り直す
  python3 scripts/backtest.py --json                   結果を JSON で標準出力に出す
2回目の測定は、実装が済んだあとに --snapshot v2 --date <日付> を回すだけでよい。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "evidence" / "backtest_cases.json"
MAPPING = ROOT / "data" / "evidence" / "backtest_mapping.json"
LAWS = ROOT / "app" / "public" / "distribution" / "laws.json"
SPEC = ROOT / "app" / "src" / "method-spec.ts"
SNAP_DIR = ROOT / "data" / "evidence" / "backtest"
PUBLIC = ROOT / "app" / "public" / "distribution" / "backtest.json"
DOC = ROOT / "docs" / "バックテスト.md"
VERSION = "backtest-v1"
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
    levels = [summarize(items, lv, len(laws)) for lv, _, _ in LEVELS]
    for entry, (_, name, definition) in zip(levels, LEVELS):
        entry["name"], entry["definition"] = name, definition
    return {
        "schema": "backtest/v1",
        "version": VERSION,
        "spec_version": spec_version(),
        "target": TARGET,
        "min_n": MIN_N,
        "inputs": {"cases": sha(CASES), "mapping": sha(MAPPING), "laws": sha(LAWS), "laws_total": len(laws)},
        "cases_total": len(items),
        "funnel": {
            "total": len(items),
            "excluded_by_reason": reasons,
            "scorable_l2": levels[2]["n"],
            "scorable_l1": levels[1]["n"],
            "scorable_l0": levels[0]["n"],
        },
        "headline": levels[0],
        "levels": levels,
        "amount_and_interval": {
            "status": "測れない",
            "n": 0,
            "reason": "正解は『生産性が年1.6%上がった』『料金が23bp下がった』のような指標ごとの効果で、現行の計算が出す法律ごとの円の額（全産業か産業の付加価値の差）とは単位も範囲も違う。円に直せる件数が0なので、額の誤差と、予測区間が正解を含む割合は出せない。暫定の区間（設計書5.1）を出す計算が入った後の測定で測る。",
        },
        "excluded": [{"id": x["id"], "policy": x["policy"], "source": x["source"], "reason": x["reason"]} for x in items if x["reason"]],
    }


def render(result: dict) -> str:
    h = result["headline"]
    lines = [f"バックテスト {result['version']}（計算式 {result['spec_version']}）事例 {result['cases_total']} 件"]
    for lv in result["levels"]:
        rate = "—" if lv["rate"] is None else f"{lv['rate'] * 100:.0f}%"
        ci = "" if not lv["wilson95"] else f"（95%区間 {lv['wilson95'][0] * 100:.0f}〜{lv['wilson95'][1] * 100:.0f}%）"
        lines.append(f"  {lv['level']} {lv['name']}: 向きの一致 {lv['hits']}/{lv['n']} = {rate}{ci} → {lv['verdict']}")
    lines.append(f"  除外の理由: {result['funnel']['excluded_by_reason']}")
    lines.append(f"  額・区間: {result['amount_and_interval']['status']}")
    lines.append(f"  本命の判定: {h['verdict']}（合格の線 {result['target'] * 100:.0f}%、判定に要る件数 {result['min_n']}）")
    return "\n".join(lines)


def snapshot_files() -> list[Path]:
    return sorted(SNAP_DIR.glob("*.json"))


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


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
        "",
    ]
    for r in runs:
        out += [f"## {r['label']}（{r['date']}、計算式 {r['spec_version']}）", "", r.get("note", ""), ""]
        out += ["| 段 | 条件 | 向きの一致 | 一致率（Wilson 95%区間） | 判定 |", "|---|---|---|---|---|"]
        for lv in r["levels"]:
            ci = "" if not lv["wilson95"] else f"（{pct(lv['wilson95'][0])}〜{pct(lv['wilson95'][1])}）"
            out.append(f"| {lv['level']} {lv['name']} | {lv['definition']} | {lv['hits']}/{lv['n']} | {pct(lv['rate'])}{ci} | {lv['verdict']} |")
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
    runs.sort(key=lambda r: r["date"])
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
        (SNAP_DIR / f"{args.snapshot}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        publish()
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
