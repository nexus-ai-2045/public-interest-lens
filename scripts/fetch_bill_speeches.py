#!/usr/bin/env python3
"""成立した全法律の「提案理由の説明」と「反対討論」を国会会議録検索システム API から集める。

法律ごとの概要（何をする法律か・誰のためか・反対側は何を心配したか）を一次資料から書くための原料。
1法律につき2回だけ問い合わせる（成立した回次と提出回次の範囲で）。
  1. 題名 + 「説明」で探し、提案理由・趣旨の説明の発言を一番早いものから1つ。
  2. 題名 + 「反対」で探し、反対討論の発言を1つ。
発言は抜粋（説明は約900字、反対討論は約500字）と会議録の URL だけを残す。途中で止めても続きから再開できる。

使い方: python3 scripts/fetch_bill_speeches.py [--sleep 0.4] [--workers 3] [--limit N] [ID ...]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://kokkai.ndl.go.jp/api/speech"
ENACTED = ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv"
OUT_DIR = ROOT / "data" / "acquired" / "bill-speeches"
OUT = OUT_DIR / "speeches.csv"
FIELDS = ["id", "題名", "説明の抜粋", "説明の発言者", "説明の会議", "説明の日付", "説明のURL",
          "反対の抜粋", "反対の発言者", "反対の会議", "反対の日付", "反対のURL", "取得状況", "取得日時"]
EXPLAIN = re.compile(r"(提案(の)?理由|趣旨|内容の概要)")
EXPLAIN_VERB = re.compile(r"(御説明|ご説明|説明(を)?申し上げ|説明いたし)")
OPPOSE = re.compile(r"反対(の立場|討論|の討論)")
HEAD = re.compile(r"^○[^　]*　")
# 冒頭の決まり文句（「ただいま議題となりました…御説明申し上げます。」）は飛ばして中身から抜く
BOILERPLATE = re.compile(r"^.{0,200}?(申し上げます|いたします|します)。")


def get(params: dict, sleep: float) -> dict:
    url = API + "?" + urllib.parse.urlencode(dict(params, recordPacking="json"))
    err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            time.sleep(sleep)
            return data
        except Exception as exc:  # 通信の揺れは待って取り直す
            err = exc
            time.sleep(sleep * (2 ** (attempt + 2)))
    raise RuntimeError(f"{url}: {err}")


def clean(text: str, limit: int, skip_boilerplate: bool) -> str:
    body = HEAD.sub("", text.strip()).replace("\r", "")
    if skip_boilerplate:
        body = BOILERPLATE.sub("", body, count=1).strip()
    body = re.sub(r"\s+", " ", body)
    return body if len(body) <= limit else body[: limit - 1] + "…"


def search(short: str, extra: str, sessions: list[str], sleep: float) -> list[dict]:
    records = []
    for session in sessions:
        data = get({"any": f"{short} {extra}", "sessionFrom": session, "sessionTo": session, "maximumRecords": 30}, sleep)
        records += data.get("speechRecord") or []
    return records


ERA_DATE = re.compile(r"(昭和|平成|令和)\s*(元|\d+)年\s*(\d+)月\s*(\d+)日")
ERAS = {"昭和": 1925, "平成": 1988, "令和": 2018}


def iso(text: str) -> str:
    match = ERA_DATE.search(text or "")
    if not match:
        return ""
    era, year, month, day = match.groups()
    return f"{ERAS[era] + (1 if year == '元' else int(year)):04d}-{int(month):02d}-{int(day):02d}"


def explain_rank(rec: dict, row: dict) -> tuple:
    """同じ題名の別の法案（公職選挙法の改正など）を拾わないよう、付託された委員会・提出者の種類・公布前かで順に選ぶ。"""
    head = rec["speech"][:60]
    committees = [name for name in (row["付託委員会_衆"], row["付託委員会_参"]) if name]
    in_committee = any(name and name in rec["nameOfMeeting"] for name in committees)
    by_proposer = ("大臣" in head) if row["種別"] == "閣法" else ("議員" in head or "委員長" in head)
    promulgated = iso(row["公布日"])
    before = not promulgated or rec["date"] <= promulgated
    return (not before, not in_committee, not by_proposer, rec["date"], int(rec.get("speechOrder") or 0))


def collect(row: dict, sleep: float) -> dict:
    law_id = f"{row['種別']}-{row['提出回次']}-{row['番号']}"
    title = row["題名"]
    short = re.sub(r"案$", "", title)
    sessions = sorted({row["回次"], row["提出回次"]}, key=int)
    out = {key: "" for key in FIELDS}
    out.update({"id": law_id, "題名": title, "取得日時": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    notes = []
    try:
        found = [rec for rec in search(short, "説明", sessions, sleep)
                 if EXPLAIN.search(rec["speech"][:400]) and EXPLAIN_VERB.search(rec["speech"][:400])]
        if found:
            rec = min(found, key=lambda item: explain_rank(item, row))
            out.update({"説明の抜粋": clean(rec["speech"], 1200, True), "説明の発言者": rec["speaker"],
                        "説明の会議": f"{rec['nameOfHouse']} {rec['nameOfMeeting']}", "説明の日付": rec["date"], "説明のURL": rec["speechURL"]})
        else:
            notes.append("説明なし")
        against = [rec for rec in search(short, "反対", sessions, sleep) if OPPOSE.search(rec["speech"][:300])]
        if against:
            rec = min(against, key=lambda item: (item["date"], int(item.get("speechOrder") or 0)))
            out.update({"反対の抜粋": clean(rec["speech"], 500, False), "反対の発言者": rec["speaker"],
                        "反対の会議": f"{rec['nameOfHouse']} {rec['nameOfMeeting']}", "反対の日付": rec["date"], "反対のURL": rec["speechURL"]})
        else:
            notes.append("反対討論なし")
        out["取得状況"] = "取得" if not notes else "一部：" + "・".join(notes)
    except Exception as exc:
        out["取得状況"] = f"取得できず：{str(exc)[:120]}"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--retry-failed", action="store_true", help="取得できなかった行を取り直す")
    parser.add_argument("--out", type=Path, default=OUT, help="書き出す先（並べて取るとき用）")
    parser.add_argument("--from-index", type=int, default=0, help="成立法の表の何行目から取るか")
    parser.add_argument("--to-index", type=int, default=0, help="成立法の表の何行目の手前まで取るか（0は最後まで）")
    parser.add_argument("ids", nargs="*")
    args = parser.parse_args()

    rows = list(csv.DictReader(ENACTED.open(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict] = {}
    if args.out.exists():
        done = {row["id"]: row for row in csv.DictReader(args.out.open(encoding="utf-8"))}
    def wanted(row: dict) -> bool:
        law_id = f"{row['種別']}-{row['提出回次']}-{row['番号']}"
        if args.ids:
            return law_id in args.ids
        prev = done.get(law_id)
        return prev is None or (args.retry_failed and prev["取得状況"].startswith("取得できず"))
    todo = [row for row in rows[args.from_index:args.to_index or None] if wanted(row)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"対象 {len(todo)} 本（済み {len(done)} 本）", flush=True)

    lock = threading.Lock()
    count = 0
    def work(row: dict) -> None:
        nonlocal count
        result = collect(row, args.sleep)
        with lock:
            done[result["id"]] = result
            count += 1
            if count % 50 == 0 or count == len(todo):
                write(done, rows, args.out)
                print(f"{count}/{len(todo)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, todo))
    write(done, rows, args.out)
    return 0


def write(done: dict[str, dict], rows: list[dict], out: Path) -> None:
    order = [f"{row['種別']}-{row['提出回次']}-{row['番号']}" for row in rows]
    tmp = out.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for law_id in order:
            if law_id in done:
                writer.writerow(done[law_id])
    tmp.replace(out)


if __name__ == "__main__":
    sys.exit(main())
