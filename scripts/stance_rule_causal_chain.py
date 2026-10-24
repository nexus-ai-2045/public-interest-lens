#!/usr/bin/env python3
"""因果の鎖の賛否の系統A（決まった言い回しで判定）と、系統Bの読み手に渡す抜粋を作る。

系統A（機械）:
  - 「反対の立場」「反対の討論」「反対いたします」「反対します」→ 反対
  - 「賛成の立場」「賛成の討論」「賛成いたします」「賛成します」「御賛同」「提案の理由」→ 支持
  - 両方あれば 中立（どちらとも言えない）、どちらも無ければ 中立（質疑・答弁のみ）
  - 政府参考人・説明員などは 無関係（議員でも参考人でもない）
  ただし委員長・議長の議事進行（「賛成の諸君の起立を求めます」など）は数えない。
系統B（読み手）用に、議員ごとの抜粋 excerpts/<法案ID>/NNN_氏名.txt を作る。

使い方: python3 scripts/stance_rule_causal_chain.py [--dir /mnt/project-files/private-m2/causal-chain]
"""
import argparse, json, re
from pathlib import Path

NEG = ("反対の立場", "反対の討論", "反対いたします", "反対します", "反対であります", "反対でございます")
POS = ("賛成の立場", "賛成の討論", "賛成いたします", "賛成します", "賛成であります", "御賛同", "提案の理由")
CHAIR = re.compile(r"^○(委員長|議長|副議長|理事)|^○\S*(委員長|議長)（")
OFFICIAL = ("政府参考人", "政府特別補佐人", "説明員", "政府委員", "会計検査院", "最高裁判所")
BLOCK = re.compile(r"^■ ([^\n]+)\nspeechURL: (\S+)\n\n(.*?)(?=\n■ |\Z)", re.S | re.M)


def blocks(txt):
    return [(h, u, b.strip()) for h, u, b in BLOCK.findall(txt)]


def judge(kubun, bl):
    if any(k in kubun for k in OFFICIAL):
        return "無関係", "", bl[0][1] if bl else ""
    hits = []
    for h, u, b in bl:
        if CHAIR.match(b):
            continue
        for k in NEG:
            if k in b:
                i = b.find(k); hits.append(("反対", b[max(0, i - 30):i + 20], u))
        for k in POS:
            if k in b:
                i = b.find(k); hits.append(("支持", b[max(0, i - 30):i + 20], u))
    kinds = {h[0] for h in hits}
    if len(kinds) == 1:
        k, q, u = hits[0]
        return k, q.replace("\n", "")[:50], u
    return "中立", "", bl[0][1] if bl else ""


def excerpt(bl, limit=2500):
    parts, n = [], 0
    for h, u, b in bl:
        s = b if len(b) <= 900 else b[:500] + " …（中略）… " + b[-400:]
        parts.append(f"■ {h}\nspeechURL: {u}\n{s}\n")
        n += len(s)
        if n > limit:
            parts.append("（以下省略）"); break
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/mnt/project-files/private-m2/causal-chain")
    a = ap.parse_args()
    d = Path(a.dir)
    (d / "stance").mkdir(exist_ok=True)
    for meta_p in sorted(d.glob("*.json")):
        if meta_p.name.startswith("stance"):
            continue
        meta = json.load(open(meta_p, encoding="utf-8"))
        bid = meta["id"]
        ex = d / "excerpts" / bid; ex.mkdir(parents=True, exist_ok=True)
        out = []
        for f in sorted((d / "speeches" / bid).glob("*.txt")):
            txt = f.read_text(encoding="utf-8")
            head = dict(l.split(": ", 1) for l in txt.split("\n\n", 1)[0].splitlines() if ": " in l)
            bl = blocks(txt)
            k, q, u = judge(head.get("区分", "議員"), bl)
            out.append({"氏名": head["氏名"], "立場": k, "根拠の引用（50字以内）": q, "証拠URL": u})
            (ex / f.name).write_text(txt.split("\n\n", 1)[0] + "\n\n" + excerpt(bl), encoding="utf-8")
        (d / "stance" / f"{bid}.lineA.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(bid, {k: sum(1 for o in out if o["立場"] == k) for k in ("支持", "反対", "中立", "無関係")})


if __name__ == "__main__":
    main()
