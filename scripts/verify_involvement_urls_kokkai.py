#!/usr/bin/env python3
"""議員の関与の表（allocation/involvements.csv）の証拠URLを、会議録 API の原本で確かめる。

証拠URL（https://kokkai.ndl.go.jp/txt/<issueID>/<発言番号>）の会議を API で丸ごと取り、
その発言番号の発言者が、表の氏名（または原表記）と同じかを見る。
  一致：発言者の表記が氏名か原表記と同じ（空白を除いて比べる）
  不一致：別の人の発言だった（理由に実際の発言者を書く）
  対象外：会議録の URL ではない
実名が入るので結果は private-m2 側に置く。

使い方: python3 scripts/verify_involvement_urls_kokkai.py [--csv .../involvements.csv] [--out .../involvements-url-check.csv]
"""
import argparse, csv, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

API = "https://kokkai.ndl.go.jp/api/speech"
URL_RE = re.compile(r"https://kokkai\.ndl\.go\.jp/txt/(\w+)/(\d+)")
BASE = "/mnt/project-files/private-m2"


def meeting(issue, sleep):
    out, start = {}, 1
    while True:
        url = API + "?" + urllib.parse.urlencode({"issueID": issue, "startRecord": start, "maximumRecords": 100,
                                                   "recordPacking": "json"})
        for i in range(4):
            try:
                with urllib.request.urlopen(url, timeout=90) as r:
                    d = json.loads(r.read().decode("utf-8")); break
            except Exception:
                time.sleep(sleep * (2 ** (i + 1)))
        else:
            raise RuntimeError(url)
        time.sleep(sleep)
        for rec in d.get("speechRecord") or []:
            out[str(rec["speechOrder"])] = rec.get("speaker") or ""
        if not d.get("nextRecordPosition"):
            return out
        start = int(d["nextRecordPosition"])


def norm(s):
    return re.sub(r"\s", "", s or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=f"{BASE}/allocation/involvements.csv")
    ap.add_argument("--out", default=f"{BASE}/kokkai-direct/involvements-url-check.csv")
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.csv, encoding="utf-8")))
    cache = {}
    res = []
    for r in rows:
        m = URL_RE.match(r.get("証拠URL", ""))
        if not m:
            res.append({**r, "照合": "対象外", "実際の発言者": ""}); continue
        issue, order = m.groups()
        if issue not in cache:
            cache[issue] = meeting(issue, a.sleep)
            print(len(cache), file=sys.stderr)
        sp = cache[issue].get(order)
        ok = sp is not None and norm(sp) in (norm(r["氏名"]), norm(r.get("氏名_原表記")))
        res.append({**r, "照合": "一致" if ok else "不一致", "実際の発言者": sp if sp is not None else "（発言番号なし）"})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(res[0].keys())); w.writeheader(); w.writerows(res)
    from collections import Counter
    print(dict(Counter(x["照合"] for x in res)))


if __name__ == "__main__":
    main()
