#!/usr/bin/env python3
"""e-Gov法令本文JSONから附則(施行期日)の最初の条文テキストを抜き出して表示・保存する。"""
from pathlib import Path
import glob, json, os, re
ROOT = os.path.join(str(Path(__file__).resolve().parent), "..")
RAW = os.path.join(ROOT, ".local/next-policies-originals/raw")


def flat(n):
    if isinstance(n, str):
        return n
    if isinstance(n, list):
        return "".join(flat(x) for x in n)
    if isinstance(n, dict):
        return flat(n.get("children", []))
    return ""


def find(n, tag, out):
    if isinstance(n, dict):
        if n.get("tag") == tag:
            out.append(n)
        for c in n.get("children", []):
            find(c, tag, out)
    elif isinstance(n, list):
        for c in n:
            find(c, tag, out)


res = {}
for f in sorted(glob.glob(RAW + "/egov_*_text.json")):
    d = json.load(open(f, encoding="utf-8"))
    key = os.path.basename(f).split("_")[1]
    sp = []
    find(d.get("law_full_text"), "SupplProvision", sp)
    # 本則の附則(改正附則でない最初のもの)
    first = [s for s in sp if not s.get("attr", {}).get("AmendLawNum")]
    s = first[0] if first else (sp[0] if sp else None)
    arts = []
    if s:
        find(s, "Article", arts)
        paras = []
        find(s, "Paragraph", paras)
        txt = [flat(p) for p in (arts[0:1] or paras[0:1])]
    else:
        txt = []
    res[key] = txt[0] if txt else ""
    print(key, "|", os.path.basename(f))
    print("   ", res[key][:200].replace("\n", " "))
json.dump(res, open(os.path.join(ROOT, ".local/next-policies-originals/fusoku.json"), "w"), ensure_ascii=False, indent=1)
