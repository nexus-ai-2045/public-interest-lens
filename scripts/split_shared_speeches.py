#!/usr/bin/env python3
"""1つの発言を2本以上の法案が材料にしているとき（まとめて説明された法案など）、発言の全文から法案ごとの部分を切り出す。

speeches.csv の抜粋は発言の冒頭だけなので、まとめて説明された2本目以降の法案の話が入っていないことがある。
ここでは国会会議録検索システム API から発言の全文を取り、その法案の題名が出てくる所から、
ほかの法案の題名が出てくる所の手前までを、その法案の部分とする。
- 題名が全文に出てこない法案は切り出さない（どの部分か決められないため）。
- 同じ題名の法案が同じ発言を材料にしているときは切り出さない。
- 題名を並べただけの文の中にしか出てこない法案は切り出さない。
- ほかの法案の説明の途中で触れているだけの所は使わず、その法案の説明の見出しになっている所から切り出す。
- 切り出した部分が短すぎる（120字未満で、題名のほかに中身が無い）ものは使わない。
出力：data/acquired/bill-speeches/segments.csv（id, 区分, 抜粋, URL, 取得日時）

使い方: python3 scripts/split_shared_speeches.py [--sleep 0.4] [--workers 4]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_bill_speeches import ENACTED, OUT_DIR, get  # noqa: E402

SPEECHES = OUT_DIR / "speeches.csv"
OUT = OUT_DIR / "segments.csv"
FIELDS = ["id", "区分", "抜粋", "URL", "取得日時"]
BASES = {"説明": ("説明のURL", 1200), "反対": ("反対のURL", 600)}
MIN_LENGTH = 120
LEAD_LIMIT = 30
HEADING_AFTER = re.compile(r"^案?(等)?(について|につきまして|に関し|に対し|の提案理由|の趣旨|であります|を議題|に反対|に対する|、|及び|並びに)")
# 「〇〇法並びに△△法の廃止法案について」のように2本の題名を並べた見出しは、どちらの法案の話か区別できない
JOINT_AFTER = re.compile(r"^案?(等)?(及び|並びに)")
JOINT_LEAD = re.compile(r"(及び|並びに)$")
TXT = re.compile(r"/txt/([^/]+)/(\d+)$")


def short(title: str) -> str:
    return re.sub(r"案$", "", title)


def read_speeches(folder: Path) -> list[dict]:
    """並べて取った分（speeches-*.csv）も、概要づくり（build_law_overviews.py）と同じくまとめて読む。"""
    rows = {row["id"]: row for path in sorted(folder.glob("speeches*.csv")) for row in csv.DictReader(path.open(encoding="utf-8"))}
    return list(rows.values())


def full_text(url: str, sleep: float) -> str:
    match = TXT.search(url)
    if not match:
        raise LookupError("発言の URL の形が違う")
    data = get({"issueID": match.group(1), "speechNumber": match.group(2)}, sleep)
    records = data.get("speechRecord") or []
    if not records or not records[0].get("speech"):
        # 応答が空でも、取れなかったものとして扱う（前回の切り出しを消さないように）
        raise LookupError("発言の全文が空")
    return records[0]["speech"]


def find(text: str, name: str, start: int, longer: list[str]) -> int:
    """長い題名の一部として出てくる所（「防衛庁設置法及び自衛隊法の一部を改正する法律」の中の「自衛隊法の一部を改正する法律」など）は数えない。"""
    for other in longer:
        if len(other) > len(name) and name in other:
            text = text.replace(other, "＿" * len(other))
    return text.find(name, start)


def heading(text: str, name: str, longer: list[str]) -> tuple[int, int]:
    """その法案の説明の見出しになっている所（「次に、〇〇法律案について、その提案理由…」など）を探す。

    ほかの法案の題名と「及び」「並びに」でつないだ見出し（閣法-155-47 の反対討論など）も使わない。
    ほかの法案の説明の途中で触れているだけの所（「同時に提出いたしております〇〇法律案と相まって」など）は使わない。
    見出しは、文の頭から題名までが短く（「次に、」「○〇〇国務大臣 」など）、題名のすぐ後に「について」「につきまして」などが続く所とする。
    """
    pos = find(text, name, 0, longer)
    while pos >= 0:
        head = max(text.rfind("。", 0, pos), text.rfind("\n", 0, pos)) + 1
        lead = text[head:pos].strip()
        after = text[pos + len(name):pos + len(name) + 12]
        joint = JOINT_AFTER.match(after) or JOINT_LEAD.search(lead)
        if len(lead) <= LEAD_LIMIT and HEADING_AFTER.match(after) and not joint:
            return pos, head
        pos = find(text, name, pos + len(name), longer)
    return -1, -1


def segment(text: str, title: str, others: list[str], limit: int, longer: list[str]) -> str:
    """その法案の題名が最初に出る所から、ほかの法案の題名が次に出る所の手前まで。"""
    start, head = heading(text, short(title), longer)
    if start < 0:
        return ""
    # 題名を並べただけの文（「これらは、すなわち、〇〇法案、△△法案、…」）は、その法案の部分とは言えない
    if any(find(text[head:start], short(other), 0, longer) >= 0 for other in others):
        return ""
    ends = [pos for other in others for pos in [find(text, short(other), start + len(short(title)), longer)] if pos >= 0]
    end = min(ends) if ends else len(text)
    end = max(text.rfind("。", 0, end), text.rfind("\n", 0, end)) + 1 or end
    body = re.sub(r"\s+", " ", text[head:end]).strip()
    # 「〇〇法律案及び」のように題名だけで中身の無い部分は使わない
    if len(body) < MIN_LENGTH:
        return ""
    return body if len(body) <= limit else body[: limit - 1] + "…"


def keep_stamps(results: list[dict], previous: list[dict]) -> list[dict]:
    """中身（抜粋・URL）が前回と同じ行は取得日時を前回のまま残す。毎回の取り直しで全行の日時だけが動き、定期更新が空振りの PR を作るのを防ぐ。"""
    old = {(row["id"], row["区分"]): row for row in previous}
    for row in results:
        before = old.get((row["id"], row["区分"]))
        if before and before["抜粋"] == row["抜粋"] and before["URL"] == row["URL"]:
            row["取得日時"] = before["取得日時"]
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    rows = read_speeches(SPEECHES.parent)
    longer = sorted({short(row["題名"]) for row in csv.DictReader(ENACTED.open(encoding="utf-8"))}, key=len, reverse=True)
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        for kind, (column, _) in BASES.items():
            if row[column]:
                groups.setdefault((kind, row[column]), []).append(row)
    shared = {key: members for key, members in groups.items() if len(members) > 1}
    print(f"共有された発言 {len(shared)} 件", flush=True)

    def work(item: tuple[tuple[str, str], list[dict]]) -> list[dict] | None:
        (kind, url), members = item
        titles = [short(member["題名"]) for member in members]
        try:
            text = full_text(url, args.sleep)
        except Exception as exc:  # 取れなかった発言は、後で前回の切り出しを残す
            print(f"取得できず {url}: {str(exc)[:80]}", file=sys.stderr)
            return None
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out = []
        for member in members:
            if titles.count(short(member["題名"])) > 1:
                continue
            others = [m["題名"] for m in members if m is not member]
            body = segment(text, member["題名"], others, BASES[kind][1], longer)
            if body:
                out.append({"id": member["id"], "区分": kind, "抜粋": body, "URL": url, "取得日時": stamp})
        return out

    order = {row["id"]: index for index, row in enumerate(rows)}
    items = sorted(shared.items())
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        chunks = list(pool.map(work, items))
    results = [row for chunk in chunks if chunk for row in chunk]
    # 取れなかった発言は、前回切り出した部分をそのまま残す（一時的な失敗で切り出しが消えないように）
    failed = {(kind, url) for ((kind, url), _), chunk in zip(items, chunks) if chunk is None}
    if failed and OUT.exists():
        kept = [row for row in csv.DictReader(OUT.open(encoding="utf-8")) if (row["区分"], row["URL"]) in failed and row["id"] in order]
        results.extend(kept)
        print(f"取得できなかった発言 {len(failed)} 件は前回の切り出し {len(kept)} 件を残す", flush=True)
    results.sort(key=lambda row: (order[row["id"]], row["区分"]))
    if OUT.exists():
        results = keep_stamps(results, list(csv.DictReader(OUT.open(encoding="utf-8"))))
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"切り出した部分 {len(results)} 件 → {OUT.relative_to(OUT_DIR.parents[2])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
