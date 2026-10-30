#!/usr/bin/env python3
"""人物台帳に無い議員（元職）を、国会会議録 API の発言者から確かめて名簿に足す。

候補（名前の手がかり）:
  - 未成立法案の提出者の筆頭で、人物IDに結べなかった人（data/derived/unenacted-bills-v1/submitters.csv）
  - 政治資金の関係団体の氏名で、台帳に無い人（data/acquired/political-funds/member-groups.csv）
  - 族議員の表で人物IDが空の人（data/derived/zoku-v1/member-field-ties.csv）
  - 外部の手がかり .local/roster-hints.json（Wikipedia の選挙ページから拾った名前。出典にはしない。無ければ飛ばす）
確かめ方（一次資料）: 会議録 API で 1986-07 以降の発言者を完全一致で引き、発言者の会派（speakerGroup）が付く発言がある人だけを議員として入れる。
  政府参考人・局長などは会派が空なので入らない。1件も見つからない名前は「会議録に一致なし」として残し、入れない（推測しない）。
出力: data/acquired/diet-roster/historical.csv（院・氏名・読み・会派（最多）・最初と最後の発言日・発言数・出典URL・同姓同名の疑い）
      data/acquired/diet-roster/historical-unmatched.csv（入れなかった候補と理由）
再開できる: 取得済みの行は引き直さない。

使い方: python3 scripts/fetch_roster_kokkai.py [--workers 4] [--sleep 0.2] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://kokkai.ndl.go.jp/api/speech"
OUT_DIR = ROOT / "data/acquired/diet-roster"
OUT = OUT_DIR / "historical.csv"
MISS = OUT_DIR / "historical-unmatched.csv"
HINTS = ROOT / ".local/roster-hints.json"
FIELDS = ["氏名", "読み", "院", "会派（最多）", "最初の発言日", "最後の発言日", "発言数", "同姓同名の疑い", "出典URL", "取得日時"]
MISS_FIELDS = ["氏名", "理由", "候補の出どころ", "取得日時"]
NOISE = re.compile(r"[（(].*?[）)]|参議院議員|衆議院議員")


def nospace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def read(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(open(path, encoding="utf-8", newline=""))) if path.exists() else []


def candidates() -> dict[str, str]:
    """氏名 → 候補の出どころ。台帳に既にいる人は除く。"""
    have = set()
    for p in read(ROOT / "data/derived/person-ids/persons.csv"):
        if p["人物ID"]:
            have |= {nospace(n) for n in [p["氏名"], *filter(None, re.split(r"[;／]", p["別表記"]))]}
    have |= {nospace(r["氏名"]) for r in read(OUT)}
    src: dict[str, str] = {}

    def add(name: str, how: str) -> None:
        n = nospace(NOISE.sub("", name or ""))
        if n and n not in have and n not in src:
            src[n] = how

    for r in read(ROOT / "data/derived/unenacted-bills-v1/submitters.csv"):
        if not r["筆頭の人物ID"]:
            add(r["提出者の筆頭"].removesuffix("君"), "未成立法案の提出者")
    for r in read(ROOT / "data/acquired/political-funds/member-groups.csv"):
        add(r["氏名"], "政治資金の関係団体")
    for r in read(ROOT / "data/derived/zoku-v1/member-field-ties.csv"):
        if not r["人物ID"]:
            add(r["氏名"], "族議員の表")
    if HINTS.exists():
        for n in json.load(open(HINTS, encoding="utf-8"))["ext"]:
            add(n, "外部の手がかり（出典にしない）")
    return src


def call(params: dict[str, str]) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "recordPacking": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": "public-interest-lens-research/1.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    raise RuntimeError("API が応答しない")


# 会議録は旧字・異体字で書かれる人がいる（髙橋、山﨑 など）。一致なしのときだけ、字体を置き換えた表記でも引く。
ALT = {"高": "髙", "崎": "﨑", "徳": "德", "浜": "濵", "沢": "澤", "斎": "齋", "斉": "齊", "辺": "邊", "邉": "邊", "島": "嶋"}


def spellings(name: str) -> list[str]:
    out = [name]
    alt = "".join(ALT.get(c, c) for c in name)
    if alt != name:
        out.append(alt)
    rev = {v: k for k, v in ALT.items() if k not in ("邉",)}
    plain = "".join(rev.get(c, c) for c in name)
    if plain not in out:
        out.append(plain)
    return out


def check(name: str, how: str, sleep: float) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    base = {"speaker": name, "from": "1986-07-01", "maximumRecords": "100"}
    for spelled in spellings(name):
        base["speaker"] = spelled
        d = call(base)
        time.sleep(sleep)
        n = int(d.get("numberOfRecords", 0))
        recs = [r for r in d.get("speechRecord", []) if nospace(r.get("speaker", "")) == spelled]
        if recs:
            break
    if not recs:
        return None, {"氏名": name, "理由": "会議録に一致なし（1986-07以降の発言が無い、または表記が違う）", "候補の出どころ": how, "取得日時": now}
    members = [r for r in recs if r.get("speakerGroup")]
    if not members:
        return None, {"氏名": name, "理由": "会派の付く発言が無い（議員ではない可能性）", "候補の出どころ": how, "取得日時": now}
    oldest = call({**base, "startRecord": str(n), "maximumRecords": "1"}).get("speechRecord", [{}])[0]
    time.sleep(sleep)
    yomi = Counter(r.get("speakerYomi") or "" for r in recs + [oldest])
    houses = sorted({r["nameOfHouse"] for r in members if r.get("nameOfHouse") in ("衆議院", "参議院")})
    group = Counter(r["speakerGroup"] for r in members).most_common(1)[0][0]
    url = API + "?" + urllib.parse.urlencode({"speaker": spelled, "from": "1986-07-01", "maximumRecords": "100", "recordPacking": "json"})
    return {
        "氏名": name, "読み": yomi.most_common(1)[0][0], "院": "・".join(houses), "会派（最多）": group,
        "最初の発言日": oldest.get("date", ""), "最後の発言日": recs[0].get("date", ""), "発言数": str(n),
        "同姓同名の疑い": "はい" if len({y for y in yomi if y}) > 1 else "", "出典URL": url, "取得日時": now,
    }, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    cand = candidates()
    done_miss = {r["氏名"]: r for r in read(MISS)}
    todo = [(n, h) for n, h in cand.items() if n not in done_miss]
    if a.limit:
        todo = todo[: a.limit]
    got = {r["氏名"]: r for r in read(OUT)}
    miss = dict(done_miss)
    with ThreadPoolExecutor(a.workers) as ex:
        for ok, ng in ex.map(lambda t: check(t[0], t[1], a.sleep), todo):
            if ok:
                got[ok["氏名"]] = ok
            if ng:
                miss[ng["氏名"]] = ng
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, fields, data in ((OUT, FIELDS, got), (MISS, MISS_FIELDS, miss)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fields, lineterminator="\n")
            w.writeheader()
            w.writerows(sorted(data.values(), key=lambda r: r["氏名"]))
    print(f"候補{len(cand)}（今回{len(todo)}）/ 名簿に足せた{len(got)} / 入れなかった{len(miss)}", file=sys.stderr)


if __name__ == "__main__":
    main()
