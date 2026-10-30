#!/usr/bin/env python3
"""未成立の提出法案（衆法・参法）の提出者と提出会派を、衆議院の議案経過ページから集める。

入力: data/derived/unenacted-bills-v1/scale.csv の id（衆法-140-18 など）と
      data/acquired/bill-census-full/listing.csv の経過URL。
出力: data/acquired/bill-submitters/submitters.csv（1法案1行）。
  議案提出者は「熊代　昭彦君外四名」の形（筆頭＋人数）。提出者一覧・賛成者は新しい議案にだけ載る。
  載っていない行は空のまま残す（推測で埋めない）。原本は .local/bill-submitters/ に保存。
閣法は提出者が内閣なので取らない。

使い方: python3 scripts/fetch_bill_submitters.py [--sleep 0.3] [--workers 3] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALE = ROOT / "data/derived/unenacted-bills-v1/scale.csv"
LISTING = ROOT / "data/acquired/bill-census-full/listing.csv"
OUT_DIR = ROOT / "data/acquired/bill-submitters"
OUT = OUT_DIR / "submitters.csv"
RAW = ROOT / ".local/bill-submitters"
FIELDS = ["id", "提出者", "提出会派", "提出者一覧", "賛成者", "経過URL", "取得状況", "取得日時"]
ROW = re.compile(r'<TD[^>]*headers="KOMOKU"[^>]*>(.*?)</TD>\s*<TD[^>]*headers="NAIYO"[^>]*>(.*?)</TD>', re.S | re.I)


def clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s.replace("　", " ")).strip()


def parse(html: str) -> dict[str, str]:
    return {clean(k): clean(v) for k, v in ROW.findall(html)}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "public-interest-lens-research/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read()
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / (url.rsplit("/", 1)[-1])).write_bytes(b)
    return b.decode("cp932", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    urls = {}
    for r in csv.DictReader(open(LISTING, encoding="utf-8")):
        urls[f"{r['種別']}-{r['提出回次']}-{r['番号']}"] = r["経過URL"]
    ids = [r["id"] for r in csv.DictReader(open(SCALE, encoding="utf-8")) if r["種別"] in ("衆法", "参法")]
    done = {}
    if OUT.exists():
        done = {r["id"]: r for r in csv.DictReader(open(OUT, encoding="utf-8")) if r["取得状況"] == "取得"}
    todo = [i for i in ids if i not in done]
    if a.limit:
        todo = todo[: a.limit]
    lock = threading.Lock()

    def work(i: str) -> dict[str, str]:
        url = urls.get(i, "")
        row = {k: "" for k in FIELDS}
        row.update(id=i, 経過URL=url)
        if not url:
            row["取得状況"] = "経過URLなし"
            return row
        try:
            d = parse(fetch(url))
            row.update(提出者=d.get("議案提出者", ""), 提出会派=d.get("議案提出会派", ""),
                       提出者一覧=d.get("議案提出者一覧", ""), 賛成者=d.get("議案提出の賛成者", ""),
                       取得状況="取得")
        except Exception as e:  # noqa: BLE001
            row["取得状況"] = f"失敗:{type(e).__name__}"
        row["取得日時"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        time.sleep(a.sleep)
        return row

    with ThreadPoolExecutor(a.workers) as ex:
        for row in ex.map(work, todo):
            with lock:
                done[row["id"]] = row
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for i in ids:
            if i in done:
                w.writerow(done[i])
    ok = sum(1 for r in done.values() if r["取得状況"] == "取得")
    print(f"対象{len(ids)}件 / 取得{ok}件 / 未取得{len(ids) - ok}件")


if __name__ == "__main__":
    main()
