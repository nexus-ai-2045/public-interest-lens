#!/usr/bin/env python3
"""因果の鎖の賛否（2系統）を突き合わせ、一致したものだけ採用する。

入力: <dir>/stance/<法案ID>.lineA.json と .lineB.json
      （各要素: 氏名, 立場=支持/反対/中立/無関係, 根拠の引用（50字以内）, 証拠URL）
出力: <dir>/stance-merged.csv（採用・保留とその理由）、<dir>/stance-summary.json
実名が入るので private-m2 側だけに置く。

使い方: python3 scripts/merge_causal_chain_stance.py [--dir /mnt/project-files/private-m2/causal-chain]
"""
import argparse, csv, json
from collections import Counter
from pathlib import Path


def load(p):
    """p が無ければ、分けて読んだ p.part1.json, p.part2.json … をまとめる。"""
    files = [p] if p.exists() else sorted(p.parent.glob(p.name.replace(".json", ".part*.json")))
    out = {}
    for f in files:
        out.update({r["氏名"]: r for r in json.load(open(f, encoding="utf-8"))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/mnt/project-files/private-m2/causal-chain")
    a = ap.parse_args()
    d = Path(a.dir)
    rows, summary = [], {}
    for meta_p in sorted(d.glob("*.json")):
        if meta_p.name.startswith("stance"):
            continue
        meta = json.load(open(meta_p, encoding="utf-8"))
        bid = meta["id"]
        A, B = load(d / "stance" / f"{bid}.lineA.json"), load(d / "stance" / f"{bid}.lineB.json")
        if not A or not B:
            summary[bid] = "賛否の判定がまだ無い"
            continue
        c = Counter()
        for s in meta["speakers"]:
            n = s["氏名"]
            a_, b_ = A.get(n, {}), B.get(n, {})
            sa, sb = a_.get("立場", "なし"), b_.get("立場", "なし")
            if sa == sb and sa != "なし":
                v, why = "採用", ""
            else:
                v, why = "保留", f"系統A={sa}・系統B={sb}"
            c[(v, sa if v == "採用" else "不一致")] += 1
            rows.append({"法案ID": bid, "題名": meta["title"], "氏名": n, "院": s["院"], "会派": s["会派"],
                         "区分": s.get("区分", ""), "判定": v, "立場": sa if v == "採用" else "", "理由": why,
                         "根拠の引用_A": a_.get("根拠の引用（50字以内）", ""), "証拠URL_A": a_.get("証拠URL", ""),
                         "根拠の引用_B": b_.get("根拠の引用（50字以内）", ""), "証拠URL_B": b_.get("証拠URL", ""),
                         "発言数": s["発言数"]})
        summary[bid] = {f"{k[0]}:{k[1]}": v for k, v in sorted(c.items())}
    if rows:
        with open(d / "stance-merged.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    (d / "stance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
