"""抜き取り検証で「不合格のまま」残った法律を、一次資料の読み直し（再判定）で決着させ、sample-resolutions.csv を作る。AI は呼ばない。

入力
  data/derived/evaluation-ledger-v1/ledger.csv                      サイトの今の値
  data/derived/evaluation-ledger-v1/sample-verdicts.csv             初回の判定（書き換えない）
  data/derived/evaluation-ledger-v1/reverification-v1/lineA.json    読み直しの系統A（議案本文を先に読む）
  data/derived/evaluation-ledger-v1/reverification-v1/lineB.json    読み直しの系統B（会議録を先に読む）
  data/derived/evaluation-ledger-v1/reverification-v1/rulings.json  2系統が割れた項目の裁定（{id: {項目: {値, 理由}}}）
出力
  data/derived/evaluation-ledger-v1/sample-resolutions.csv          1本1行の決着（台帳とレポートが読む）

決着の規則（項目は 類型 と 分類）
  読み直しの値   2系統が一致した値。割れたら裁定の値。どちらも無ければ「決められない」。
  類型           サイトの類型と読み直しの値が同じなら食い違いなし。違えばサイトの誤り。
  分類           サイトの主張は「到達点」で読む。到達点が評価対象外か効果なし（定例）なら、サイトは「制度だけ」と扱っている。
                 それ以外（額・参考額・国の収支の別欄・保留・測定できない）なら「経済に効く」と扱っている。
                 振り分けの「分類＝評価対象外」は市場の産業の対応表に当たらないという区分で、制度だけという主張ではない
                 （初回の照合はこれを「制度のみ」と読み替えていた。2026-11-19 の裁定 rulings.json「照合の読み方」）。
                 読み直しが「経済に効く」のとき：サイトが制度だけと扱っていればサイトの誤り。
                 読み直しが「制度のみ」のとき：サイトが経済に効くと扱っているか、経済の区分に「経済に効く」と記録していればサイトの誤り。
                 サイトの類型が空なら、それもサイトの誤りとして数える。
  決着           サイトの誤りが1つも残らない → 合格に訂正。
                 残る、または決められない → 参考に下げた（サイトの値は直っていない。順位・議員配分には使わない。
                 サイトの値と読み直しの値を並べて出し続ける）。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import primary_source_corrections as corrections
from scripts.build_evaluation_ledger import (
    RESOLVED_DEMOTED,
    RESOLVED_PASS,
    amount_demoted,
    site_key,
)
from scripts.evaluation_rules import VERDICT_FAIL, is_demoted

L = ROOT / "data" / "derived" / "evaluation-ledger-v1"
RV = L / "reverification-v1"
OUT = L / "sample-resolutions.csv"
HEADER = ["id", "決着", "原因の区分", "理由", "参考値", "根拠URL", "判定時のサイトの値", "抜き取り時の到達点", "記録"]
SAMPLED_AT = RV / "sampling-time-ledger.csv"  # 抜き取り時（#133、275620d）の台帳から対象の行だけを写したもの
RESOLUTIONS = (RESOLVED_PASS, RESOLVED_DEMOTED)
UNDECIDED = "決められない"
NO_ANSWER = ("判定不能", "", None)
CAUSE_READING = "照合の読み替え（サイトの誤りではない）"
CAUSE_FIRST = "初回の独立判定の誤り"
CAUSE_KIND = "サイトの類型の誤り"
CAUSE_CLASS = "サイトの分類の誤り（制度だけの法律を評価の対象に置いた）"
CAUSE_UNDECIDED = "一次資料が足りず決められない"
CAUSE_ECON_OUT = "サイトの分類の誤り（経済に効く法律を制度だけと扱った）"
CAUSE_FIXED = "サイトの値を一次資料で直した（primary-source-corrections-v1）"
INSTITUTIONAL_REACHES = ("評価対象外", "効果なし（定例）")
CAUSE_ECON = "サイトの分類の誤り（経済に効くと記録した法律が制度だけだった）"
RECORD = "data/derived/evaluation-ledger-v1/reverification-v1/"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def agreed(a: dict, b: dict, key: str, ruling: dict | None) -> str:
    """読み直しの値。2系統が一致すればその値、割れたら裁定、無ければ「決められない」。"""
    if ruling and ruling.get(key, {}).get("値") not in NO_ANSWER:
        return ruling[key]["値"]
    va, vb = a.get(key), b.get(key)
    if va == vb and va not in NO_ANSWER:
        return va
    return UNDECIDED


def site_is_institutional(site: dict) -> bool:
    """サイトが「制度だけ（経済の量は動かない）」と扱っているか。到達点で読む（振り分けの分類では読まない）。"""
    return site["到達点"] in INSTITUTIONAL_REACHES


def resolve(site: dict, a: dict, b: dict, ruling: dict | None, first_memo: str, sampled_reach: str = "", fixed: dict | None = None) -> dict:
    """fixed：この法律で、サイトの値を一次資料で直した項目と行（primary-source-corrections-v1 の {項目: 行}）。"""
    fixed = fixed or {}
    kind, econ = agreed(a, b, "類型", ruling), agreed(a, b, "経済に効くか", ruling)
    causes, errors, notes = [], [], []
    # 類型
    if not site["類型"]:
        causes.append(CAUSE_KIND)
        errors.append(f"類型：サイトは空、読み直し「{kind}」")
    else:
        if kind == UNDECIDED:
            causes.append(CAUSE_UNDECIDED)
            errors.append("類型は読み直しでも決められない")
        elif kind != site["類型"]:
            causes.append(CAUSE_KIND)
            errors.append(f"類型：サイト「{site['類型']}」、読み直し「{kind}」")
        elif "類型" in fixed:
            causes.append(CAUSE_FIXED)
            notes.append(f"類型：サイトの値を一次資料で「{kind}」に直した")
        elif "類型：" in first_memo:
            causes.append(CAUSE_FIRST)
            notes.append(f"類型は読み直しでサイトと同じ「{kind}」")
    # 分類（サイトの扱いは到達点で読む）
    inst = site_is_institutional(site)
    says_econ = site["経済に効くか"].startswith("経済に効く")
    first_flagged = "分類：" in first_memo or "制度のみ" in first_memo
    fixed_econ = fixed.get("経済に効くか")
    if fixed_econ and not fixed_econ["直す前の値"].startswith(fixed_econ["直した値"]):
        causes.append(CAUSE_FIXED)
        notes.append(f"経済に効くか：サイトの値「{fixed_econ['直す前の値'] or '（空）'}」を一次資料で「{fixed_econ['直した値']}」に直した（到達点は今「{site['到達点']}」）")
    if econ == UNDECIDED:
        causes.append(CAUSE_UNDECIDED)
        errors.append("経済に効くかは読み直しでも決められない")
    elif econ == "経済に効く":
        if site["経済に効くか"].startswith("制度"):
            causes.append(CAUSE_ECON_OUT)
            errors.append(f"分類：サイトは「{site['経済に効くか']}」と記録、読み直しは「経済に効く」")
        elif inst:
            causes.append(CAUSE_ECON_OUT)
            errors.append(f"分類：サイトは到達点「{site['到達点']}」（制度だけの扱い）、読み直しは「経済に効く」")
        elif site["分類"] == "評価対象外":
            causes.append(CAUSE_READING)
            notes.append(f"分類：サイトは到達点「{site['到達点']}」で経済に効く扱い（経済の区分「{site['経済に効くか'] or '（空）'}」）。"
                         "振り分けの「評価対象外」は市場の対応表に無いという意味で、制度だけという主張ではない")
        elif first_flagged:
            causes.append(CAUSE_FIRST)
            notes.append("分類は読み直しでサイトと同じ「経済に効く」")
    else:  # 制度のみ
        if says_econ:
            causes.append(CAUSE_ECON)
            errors.append(f"分類：サイトは「{site['経済に効くか']}」と記録、読み直しは「制度のみ」")
        elif not inst:
            causes.append(CAUSE_CLASS)
            errors.append(f"分類：サイトは「{site['分類']}」（到達点「{site['到達点']}」）、読み直しは「制度のみ」")
        elif first_flagged and not fixed_econ:
            causes.append(CAUSE_FIRST)
            notes.append("分類は読み直しでサイトと同じ「制度のみ」")
    decided = RESOLVED_DEMOTED if errors else RESOLVED_PASS
    reference = [f"類型：サイト「{site['類型'] or '（空）'}」／読み直し「{kind}」",
                 f"分類：サイト「{site['分類']}」・到達点「{site['到達点']}」・経済の区分「{site['経済に効くか'] or '（空）'}」／読み直し「{econ}」"]
    if site["国の収支（億円）"]:
        reference.append(f"国の収支 {site['国の収支（億円）']} 億円（別欄。順位・配分に使わない）")
    if not site["額（円）"]:
        reference.append("付加価値の額は無い")
    if sampled_reach and sampled_reach != site["到達点"]:
        notes.append(f"抜き取り時の到達点は「{sampled_reach}」で、今は「{site['到達点']}」。決着は今の台帳に対するもの")
    why = "；".join(errors + notes)
    if decided == RESOLVED_DEMOTED:
        why += "。サイトの値はまだ直っていないので参考に下げる"
    urls = []
    for line in (a, b):
        for u in line.get("出典URL", []):
            if u.startswith("http") and u not in urls:
                urls.append(u)
    return {"id": site["id"], "決着": decided, "原因の区分": "／".join(dict.fromkeys(causes)) or CAUSE_FIRST, "理由": why,
            "参考値": "；".join(reference), "根拠URL": " ".join(urls),
            "判定時のサイトの値": site_key(site), "抜き取り時の到達点": sampled_reach, "記録": RECORD}


def targets(ledger: dict[str, dict], verdicts: list[dict], reread: set[str] = frozenset()) -> list[str]:
    """初回が不合格で、額を参考に下げる自動の規則（is_demoted）に当たらない法律と、一次資料で読み直した法律（reread）。

    読み直した法律は、サイトの値を直した後に到達点が評価対象外になって自動の規則に当たっても、読み直しで決着させる。
    額のある到達点（参考額・個別の額）の自動の降格は、読み直しても決着で戻さない（台帳の verify_state と同じ）。
    """
    return sorted(v["id"] for v in verdicts if v["判定"] == VERDICT_FAIL
                  and not amount_demoted(v["判定"], ledger[v["id"]]["到達点"], ledger[v["id"]]["確かさ"])
                  and (v["id"] in reread or not is_demoted(v["判定"], ledger[v["id"]]["到達点"], ledger[v["id"]]["確かさ"])))


def main() -> int:
    ledger = {r["id"]: r for r in read_csv(L / "ledger.csv")}
    verdicts = read_csv(L / "sample-verdicts.csv")
    memo = {v["id"]: v["食い違い"] for v in verdicts}
    line_a = {x["id"]: x for x in json.loads((RV / "lineA.json").read_text(encoding="utf-8"))}
    line_b = {x["id"]: x for x in json.loads((RV / "lineB.json").read_text(encoding="utf-8"))}
    rulings = json.loads((RV / "rulings.json").read_text(encoding="utf-8")) if (RV / "rulings.json").exists() else {}
    ids = targets(ledger, verdicts, set(line_a) & set(line_b))
    corr = corrections.load()
    missing = [i for i in ids if i not in line_a or i not in line_b]
    if missing:
        print(f"読み直しの記録が無い：{'、'.join(missing)}", file=sys.stderr)
        return 1
    sampled = {r["id"]: r["到達点"] for r in read_csv(SAMPLED_AT)} if SAMPLED_AT.exists() else {}
    rows = [resolve(ledger[i], line_a[i], line_b[i], rulings.get(i), memo[i], sampled.get(i, ""), corr.get(i)) for i in ids]
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, HEADER)
        w.writeheader()
        w.writerows(rows)
    tally = {k: sum(r["決着"] == k for r in rows) for k in RESOLUTIONS}
    print(f"決着 {len(rows)} 本：" + "、".join(f"{k} {v}" for k, v in tally.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
