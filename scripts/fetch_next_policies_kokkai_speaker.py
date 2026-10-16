#!/usr/bin/env python3
"""各法案の趣旨説明(提案理由)をした大臣・議員の氏名と役職を国会会議録検索システムAPIから取る。"""
from pathlib import Path
import json, os, urllib.parse
src = open(os.path.join(str(Path(__file__).resolve().parent), "fetch_next_policies_kokkai.py")).read()
exec(src.split("out = []")[0])
res = []
for key, sess, bill in Q:
    short = bill.replace("案", "")
    base = short.replace("の一部を改正する法律", "")
    cands = []
    for kw in ("趣旨", "理由"):
        p = {"any": short + " " + kw, "sessionFrom": sess, "sessionTo": sess, "maximumRecords": 100, "recordPacking": "json"}
        u = "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(p)
        st, b = get(u)
        save(f"kokkai_speaker_{key}_s{sess}_{kw}.json", u, st, b)
        if st != 200:
            print(key, "fail", st); continue
        for r in json.loads(b).get("speechRecord", []):
            sp = r["speech"]; head = sp[:300]
            pos = r.get("speakerPosition") or ""
            if base not in head and short not in head: continue
            if not any(k in head for k in ("趣旨", "提案", "理由")): continue
            if any(k in head for k in ("附帯決議", "修正案", "質問", "報告", "討論", "賛成", "反対")): continue
            if "委員長" in pos or "議長" in pos: continue
            m = [k for k in ("ただいま議題となりました", "ただいま議題") if k in sp]
            i = sp.find(m[0]) if m else 0
            cands.append((r["date"], r["nameOfHouse"], r["nameOfMeeting"], r["speaker"], pos, r["speechURL"], sp[i:i + 60], u))
    cands = sorted(set(cands))
    print(key, "n", len(cands))
    for c in cands[:3]:
        print("   ", c[:7])
    if cands:
        res.append([key, sess, bill, *cands[0]])
json.dump(res, open(os.path.join(ROOT, ".local/next-policies-originals/kokkai_speakers.json"), "w"), ensure_ascii=False)
