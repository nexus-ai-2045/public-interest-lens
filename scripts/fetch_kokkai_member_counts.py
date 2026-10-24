#!/usr/bin/env python3
"""議員ページの全員について、国会会議録検索システム API から発言の件数と期間を直接取る。

2系統で照合する。
  系統A: speech API で氏名だけを指定した総件数。
  系統B: 同じ API を院ごと（衆議院・参議院・両院）に分けて取った件数の合計。
一致したものだけ「採用」、ずれたものは「保留」として理由を書く。
実名が入るので出力は共有フォルダの private-m2 側に置く（リポジトリには入れない）。

使い方: python3 scripts/fetch_kokkai_member_counts.py [--members app/public/distribution/members.json]
            [--out /mnt/project-files/private-m2/kokkai-direct] [--sleep 1.0]
"""
import argparse, csv, json, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://kokkai.ndl.go.jp/api/speech"
HOUSES = ("衆議院", "参議院", "両院")


def get(params, sleep):
    q = dict(params, recordPacking="json")
    url = API + "?" + urllib.parse.urlencode(q)
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8"))
            time.sleep(sleep)
            return url, body
        except Exception as e:  # 相手の負荷を避けるため間隔を伸ばして取り直す
            err = e
            time.sleep(sleep * (2 ** (i + 1)))
    raise RuntimeError(f"{url}: {err}")


def one(name, sleep):
    url, d = get({"speaker": name, "maximumRecords": 1}, sleep)
    total = int(d.get("numberOfRecords", 0))
    row = {"氏名": name, "照会URL": url, "系統A_総件数": total}
    if total:
        newest = d["speechRecord"][0]
        row["最終発言日"] = newest["date"]
        row["最新の会派"] = newest.get("speakerGroup") or ""
        row["最新の発言URL"] = newest["speechURL"]
        _, old = get({"speaker": name, "maximumRecords": 1, "startRecord": total}, sleep)
        rec = (old.get("speechRecord") or [{}])[0]
        row["初回発言日"] = rec.get("date", "")
        row["初回の発言URL"] = rec.get("speechURL", "")
    b = 0
    for h in HOUSES:
        _, dh = get({"speaker": name, "nameOfHouse": h, "maximumRecords": 1}, sleep)
        n = int(dh.get("numberOfRecords", 0))
        row[f"{h}_件数"] = n
        b += n
    row["系統B_院別合計"] = b
    if total == 0:
        row["判定"], row["理由"] = "保留", "会議録に同じ表記の発言者がいない（表記ゆれの可能性）"
    elif total == b:
        row["判定"], row["理由"] = "採用", ""
    else:
        row["判定"], row["理由"] = "保留", f"総件数{total}と院別合計{b}が不一致"
    return row


COLS = ["氏名", "判定", "理由", "系統A_総件数", "系統B_院別合計", "衆議院_件数", "参議院_件数", "両院_件数",
        "初回発言日", "最終発言日", "最新の会派", "初回の発言URL", "最新の発言URL", "照会URL", "取得日時"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", default="app/public/distribution/members.json")
    ap.add_argument("--out", default="/mnt/project-files/private-m2/kokkai-direct")
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    names = [m["name"] for m in json.load(open(a.members, encoding="utf-8"))["members"]]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / "members-speech-counts.csv"
    done = {}
    if path.exists():  # 途中から再開できるようにする
        for r in csv.DictReader(open(path, encoding="utf-8")):
            done[r["氏名"]] = r
    rows = []
    for i, n in enumerate(names, 1):
        if n in done:
            rows.append(done[n]); continue
        r = one(n, a.sleep)
        r["取得日時"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(r)
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
        print(i, len(names), r["判定"], file=sys.stderr)
    ok = sum(1 for r in rows if r["判定"] == "採用")
    print(f"採用 {ok} / {len(rows)}")


if __name__ == "__main__":
    main()
