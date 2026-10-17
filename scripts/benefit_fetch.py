#!/usr/bin/env python3
"""便益データ取得の共通部品：間隔1秒以上の取得、原本の保存、sha256 つきの manifest.csv。

原本: .local/benefit-data/raw/<source>/（git 管理外）
manifest: data/acquired/benefit-data/manifest.csv
"""
from __future__ import annotations

import csv
import hashlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / ".local/benefit-data/raw"
OUT_DIR = ROOT / "data/acquired/benefit-data"
MANIFEST = OUT_DIR / "manifest.csv"
MANIFEST_COLS = ["source", "url", "local_path", "sha256", "http_status", "bytes", "fetched_at"]
USER_AGENT = "Mozilla/5.0 (public-interest-lens; research use)"
INTERVAL = 1.2

_last = [0.0]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manifest(path: Path = MANIFEST) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["url"]: r for r in csv.DictReader(fh)}


def append_manifest(row: dict, path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)


def fetch(source: str, url: str, filename: str, force: bool = False) -> tuple[Path, int]:
    """url を取得して RAW_ROOT/source/filename に保存し、(パス, HTTP状態) を返す。同じ url は再取得しない。"""
    dest = RAW_ROOT / source / filename
    known = read_manifest().get(url)
    if known and dest.exists() and not force:
        return dest, int(known["http_status"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    body, status = b"", 0
    for attempt in range(3):
        wait = _last[0] + INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body, status = resp.read(), resp.status
            break
        except urllib.error.HTTPError as err:
            body, status = err.read(), err.code
            if status < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError):
            body, status = b"", 0
        time.sleep(2 * (attempt + 1))
    if status == 200:
        dest.write_bytes(body)
    append_manifest({
        "source": source, "url": url, "local_path": str(dest.relative_to(ROOT)) if status == 200 else "",
        "sha256": sha256_bytes(body) if status == 200 else "", "http_status": status, "bytes": len(body),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return dest, status


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: benefit_fetch.py SOURCE URL FILENAME")
    p, s = fetch(*sys.argv[1:])
    print(s, p)
