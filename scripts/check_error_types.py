"""抜き取り検証の読み直しで見つかった誤りの型を、抜き取っていない法律も含めた全法律で機械的に拾う（AI は呼ばない）。

読み直し（evaluation-ledger-v1/reverification-v1/）で、サイトの類型・分類が一次資料と合わない法律が6本あった。
同じ型の誤りが抜き取っていない法律にも残っている前提で、型ごとに「Y本中X本、どの定義で」を数え、候補を1本ずつ書き出す。
候補は「誤りの疑い」で、誤りと確定したものではない（確定は一次資料の読み直しで行う）。
一次資料で直した法律（primary-source-corrections-v1）は、直した項目の型には数えない。
機械で拾えない型：全部改正を「新規」と置いた誤り（閣法-213-45）は題名だけでは分からず、議案本文が要る。

入力：data/derived/all-laws-v1/outcomes.csv、data/derived/evaluation-ledger-v1/ledger.csv、
      data/derived/bill-triage-v1/triage.csv、data/derived/bill-triage-v2/labels-line1.csv・labels-line2.csv
出力：data/derived/error-type-check-v1/candidates.csv（id・型・根拠）、counts.json（型ごとの定義と本数）

使い方：python3 scripts/check_error_types.py [--check]   （--check は出力が今の入力から作り直したものと同じかを確かめる）
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import primary_source_corrections as corrections

D = ROOT / "data" / "derived"
OUT_DIR = D / "error-type-check-v1"
HEADER = ["id", "題名", "型", "根拠"]

NO_EFFECT_REACHES = ("評価対象外", "効果なし（定例）")  # サイトが「制度だけ（経済の量は動かない）」と扱う到達点
TAX_ANNUAL = re.compile(r"^(?:所得税法|法人税法|地方税法|租税特別措置法|関税定率法|関税暫定措置法|消費税法)(?:等|及び[^の]+)?の一部を改正")
TIME_LIMITED = ("臨時措置法", "特別措置法", "特別措置に関する法律", "緊急措置法", "臨時特例")  # 定例の規則 RT8 と同じ語
KINDS = ("新規", "実質改正", "定型改正", "組織手続")

# 型の定義（読み直しの指示文 prompt-v1 の定義に合わせる）。分母はどれも成立した全法律。
TYPES = {
    "K1": ("類型が空", "サイトの類型（all-laws-v1 の種類）が空。読み直しでは衆法-217-19"),
    "K2": ("税法の年度改正を定型改正に置いた",
           ("題名が税法（所得税法・法人税法・地方税法・租税特別措置法・関税定率法・関税暫定措置法・消費税法）の一部改正で、類型が定型改正。"
           "指示文の定義では税率や対象を変えうるので実質改正。読み直しでは閣法-189-3・閣法-221-4")),
    "K3": ("時限法の改正で系統の類型が割れた",
           ("題名が時限法（定例の規則 RT8 と同じ語）の改正で、振り分けの各系統（v1 の A・B、v2 の系統1・系統2）の類型が定型改正とそれ以外に割れる。"
           "延長だけか中身も変えるかの取り違えが起きやすい。読み直しでは閣法-180-38・衆法-217-15・衆法-217-19")),
    "C1": ("経済に効くと記録しつつ制度だけの扱い",
           "経済の区分が「経済に効く」なのに、到達点が評価対象外か効果なし（定例）。読み直しで経済に効くなら分類の誤り"),
    "C2": ("制度と記録しつつ経済の扱い",
           "経済の区分が「制度」なのに、到達点が額・参考額・保留・測定できないなど（測る側）。読み直しで制度だけなら分類の誤り（閣法-213-45 と同じ形）"),
    "C3": ("経済に効くかを AI が決められないまま測る側に置いた",
           ("到達点が測る側で、経済の区分が判定不能。読み直しでは閣法-180-38 がこの形から経済に効くと決まった。"
            "経済の区分が空の法律（市場の経路に載り、区分を付けていない）はこの型に数えない（閣法-213-45・衆法-217-19 は空の側）")),
    "R1": ("照合で読み替えが起きる形",
           ("台帳の分類が評価対象外（振り分けで市場の対応表に当たらない）なのに、到達点が測る側。分類を「制度だけ」と読むと誤って食い違いになる"
           "（初回の照合が閣法-180-72・閣法-217-48・衆法-218-1 で起こした読み替え）")),
}


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def line_kinds(i: str, v1: dict, l1: dict, l2: dict) -> list[str]:
    t, a, b = v1.get(i, {}), l1.get(i, {}), l2.get(i, {})
    return [k for k in (t.get("A_種類"), t.get("B_種類"), a.get("種類"), b.get("系統2_種類")) if k in KINDS]


def find(outcomes: list[dict], ledger: dict[str, dict], v1: dict, l1: dict, l2: dict, fixed: dict | None = None) -> list[dict]:
    """fixed：一次資料で直した法律（{id: {項目: 行}}）。直した項目の型（類型→K、経済に効くか→C）には数えない。"""
    fixed = fixed or {}
    rows = []
    for o in outcomes:
        i, title, kind = o["id"], o["題名"], o["種類"]
        g = ledger.get(i)
        if g is None:  # 台帳に行が無い法律は数えない（台帳の作り直しが先）
            continue
        reach, econ = g.get("到達点", ""), g.get("経済に効くか", "")
        measured = reach not in NO_EFFECT_REACHES

        hits: list[tuple[str, str]] = []
        if not kind:
            hits.append(("K1", "類型が空"))
        if kind == "定型改正" and TAX_ANNUAL.search(title):
            hits.append(("K2", "税法の一部改正で類型が定型改正"))
        if any(w in title for w in TIME_LIMITED) and "改正" in title:
            ks = line_kinds(i, v1, l1, l2)
            if "定型改正" in ks and any(k != "定型改正" for k in ks):
                hits.append(("K3", f"系統の類型：{'・'.join(ks)}／サイト：{kind or '（空）'}"))
        if econ.startswith("経済に効く") and not measured:
            hits.append(("C1", f"経済の区分「{econ}」・到達点「{reach}」（経路「{o['経路']}」）"))
        if econ.startswith("制度") and measured:
            hits.append(("C2", f"経済の区分「{econ}」・到達点「{reach}」"))
        if measured and econ.startswith("判定不能"):
            hits.append(("C3", f"経済の区分「{econ}」・到達点「{reach}」"))
        if g.get("分類") == "評価対象外" and measured:
            hits.append(("R1", f"分類「評価対象外」・到達点「{reach}」・経済の区分「{econ or '（空）'}」"))
        skip = {"K"} if "類型" in fixed.get(i, {}) else set()
        skip |= {"C"} if "経済に効くか" in fixed.get(i, {}) else set()
        rows += [{"id": i, "題名": title, "型": c, "根拠": w} for c, w in hits if c[0] not in skip]
    return rows


def counts(rows: list[dict], total: int) -> dict:
    out = {"母数": total, "母数の定義": "成立した全法律（all-laws-v1/outcomes.csv の行）", "型": {}}
    for code, (name, definition) in TYPES.items():
        ids = sorted({r["id"] for r in rows if r["型"] == code})
        out["型"][code] = {"名前": name, "定義": definition, "本数": len(ids),
                           "表記": f"{total:,}本中{len(ids):,}本（{name}）"}
    return out


def build(root: Path = ROOT) -> tuple[list[dict], dict]:
    d = root / "data" / "derived"
    outcomes = read(d / "all-laws-v1" / "outcomes.csv")
    ledger = {r["id"]: r for r in read(d / "evaluation-ledger-v1" / "ledger.csv")}
    v1 = {r["id"]: r for r in read(d / "bill-triage-v1" / "triage.csv")}
    l1 = {r["id"]: r for r in read(d / "bill-triage-v2" / "labels-line1.csv")}
    l2 = {r["id"]: r for r in read(d / "bill-triage-v2" / "labels-line2.csv")}
    rows = find(outcomes, ledger, v1, l1, l2, corrections.load(d / "primary-source-corrections-v1" / "corrections.csv"))
    return rows, counts(rows, len(outcomes))


def render(rows: list[dict]) -> str:
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, HEADER, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str]) -> int:
    rows, summary = build()
    text_csv = render(rows)
    text_json = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if "--check" in argv:
        same = ((OUT_DIR / "candidates.csv").read_text(encoding="utf-8") == text_csv
                and (OUT_DIR / "counts.json").read_text(encoding="utf-8") == text_json)
        print("一致" if same else "出力が古い：python3 scripts/check_error_types.py で作り直す")
        return 0 if same else 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "candidates.csv").write_text(text_csv, encoding="utf-8")
    (OUT_DIR / "counts.json").write_text(text_json, encoding="utf-8")
    for t in summary["型"].values():
        print(t["表記"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
