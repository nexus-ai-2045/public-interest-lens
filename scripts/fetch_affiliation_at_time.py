"""議員の「当時の会派」を、関与の記録の日付ごとに国会会議録 API の発言者所属会派（speakerGroup）から取る。

入力：data/derived/allocation-v1/involvements.csv の（人物ID, 氏名, 年）。重複は1回だけ引く。
日付ごとだと、採決の日に発言していない人が引けない（8割が空）ので、年単位で引き、その年の発言で最も多い会派を採る。
年の途中で会派が変わった人は多数の側になる。出力の「日付」列は年（YYYY）。
出力：data/acquired/member-affiliation/at-time.csv（途中から再開できる。取れなかった行は 当時の会派 を空にして残す）。
使い方: python3 scripts/fetch_affiliation_at_time.py [--limit N]
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/derived/allocation-v1/involvements.csv"
OUT = ROOT / "data/acquired/member-affiliation/at-time.csv"
API = "https://kokkai.ndl.go.jp/api/speech?"
HEAD = ["人物ID", "氏名", "日付", "当時の会派", "照合した発言数", "出典URL"]


def lookup(name: str, year: str) -> tuple[str, int, str]:
    q = urllib.parse.urlencode({"speaker": name, "from": f"{year}-01-01", "until": f"{year}-12-31", "maximumRecords": 100, "recordPacking": "json"})
    with urllib.request.urlopen(API + q, timeout=30) as r:
        data = json.load(r)
    groups = Counter(s["speakerGroup"] for s in data.get("speechRecord", []) if s.get("speaker", "").replace(" ", "").replace("　", "") == name and s.get("speakerGroup"))
    group = groups.most_common(1)[0][0] if groups else ""
    return group, sum(groups.values()), API + q


def main() -> None:
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**9
    # --shard i/n：n 本に分けて並列に取る。出力は at-time.shard-i.csv（最後に まとめる）。
    shard = sys.argv[sys.argv.index("--shard") + 1] if "--shard" in sys.argv else ""
    out = OUT.with_name(f"at-time.shard-{shard.split('/')[0]}.csv") if shard else OUT
    keys = sorted({(r["人物ID"], r["氏名"], r["日付"][:4]) for r in csv.DictReader(SRC.open(encoding="utf-8")) if r["日付"]})
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        keys = [k for j, k in enumerate(keys) if j % n == i]
    done = set()
    if out.exists():
        done = {(r["人物ID"], r["氏名"], r["日付"]) for r in csv.DictReader(out.open(encoding="utf-8"))}
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(HEAD)
    todo = [k for k in keys if k not in done][:limit]
    with out.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for i, (pid, name, date) in enumerate(todo):
            try:
                group, n, url = lookup(name, date)
            except Exception as e:  # noqa: BLE001 取れない行は空で残し、次回も引き直さない
                group, n, url = "", 0, f"error:{str(e)[:40]}"
            w.writerow([pid, name, date, group, n, url])
            f.flush()
            time.sleep(0.7)
            if i % 200 == 0:
                print(i, len(todo), flush=True)


if __name__ == "__main__":
    main()
