#!/usr/bin/env python3
"""未成立の提出法案に、提出した議員（人物ID）と提出会派を結ぶ。

入力: data/acquired/bill-submitters/submitters.csv（fetch_bill_submitters.py）
      data/derived/person-ids/persons.csv（人物ID の台帳）、data/derived/allocation-v1/vote-parties.csv（会派名の既知一覧）
出力: data/derived/unenacted-bills-v1/submitters.csv（1法案1行）
  - 筆頭提出者を人物IDに結ぶ。衆法は衆議院議員、参法は参議院議員だけを候補にする（提出した院は法案の種別で確定する）。
  - 結べない行は理由を残す（名簿に無い／同姓同名で決められない／提出者の記載なし）。推測で埋めない。
  - 提出者一覧・賛成者は載っている法案だけ人物IDに結ぶ（院は種別から。賛成者は他院でも署名できないので同じ院）。
  - 点数・額には使わない。表示用の「誰が出したか」だけ。
使い方: python3 scripts/build_bill_submitters.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.allocation_involvements import normalize_name  # noqa: E402
from scripts.person_ids import canonical  # noqa: E402

SRC = ROOT / "data/acquired/bill-submitters/submitters.csv"
PERSONS = ROOT / "data/derived/person-ids/persons.csv"
PARTIES = ROOT / "data/derived/allocation-v1/vote-parties.csv"
OUT = ROOT / "data/derived/unenacted-bills-v1/submitters.csv"
FIELDS = ["id", "種別", "提出者の筆頭", "外の人数", "筆頭の人物ID", "結べなかった理由", "提出会派", "会派が既知の名前",
          "提出者一覧の人数", "提出者一覧で結べた人数", "賛成者の人数", "賛成者で結べた人数", "出典URL"]
HOUSE = {"衆法": "衆議院", "参法": "参議院"}
KUN = re.compile(r"君$")
OTHERS = re.compile(r"外([一二三四五六七八九十百〇\d]+)名$")
KANSUU = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kan(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    n, t = 0, 0
    for ch in s:
        if ch == "十":
            t = (t or 1) * 10
        elif ch == "百":
            n += (t or 1) * 100
            t = 0
        elif ch in KANSUU:
            t += KANSUU[ch]
    return (n + t) or None


def main() -> None:
    by_house: dict[str, dict[str, set[str]]] = {"衆議院": defaultdict(set), "参議院": defaultdict(set)}
    for p in csv.DictReader(open(PERSONS, encoding="utf-8")):
        if not p["人物ID"]:
            continue
        for n in [p["氏名"], *filter(None, re.split(r"[;／]", p["別表記"]))]:
            if p["院"] in by_house:
                by_house[p["院"]][canonical(n)].add(p["人物ID"])
            else:  # 院が決まらない行（元職など）は両院の候補に入れる
                for h in by_house:
                    by_house[h][canonical(n)].add(p["人物ID"])
    known_parties = {r["会派"] for r in csv.DictReader(open(PARTIES, encoding="utf-8"))}

    def link(name: str, house: str) -> tuple[str, str]:
        c = canonical(KUN.sub("", normalize_name(name)))
        if c.endswith("委員長"):
            return "", "委員会の提出（提出者は委員長の役職名）"
        ids = by_house[house].get(c, set())
        if len(ids) == 1:
            return next(iter(ids)), ""
        if not ids:
            # 院を移った人（台帳の院は今の院だけ）。ほかの院に同じ氏名がちょうど1人なら、その人とする。
            other = by_house["参議院" if house == "衆議院" else "衆議院"].get(c, set())
            if len(other) == 1:
                return next(iter(other)), ""
            return "", "人物IDの台帳に無い（名簿の不足）"
        return "", "同姓同名で決められない"

    rows = []
    for r in csv.DictReader(open(SRC, encoding="utf-8")):
        kind = r["id"].split("-")[0]
        house = HOUSE[kind]
        sub = r["提出者"]
        m = OTHERS.search(sub)
        head = OTHERS.sub("", sub).strip()
        pid, why = ("", "提出者の記載なし") if not head else link(head, house)
        if r["取得状況"] != "取得":
            pid, why = "", "取得できなかった：" + r["取得状況"]
        parties = [x.strip() for x in re.split(r"[;；]", r["提出会派"]) if x.strip()]
        lst = [x for x in r["提出者一覧"].split(";") if x.strip()]
        sup = [x for x in r["賛成者"].split(";") if x.strip()]
        rows.append({
            "id": r["id"], "種別": kind, "提出者の筆頭": head, "外の人数": kan(m.group(1)) if m else 0,
            "筆頭の人物ID": pid, "結べなかった理由": why, "提出会派": ";".join(parties),
            "会派が既知の名前": ";".join(p for p in parties if p in known_parties),
            "提出者一覧の人数": len(lst), "提出者一覧で結べた人数": sum(1 for x in lst if link(x, house)[0]),
            "賛成者の人数": len(sup), "賛成者で結べた人数": sum(1 for x in sup if link(x, house)[0]),
            "出典URL": r["経過URL"],
        })
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    ok = sum(1 for x in rows if x["筆頭の人物ID"])
    reasons: dict[str, int] = defaultdict(int)
    for x in rows:
        if x["結べなかった理由"]:
            reasons[x["結べなかった理由"]] += 1
    print(f"{n}件 / 筆頭を人物IDに結べた {ok}件 / 会派あり {sum(1 for x in rows if x['提出会派'])}件")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  結べない理由 {k}: {v}")


if __name__ == "__main__":
    main()
