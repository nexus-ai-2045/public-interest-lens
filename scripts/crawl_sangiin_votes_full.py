"""参議院「本会議投票結果」を第142回国会から最新回次まで取得する（原本保存・再開可能）。

使い方:  python3 scripts/crawl_sangiin_votes_full.py [--root .local/sangiin-votes-full]
- 回次一覧 touhyoulist.html -> 各回次の vote_ind.htm -> 各議案の個人別投票ページ
- 同一サイトへのアクセスは 1.1 秒以上あける。User-Agent に public-interest-lens を入れる。
- 原本は <root>/raw/ に保存し、<root>/manifest.csv に URL・sha256・HTTP結果・取得時刻を追記する。
- 既に保存済みのファイルは再取得しない（途中から再開できる）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.sangiin.go.jp/japanese/touhyoulist/"
TOP = BASE + "touhyoulist.html"
UA = "public-interest-lens/1.0 (research; contact via repository)"
INTERVAL = 1.1
LINK_RE = re.compile(r'href="(\d+-\d{4}-v\d+\.htm)"', re.I)
KAIJI_RE = re.compile(r"touhyoulist/(\d+)/vote_ind\.htm")

_last = 0.0


def fetch(url: str) -> tuple[int, bytes]:
    global _last
    wait = INTERVAL - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        _last = time.monotonic()
        p = subprocess.run(
            ["curl", "-sS", "-A", UA, "--max-time", "60", "-w", "\n%{http_code}", url],
            capture_output=True,
        )
        if p.returncode == 0:
            body, _, code = p.stdout.rpartition(b"\n")
            status = int(code or 0)
            if status < 500:
                return status, body
        time.sleep(3 * (attempt + 1))
    return 0, b""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(".local/sangiin-votes-full"))
    ap.add_argument("--min-kaiji", type=int, default=142)
    args = ap.parse_args()
    raw = args.root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    mpath = args.root / "manifest.csv"
    new = not mpath.exists()
    mf = mpath.open("a", newline="", encoding="utf-8")
    mw = csv.writer(mf)
    if new:
        mw.writerow(["url", "local_path", "sha256", "http_status", "bytes", "fetched_at"])

    def get(url: str, rel: str) -> bytes | None:
        path = raw / rel
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()
        status, body = fetch(url)
        sha = hashlib.sha256(body).hexdigest() if body else ""
        mw.writerow([url, f"raw/{rel}", sha, status, len(body),
                     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
        mf.flush()
        if status != 200 or not body:
            print(f"FAIL {status} {url}", flush=True)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return body

    top = get(TOP, "touhyoulist.html")
    if top is None:
        print("top page failed", flush=True)
        return 1
    kaijis = sorted({int(k) for k in KAIJI_RE.findall(top.decode("utf-8", "replace"))})
    kaijis = [k for k in kaijis if k >= args.min_kaiji]
    print("kaiji", kaijis[0], "-", kaijis[-1], len(kaijis), flush=True)
    for k in kaijis:
        idx = get(f"{BASE}{k}/vote_ind.htm", f"{k}/vote_ind.htm")
        if idx is None:
            continue
        links = sorted(set(LINK_RE.findall(idx.decode("utf-8", "replace"))))
        print(f"kaiji {k}: {len(links)} pages", flush=True)
        for name in links:
            get(f"{BASE}{k}/{name}", f"{k}/{name}")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
