#!/usr/bin/env python3
"""根拠値の台帳（data/evidence/ledger.json）の検査。

- 必須項目・型・ID の重複
- DOI の形式
- verified には「収集・照合1・照合2」の3者の記録があり、数値が丸めの範囲で一致していること
- mapping.json の参照 ID が台帳に実在すること
赤なら終了コード1。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "evidence" / "ledger.json"
MAPPING = ROOT / "data" / "evidence" / "mapping.json"

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
STUDY_TYPES = {"meta-analysis", "systematic-review", "official-estimate", "review", "single-study"}
STATUSES = {"verified", "held"}
CONFIDENCE = {"高", "中", "低"}
ROLES = ("collector", "check1", "check2")
REQUIRED = ["id", "mechanism", "quantity", "estimate", "source", "scope", "locator", "japan_application", "used_for", "confidence", "verification"]


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def agree(a, b, rel=0.02):
    """丸めの範囲で一致（相対2%。符号が違う値、0 と 0 以外は一致としない）。"""
    if a == b:
        return True
    if a == 0 or b == 0 or (a < 0) != (b < 0):
        return False
    return abs(a - b) <= max(abs(a), abs(b)) * rel


def agree_opt(a, b):
    """区間の端：両方 None、または両方数値で一致。"""
    if a is None or b is None:
        return a is None and b is None
    return _num(a) and _num(b) and agree(a, b)


def _filled(d, keys):
    return isinstance(d, dict) and all(isinstance(d.get(k), str) and d.get(k).strip() for k in keys)


def check_entry(e):
    errs = []
    for k in REQUIRED:
        if k not in e:
            errs.append(f"{e.get('id', '?')}: 必須項目 {k} がない")
    if errs:
        return errs
    i = e["id"]
    est = e["estimate"]
    if not _filled(e["source"], ["authors", "title", "venue"]) or not isinstance(e["source"].get("year"), int):
        errs.append(f"{i}: source の著者・年・題名・誌名が欠けている")
    if not _filled(e["scope"], ["countries", "period", "population_or_sector"]):
        errs.append(f"{i}: scope の国・期間・対象が欠けている")
    if not isinstance(e["locator"], str) or not e["locator"].strip():
        errs.append(f"{i}: locator が空")
    if not _filled(e["japan_application"], ["method", "caveat"]):
        errs.append(f"{i}: japan_application の当てはめ方・条件が欠けている")
    if not isinstance(e["used_for"], list) or not e["used_for"]:
        errs.append(f"{i}: used_for が空")
    if not isinstance(est.get("unit"), str) or not est["unit"].strip():
        errs.append(f"{i}: estimate.unit が空")
    if not _num(est.get("central")):
        errs.append(f"{i}: estimate.central が数値でない")
    for k in ("low", "high"):
        if est.get(k) is not None and not _num(est[k]):
            errs.append(f"{i}: estimate.{k} が数値でない")
    if _num(est.get("low")) and _num(est.get("central")) and est["low"] > est["central"] + 1e-9:
        errs.append(f"{i}: low が central を超える")
    if _num(est.get("high")) and _num(est.get("central")) and est["high"] < est["central"] - 1e-9:
        errs.append(f"{i}: high が central を下回る")
    s = e["source"]
    if s.get("study_type") not in STUDY_TYPES:
        errs.append(f"{i}: study_type が不正")
    if s.get("doi") is not None and not DOI_RE.match(s["doi"]):
        errs.append(f"{i}: DOI の形式が不正")
    if not s.get("doi") and not s.get("url"):
        errs.append(f"{i}: DOI も URL もない")
    if e["confidence"] not in CONFIDENCE:
        errs.append(f"{i}: confidence が不正")
    v = e["verification"]
    if v.get("status") not in STATUSES:
        errs.append(f"{i}: verification.status は verified か held")
    if v.get("status") == "verified":
        checks = {c.get("role"): c for c in v.get("checks", [])}
        if not all(r in checks for r in ROLES):
            errs.append(f"{i}: verified に3者（収集・照合1・照合2）の記録がない")
        else:
            vals = [checks[r].get("central") for r in ROLES]
            if not all(_num(x) for x in vals):
                errs.append(f"{i}: 3者の central が数値でない")
            elif not (agree(vals[0], vals[1]) and agree(vals[1], vals[2]) and agree(vals[0], vals[2])):
                errs.append(f"{i}: 3者の値が一致しないのに verified")
            else:
                if _num(est.get("central")) and not agree(est["central"], vals[1]):
                    errs.append(f"{i}: 台帳の central が照合の値と一致しない")
                for r in ("check1", "check2"):
                    c = checks[r]
                    if c.get("unit") != est.get("unit"):
                        errs.append(f"{i}: {r} の単位が台帳と違う")
                    if not agree_opt(est.get("low"), c.get("low")) or not agree_opt(est.get("high"), c.get("high")):
                        errs.append(f"{i}: {r} の区間が台帳と一致しない")
                    if c.get("scope_match") is not True:
                        errs.append(f"{i}: {r} が対象（国・期間・対象）の一致を確認していない")
        if s.get("doi") and v.get("crossref_title_match") is not True:
            errs.append(f"{i}: DOI があるのに Crossref の題名一致が確認されていない")
    elif not v.get("held_reason"):
        errs.append(f"{i}: held に理由（held_reason）がない")
    return errs


def check(ledger, mapping=None):
    errs = []
    entries = ledger.get("entries", [])
    ids = [e.get("id") for e in entries]
    for d in {x for x in ids if ids.count(x) > 1}:
        errs.append(f"ID が重複: {d}")
    for e in entries:
        errs += check_entry(e)
    if mapping is not None:
        have = set(ids)
        for m in mapping.get("mechanisms", []):
            for q in m.get("ledger_ids", []):
                if q not in have:
                    errs.append(f"mapping の {m.get('id')} が台帳にない ID を参照: {q}")
    return errs


def main():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8")) if MAPPING.exists() else None
    errs = check(ledger, mapping)
    n = len(ledger.get("entries", []))
    ver = sum(1 for e in ledger.get("entries", []) if e.get("verification", {}).get("status") == "verified")
    print(f"台帳 {n} 件（verified {ver}・held {n - ver}）")
    for e in errs:
        print("NG:", e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
