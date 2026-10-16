#!/usr/bin/env python3
"""e-Gov 法令API v2 から13政策の法令の公布日・施行日の原本(JSON)を取得し manifest に記録する。"""
import csv, hashlib, json, os, sys, time, urllib.parse, urllib.request, datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RAW = os.path.join(ROOT, ".local/next-policies-originals/raw")
MAN = os.path.join(ROOT, ".local/next-policies-originals/manifest.csv")
os.makedirs(RAW, exist_ok=True)
UA = "Mozilla/5.0 (compatible; public-interest-lens)"
LAWS = [
    ("携帯電話料金", "令和元年法律第五号"),
    ("民泊", "平成二十九年法律第六十五号"),
    ("電力小売全面自由化", "平成二十六年法律第七十二号"),
    ("科学技術基本法", "平成七年法律第百三十号"),
    ("IT基本法", "平成十二年法律第百四十四号"),
    ("知的財産基本法", "平成十四年法律第百二十二号"),
    ("研究開発税制", "平成十五年法律第八号"),
    ("国立大学法人法", "平成十五年法律第百十二号"),
    ("資金決済法", "平成二十一年法律第五十九号"),
    ("FIT", "平成二十三年法律第百八号"),
    ("マイナンバー法", "平成二十五年法律第二十七号"),
    ("会社法", "平成十七年法律第八十六号"),
    ("薬事法改正", "平成二十五年法律第百三号"),
]
last = [0.0]


def get(url):
    w = 1.1 - (time.time() - last[0])
    if w > 0:
        time.sleep(w)
    last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read()
    except Exception as e:
        code = getattr(e, "code", "ERR")
        return code, str(e).encode()


def save(name, url, status, body):
    path = os.path.join(RAW, name)
    if status == 200:
        open(path, "wb").write(body)
    new = not os.path.exists(MAN)
    with open(MAN, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["file", "url", "sha256", "http", "fetched_at"])
        w.writerow([name if status == 200 else "", url, hashlib.sha256(body).hexdigest(), status,
                    datetime.datetime.now().astimezone().isoformat(timespec="seconds")])


for key, num in LAWS:
    u = "https://laws.e-gov.go.jp/api/2/laws?response_format=json&law_num=" + urllib.parse.quote(num)
    s, b = get(u)
    save(f"egov_{key}_search.json", u, s, b)
    if s != 200:
        print(key, "search fail", s); continue
    d = json.loads(b)
    if not d["laws"]:
        print(key, num, "NOT FOUND in e-Gov"); continue
    lid = d["laws"][0]["law_info"]["law_id"]
    u = f"https://laws.e-gov.go.jp/api/2/law_revisions/{lid}?response_format=json"
    s, b = get(u)
    save(f"egov_{key}_{lid}_revisions.json", u, s, b)
    rv = json.loads(b)["revisions"]
    first = rv[-1]
    print(key, num, lid, d["laws"][0]["revision_info"]["law_title"], "promul", d["laws"][0]["law_info"]["promulgation_date"],
          "first-rev", first["law_revision_id"], first.get("amendment_enforcement_date"), "nrev", len(rv))
    u = f"https://laws.e-gov.go.jp/api/2/law_data/{first['law_revision_id']}?response_format=json"
    s, b = get(u)
    save(f"egov_{key}_{first['law_revision_id']}_text.json", u, s, b)
    print("   text", s, len(b))
