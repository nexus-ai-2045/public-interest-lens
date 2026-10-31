"""成立した全法律（3,415本）の評価台帳を、既存の表から作る（AI は呼ばない）。

1本ごとに「どこまで評価したか（分類・類型・分野・向き・額）」「どの方法で評価したか」「確かさ」
「検証の状態」を1行にする。数値は作らない。既存の表を結び付けて並べるだけ。

入力（全てリポジトリ内）：
  data/derived/all-laws-v1/outcomes.csv          全法律の結果（母集団）
  data/derived/bill-triage-v2/agreement.csv      振り分けの2系統の一致
  data/derived/bill-triage-v2/tiebreak-lines.csv 食い違いの決着（第3の判定者）
  data/derived/econ-relevance-v1/labels.csv      経済に効くかの区分
  data/derived/ai-field-v1/labels.csv            分野ラベル
  data/derived/macro-v1/macro.csv                産業の付加価値の差による参考額
  data/derived/publish-v1-triage-v2/publish.csv  公開可否
  data/derived/law-overviews-v1/overviews.csv    概要の作り方
  data/derived/evaluation-ledger-v1/sample-verdicts.csv  抜き取り検証の結果（あれば）

出力：
  data/derived/evaluation-ledger-v1/ledger.csv
  app/public/distribution/ledger-summary.json   /methodology 用の集計
  docs/評価台帳.md                              集計（手で直さない）

使い方（リポジトリのルートで）：
  python3 scripts/build_evaluation_ledger.py sample   # 抜き取り100本前後（乱数の種は固定）
  python3 scripts/build_evaluation_ledger.py build
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "derived"
LEDGER_DIR = D / "evaluation-ledger-v1"
SEED = 20261030
SAMPLE_TARGET = 100

HEADER = ["id", "題名", "分類", "分類の方法", "類型", "経済に効くか", "分野", "分野の方法", "到達点", "向き",
          "額の方法", "額（円）", "確かさ", "公開可否", "概要の方法", "常識検査③", "頑健性④", "同型の誤り候補⑤", "ロジック検査", "検証状態", "検証メモ"]
VERIFY_STATES = ("未検証", "分類を2系統で照合済み", "分類を第3判定で決着", "抜き取り検証で合格", "抜き取り検証で不合格")


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows}


def load():
    return {
        "out": read(D / "all-laws-v1" / "outcomes.csv"),
        "agree": by_id(read(D / "bill-triage-v2" / "agreement.csv")),
        "tie": by_id(read(D / "bill-triage-v2" / "tiebreak-lines.csv")),
        "econ": by_id(read(D / "econ-relevance-v1" / "labels.csv")),
        "field": by_id(read(D / "ai-field-v1" / "labels.csv")),
        "macro": by_id(read(D / "macro-v1" / "macro.csv")),
        "pub": by_id(read(D / "publish-v1-triage-v2" / "publish.csv")),
        "ov": by_id(read(D / "law-overviews-v1" / "overviews.csv")),
        "sample": by_id(read(LEDGER_DIR / "sample-verdicts.csv")),
    }


def classification(o: dict, a: dict | None, t: dict | None) -> tuple[str, str]:
    """(分類, 分類の方法)"""
    if a is None:
        route = o["経路"]
        if o["結果"] == "効果なし（定例）":
            return "評価対象外", "題名の語の規則（定例の改正）"
        if o["結果"] == "評価対象外":
            return "評価対象外", "題名の語の規則（定型改正・組織手続）"
        return {"保留": "保留", "測定できない": "評価対象"}.get(o["結果"], "保留"), f"題名の語の規則（{route}）"
    verdict = a["系統1_判定"] if a["解消規則"] == "" and a["結果"] == "採用" else None
    if a["結果"] == "保留":
        return "保留", "2系統が不一致のまま規則で保留"
    if t is not None:
        verdict = {"系統1": a["系統1_判定"], "系統2": a["系統2_判定"]}.get(t["採用"], a["系統1_判定"])
        how = {"一致": "2系統の食い違い→第3の判定者が一致", "Sonnetが決定": "2系統の食い違い→Sonnetが決定",
               "Opusが修正": "2系統の食い違い→Opusが修正", "規則で保留": "2系統の食い違い→規則で保留"}.get(t["決め方"], "2系統の食い違い→第3の判定者")
        return verdict or "保留", how
    if a["解消規則"]:
        return a["系統1_判定"], f"2系統の食い違い→規則 {a['解消規則']}"
    return verdict or a["系統1_判定"], "2系統が一致"


def reach(o: dict, m: dict | None) -> tuple[str, str, str]:
    """(到達点, 額の方法, 額)"""
    if o["結果"] == "額あり" and o["経路"] == "財政（税収見込み）":
        return "国の収支の額（GDP とは別欄）", "財務省の税制改正による国税の増減収見込み（順位・配分に使わない）", o["損失または便益の額"]
    if o["結果"] == "額あり":
        return "額（個別の因果の鎖）", "産業別の差の差・合成対照など（法律ごと）", o["損失または便益の額"]
    if m is not None and m["結果"] == "額":
        return "参考額（産業の付加価値の差）", "OECD 同産業の中央値との差（macro-v1、順位・議員配分に使わない）", m["中央値"]
    if o["結果"] == "保留":
        return "保留", "なし", ""
    if o["結果"] == "測定できない":
        return "測定できない", "なし", ""
    if o["結果"] == "効果なし（定例）":
        return "効果なし（定例）", "なし", ""
    return "評価対象外", "なし", ""


NARROW_WORDS = ("特例", "特定", "臨時", "暫定", "特別措置")


def sense_checks(rows_macro: dict[str, dict]) -> dict[str, dict]:
    """③常識の歯止め（規模・重なり）と④頑健性（四分位が0をまたぐか）。macro-v1 の参考額だけが対象。"""
    shared = Counter((m["産業"], m["窓"], m["中央値"]) for m in rows_macro.values() if m["結果"] == "額")
    out = {}
    for i, m in rows_macro.items():
        if m["結果"] != "額":
            continue
        va = re.search(r"名目付加価値 ([\d.]+)百万円", m["計算式の要素"])
        scale = "規模不明"
        if va:
            ratio = abs(float(m["中央値"])) / (float(va.group(1)) * 1e6)
            scale = "規模超過（産業の付加価値1年分を超える）" if ratio > 1 else "規模内"
        n_shared = shared[(m["産業"], m["窓"], m["中央値"])]
        overlap = f"同額が{n_shared}本で重なる（産業の差を法律ごとに分けていない）" if n_shared > 1 else "重ならない"
        crosses = float(m["第1四分位"]) < 0 < float(m["第3四分位"])
        out[i] = {"scale": scale, "overlap": overlap,
                  "robust": "四分位が0をまたぐ（向きが定まらない）" if crosses else "四分位が同じ向き",
                  "narrow_flag": bool(m["産業"] == "_T" or m["分野"] == "経済全体")}
    return out


def verify_state(id_: str, cls_how: str, sample: dict) -> tuple[str, str]:
    s = sample.get(id_)
    if s:
        ok = s["判定"] == "合格"
        return ("抜き取り検証で合格" if ok else "抜き取り検証で不合格"), s.get("食い違い", "")
    if "第3" in cls_how or "Sonnet" in cls_how or "Opus" in cls_how or cls_how.startswith("2系統の食い違い"):
        return "分類を第3判定で決着", ""
    if cls_how == "2系統が一致":
        return "分類を2系統で照合済み", ""
    return "未検証", ""


def build_rows(src) -> list[dict]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_evaluation_logic as logic
    lv = logic.check()
    rows = []
    sc = sense_checks(src["macro"])
    for o in src["out"]:
        i = o["id"]
        a, t, m = src["agree"].get(i), src["tie"].get(i), src["macro"].get(i)
        cls, how = classification(o, a, t)
        reach_, amt_how, amt = reach(o, m)
        e = src["econ"].get(i)
        f = src["field"].get(i)
        field = (m["分野"] if m else None) or o["分野"] or (f["分野"] if f else "")
        field_how = m["分野の由来"] if m else ("AI 2系統" if f else ("題名の語の規則" if o["分野"] else ""))
        pub = src["pub"].get(i)
        ov = src["ov"].get(i)
        state, memo = verify_state(i, how, src["sample"])
        rows.append({
            "id": i, "題名": o["題名"], "分類": cls, "分類の方法": how, "類型": o["種類"] or "",
            "経済に効くか": (f"{e['区分']}（{e['決め方']}）" if e else ""),
            "分野": field, "分野の方法": field_how, "到達点": reach_, "向き": o["向き"],
            "額の方法": amt_how, "額（円）": amt, "確かさ": o["確かさ"] or (m["結果"] and "参考" if m and m["結果"] == "額" else ""),
            "公開可否": (pub["公開可否"] if pub else o["公開可否"]),
            "概要の方法": ("AI 1行要約→別の読み手で照合" if ov else "概要なし"),
            "常識検査③": (f"{sc[i]['scale']}／{sc[i]['overlap']}" if i in sc else ""),
            "頑健性④": (sc[i]["robust"] if i in sc else ""),
            "同型の誤り候補⑤": ("狭い題名に全産業の額" if i in sc and sc[i]["narrow_flag"] and any(w in o["題名"] for w in NARROW_WORDS) else ""),
            "ロジック検査": "、".join(f"{k}違反" for k in logic.RULES if i in lv[k]) or "違反なし",
            "検証状態": state, "検証メモ": memo,
        })
    return rows


def coarse_method(how: str) -> str:
    if how == "2系統が一致":
        return "2系統一致"
    if how.startswith(("2系統の食い違い", "2系統が不一致")):
        return "第3判定・規則で決着"
    return "題名の語の規則"


def stratum(r: dict) -> str:
    extra = f"|分野:{r['分野の方法']}" if r["到達点"].startswith("参考額") else ""
    return f"{r['到達点']}|{coarse_method(r['分類の方法'])}{extra}"


def make_sample(rows: list[dict]) -> list[dict]:
    """到達点×分類の大区分（参考額は分野の方法も）で層をつくる。各層は最低 MIN_PER 本（層が小さければ全数）、
    残りの枠は層の大きさに比例。額の個別計算（30本）は希少で重いので別枠で10本。"""
    rng = random.Random(SEED)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[stratum(r)].append(r)
    total = len(rows)
    min_per = 3
    quota = {k: min(len(v), max(min_per, round(60 * len(v) / total))) for k, v in groups.items()}
    for k, v in groups.items():
        if k.startswith("額（個別"):
            quota[k] = min(10, len(v))
    out = []
    for k in sorted(groups):
        out += rng.sample(sorted(groups[k], key=lambda r: r["id"]), quota[k])
    return sorted(out, key=lambda r: (stratum(r), r["id"]))


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    c = lambda k: dict(Counter(r[k] for r in rows).most_common())
    samp = [r for r in rows if r["検証状態"].startswith("抜き取り")]
    ok = sum(r["検証状態"] == "抜き取り検証で合格" for r in samp)
    by_reach: dict[str, dict] = {}
    for k in sorted({r["到達点"] for r in rows}):
        rs = [r for r in rows if r["到達点"] == k]
        ss = [r for r in rs if r["検証状態"].startswith("抜き取り")]
        by_reach[k] = {"本数": len(rs), "抜き取り": len(ss), "合格": sum(r["検証状態"] == "抜き取り検証で合格" for r in ss),
                       "うち額あり": sum(bool(r["額（円）"]) for r in rs)}
    return {
        "total": n,
        "by_reach": by_reach,
        "by_classification_method": c("分類の方法"),
        "by_field_method": c("分野の方法"),
        "by_amount_method": c("額の方法"),
        "by_certainty": c("確かさ"),
        "by_verify_state": c("検証状態"),
        "logic": {k: sum(1 for r in rows if f"{k}違反" in r["ロジック検査"]) for k in ("L1", "L2", "L3", "L4", "L5", "L6")},
        "angles": {
            "③規模": dict(Counter(r["常識検査③"].split("／")[0] for r in rows if r["常識検査③"])),
            "③重なり": dict(Counter(("同額が重なる" if "重なる（" in r["常識検査③"] else "重ならない") for r in rows if r["常識検査③"])),
            "④頑健性": dict(Counter(r["頑健性④"] for r in rows if r["頑健性④"])),
            "⑤同型の誤り候補": sum(bool(r["同型の誤り候補⑤"]) for r in rows),
            "③④の両方を通った参考額": sum(1 for r in rows if r["常識検査③"].startswith("規模内／重ならない") and r["頑健性④"] == "四分位が同じ向き"),
        },
        "sample": {"n": len(samp), "pass": ok, "fail": len(samp) - ok},
        "rule": "分類の2系統照合は『分類』だけを確かめたもの。向き・類型・額まで確かめたのは抜き取り検証だけ。",
    }


def write_docs(s: dict, path: Path) -> None:
    def table(title: str, d: dict) -> str:
        lines = [f"### {title}", "", "| 区分 | 本数 | 割合 |", "|---|---|---|"]
        lines += [f"| {k or '（空）'} | {v:,} | {v / s['total']:.1%} |" for k, v in d.items()]
        return "\n".join(lines) + "\n"
    lines = [
        "# 評価台帳（全法律の評価の到達点・方法・検証状態）", "",
        "このファイルは `python3 scripts/build_evaluation_ledger.py build` が作ります。手で直さないでください。",
        f"1本ごとの表は `data/derived/evaluation-ledger-v1/ledger.csv`（{s['total']:,}本）。", "",
        f"**{s['rule']}**", "",
        "## 到達点ごとの本数と抜き取り検証", "",
        "| 到達点 | 本数 | うち額あり | 抜き取り | 合格 |", "|---|---|---|---|---|",
    ]
    lines += [f"| {k} | {v['本数']:,} | {v['うち額あり']:,} | {v['抜き取り']} | {v['合格']} |" for k, v in s["by_reach"].items()]
    lines += ["", table("分類の方法", s["by_classification_method"]), table("分野の方法", s["by_field_method"]),
              table("額の方法", s["by_amount_method"]), table("確かさ", s["by_certainty"]), table("検証状態", s["by_verify_state"]), table("③ 規模（参考額）", s["angles"]["③規模"]), table("③ 同額の重なり（参考額）", s["angles"]["③重なり"]), table("④ 頑健性（参考額）", s["angles"]["④頑健性"]), f"⑤ 同型の誤り候補（狭い題名に全産業の額）：{s['angles']['⑤同型の誤り候補']}本　／　③④を両方通った参考額：{s['angles']['③④の両方を通った参考額']}本\n"]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    src = load()
    rows = build_rows(src)
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    if cmd == "sample":
        sm = make_sample(rows)
        with (LEDGER_DIR / "sample.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, ["層", "id", "題名"])
            w.writeheader()
            w.writerows({"層": stratum(r), "id": r["id"], "題名": r["題名"]} for r in sm)
        print(f"抜き取り {len(sm)} 本（{len({stratum(r) for r in sm})} 層、種 {SEED}）")
        return 0
    with (LEDGER_DIR / "ledger.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, HEADER)
        w.writeheader()
        w.writerows(rows)
    s = summarize(rows)
    (ROOT / "app" / "public" / "distribution" / "ledger-summary.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_docs(s, ROOT / "docs" / "評価台帳.md")
    print(json.dumps(s["by_reach"], ensure_ascii=False))
    print(s["by_verify_state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
