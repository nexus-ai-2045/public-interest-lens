#!/usr/bin/env python3
"""改正法(単独の法令データを持たないもの)を、改正された法律の改正履歴(e-Gov API v2)から探す。"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_next_policies_laws.py")).read()
head = src.split("for key, num in LAWS:")[0]
exec(head)
TARGET = [
    ("携帯電話料金", "359AC0000000086", "令和元年法律第五号"),
    ("電力小売全面自由化", "339AC0000000170", "平成二十六年法律第七十二号"),
    ("研究開発税制_所得税法", "340AC0000000033", "平成十五年法律第八号"),
    ("研究開発税制_租税特別措置法", "332AC0000000026", "平成十五年法律第八号"),
    ("研究開発税制_法人税法", "340AC0000000034", "平成十五年法律第八号"),
    ("薬事法改正", "335AC0000000145", "平成二十五年法律第百三号"),
]
for key, lid, num in TARGET:
    u = f"https://laws.e-gov.go.jp/api/2/law_revisions/{lid}?response_format=json"
    s, b = get(u)
    save(f"egov_{key}_{lid}_revisions.json", u, s, b)
    if s != 200:
        print(key, lid, "fail", s); continue
    d = json.loads(b)
    hits = [r for r in d["revisions"] if r.get("amendment_law_num") == num]
    print(key, lid, d["law_info"].get("law_num"), "nrev", len(d["revisions"]), "oldest", d["revisions"][-1]["law_revision_id"])
    for r in hits:
        print("   HIT", r["law_revision_id"], r["amendment_law_title"], "promul", r["amendment_promulgate_date"], "enf", r["amendment_enforcement_date"])
