"""第77〜141回国会（1976〜1997年）の成立法の一覧を作る。

入力は衆議院「制定法律」の回次別一覧（houritsu/kaiji○○○_l.htm）を WebFetch で読んだ抽出結果
（data/acquired/bill-census-old/webfetch-extract.json）。クラウドから衆議院へ直接は届かないため、
要約モデル経由の抽出で、原本のバイトは無い（暫定値）。そのため次の検算が全部通った行だけを採る。

- 本文ページの URL（houritsu/<回次3桁><公布日8桁><法律番号3桁>.htm）の回次・番号が、表の回次・番号と一致する。
- 元号の年ごとに法律番号が 1 から欠けずに続く（欠けた番号は report に出す）。

出力:
- enacted_old.csv: 回次, 法律番号, 法令番号, 公布日, 題名, 出典URL, 一覧URL
- manifest.csv: 回次ごとの一覧URL・行数・抽出結果の sha256（原本ではなく抽出文の hash）
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "acquired" / "bill-census-old"
URL_RE = re.compile(r"/houritsu/(\d{3})(\d{8})(\d{3})\.htm$")
HEISEI_START = dt.date(1989, 1, 8)
DIGITS = "〇一二三四五六七八九"


def kanji_number(n: int) -> str:
    """1〜9999 を法令番号の漢数字（例 百二十三）にする。"""
    if n <= 0:
        raise ValueError(n)
    out = ""
    for value, unit in ((1000, "千"), (100, "百"), (10, "十")):
        q, n = divmod(n, value)
        if q:
            out += ("" if q == 1 else DIGITS[q]) + unit
    if n:
        out += DIGITS[n]
    return out


def era_year(date: dt.date) -> tuple[str, int]:
    if date >= HEISEI_START:
        return "平成", date.year - 1988
    return "昭和", date.year - 1925


def law_num_text(date: dt.date, number: int) -> str:
    era, year = era_year(date)
    year_text = "元" if year == 1 else kanji_number(year)
    return f"{era}{year_text}年法律第{kanji_number(number)}号"


def build(sessions: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    rows, manifest, problems = [], [], []
    for s in sorted(sessions, key=lambda s: s["回次"]):
        payload = json.dumps(s["rows"], ensure_ascii=False, sort_keys=True).encode()
        manifest.append({
            "回次": s["回次"], "一覧URL": s["url"], "取得": "取得" if s["取得"] else "取得できず",
            "行数": len(s["rows"]), "抽出結果のsha256": hashlib.sha256(payload).hexdigest(),
            "取得経路": "WebFetch（要約モデル経由の抽出、暫定）", "メモ": s["メモ"],
        })
        if not s["取得"]:
            problems.append(f"第{s['回次']}回: 一覧を読めなかった（{s['メモ']}）")
        for r in s["rows"]:
            m = URL_RE.search(r["リンクURL"])
            number = int(re.sub(r"\D", "", r["法律番号"]) or 0)
            if not m or int(m.group(1)) != s["回次"] or int(m.group(3)) != number:
                problems.append(f"第{s['回次']}回 {r}: URL と回次・番号が一致しないため採らない")
                continue
            date = dt.datetime.strptime(m.group(2), "%Y%m%d").date()
            rows.append({
                "回次": s["回次"], "法律番号": number, "法令番号": law_num_text(date, number),
                "公布日": date.isoformat(), "題名": r["題名"].strip(), "出典URL": r["リンクURL"], "一覧URL": s["url"],
            })
    by_year = defaultdict(set)
    for r in rows:
        era, year = era_year(dt.date.fromisoformat(r["公布日"]))
        by_year[(era, year)].add(r["法律番号"])
    for key, numbers in sorted(by_year.items(), key=lambda kv: (kv[0][0] != "昭和", kv[0][1])):
        missing = sorted(set(range(1, max(numbers) + 1)) - numbers)
        if missing:
            problems.append(f"{key[0]}{key[1]}年: 法律番号 {missing} が一覧に無い")
    return rows, manifest, problems


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", type=Path, default=DIR / "webfetch-extract.json")
    args = ap.parse_args()
    rows, manifest, problems = build(json.loads(args.extract.read_text(encoding="utf-8")))
    write_csv(DIR / "enacted_old.csv", rows)
    write_csv(DIR / "manifest.csv", manifest)
    print(f"成立法 {len(rows)} 本（第{manifest[0]['回次']}〜{manifest[-1]['回次']}回）")
    for p in problems:
        print("注意:", p)


if __name__ == "__main__":
    main()
