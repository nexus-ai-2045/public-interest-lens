#!/usr/bin/env python3
"""国会会議録検索システムAPIで、各法案を議題とした会議を探す(原本JSONを保存)。"""
from pathlib import Path
import json, os, sys, urllib.parse
src = open(os.path.join(str(Path(__file__).resolve().parent), "fetch_next_policies_laws.py")).read()
exec(src.split("LAWS = [")[0])
exec("last = [0.0]\n" + src.split("last = [0.0]")[1].split("for key, num in LAWS:")[0])
Q = [
    ("携帯電話料金", 198, "電気通信事業法の一部を改正する法律案"),
    ("民泊", 193, "住宅宿泊事業法案"),
    ("電力小売全面自由化", 186, "電気事業法等の一部を改正する法律案"),
    ("科学技術基本法", 134, "科学技術基本法案"),
    ("IT基本法", 150, "高度情報通信ネットワーク社会形成基本法案"),
    ("知的財産基本法", 155, "知的財産基本法案"),
    ("研究開発税制", 156, "所得税法等の一部を改正する法律案"),
    ("国立大学法人法", 156, "国立大学法人法案"),
    ("資金決済法", 171, "資金決済に関する法律案"),
    ("FIT", 177, "電気事業者による再生可能エネルギー電気の調達に関する特別措置法案"),
    ("マイナンバー法", 183, "行政手続における特定の個人を識別するための番号の利用等に関する法律案"),
    ("会社法", 162, "会社法案"),
    ("薬事法改正", 185, "薬事法及び薬剤師法の一部を改正する法律案"),
]
out = []
for key, sess, bill in Q:
    p = {"any": bill + " 議題", "sessionFrom": sess, "sessionTo": sess, "maximumRecords": 100,
         "recordPacking": "json"}
    u = "https://kokkai.ndl.go.jp/api/speech?" + urllib.parse.urlencode(p)
    s, b = get(u)
    save(f"kokkai_{key}_s{sess}.json", u, s, b)
    if s != 200:
        print(key, "fail", s); continue
    d = json.loads(b)
    seen = {}
    for r in d.get("speechRecord", []):
        sp = r["speech"]
        if bill not in sp and bill.replace("案", "") not in sp:
            continue
        i = sp.find("議題")
        if i < 0:
            continue
        k = (r["date"], r["nameOfHouse"], r["nameOfMeeting"], r["issue"])
        if k in seen: continue
        a = max(0, sp.find(bill.replace("案", "")))
        quote = sp[a:i + 3].replace("\n", "").replace("　", "")
        seen[k] = (r["meetingURL"], r["speakerPosition"] if "speakerPosition" in r else "", quote[-60:] if len(quote) > 60 else quote, u)
    print(key, sess, "total", d.get("numberOfRecords"), "meetings", len(seen))
    for k, v in sorted(seen.items()):
        out.append([key, sess, *k, *v])
json.dump(out, open(os.path.join(ROOT, ".local/next-policies-originals/kokkai_rows.json"), "w"), ensure_ascii=False)
for o in out: print(o[:6], o[7][:60])
