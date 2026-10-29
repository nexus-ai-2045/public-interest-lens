"""議員ごとの届出団体 `app/public/distribution/political-funds-groups.json` を作る。

入力
- data/acquired/political-funds/member-groups.csv：総務省「政治団体名簿」（現職国会議員の資金管理団体・国会議員関係政治団体）を表にしたもの。
  1行＝名簿の1行（氏名・院・選挙区・届出先・団体名・種別・名簿・資料URL）。
- data/derived/person-ids/persons.csv：人物ID。

出すのは「どの団体が届け出られているか」と、その名簿の一次資料（総務省の PDF）だけ。収入・支出・寄附先の金額は、
収支報告書の読み取り結果（relations.csv・spending-by-member.json）がリポジトリに無いので出さない（推測で埋めない）。
点数には使わない。人物IDに一意に結べない名前は結ばず、件数だけ数える（同姓同名は院で分け、それでも決まらなければ結ばない）。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.person_ids import canonical  # noqa: E402

GROUPS = ROOT / "data" / "acquired" / "political-funds" / "member-groups.csv"
PERSONS = ROOT / "data" / "derived" / "person-ids" / "persons.csv"
OUTPUT = ROOT / "app" / "public" / "distribution" / "political-funds-groups.json"

SOUMU_PDF = re.compile(r"https://www\.soumu\.go\.jp/main_content/\d+\.pdf")
HOUSE = {"衆": "衆議院", "参": "参議院"}
KIND_ORDER = {"資金管理団体": 0, "国会議員関係政治団体": 1}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build() -> dict:
    index: dict[str, dict[str, dict]] = {}
    for p in read_csv(PERSONS):
        if not p["人物ID"]:
            continue
        for name in [p["氏名"], *[a for a in (p["別表記"] or "").split("|") if a]]:
            index.setdefault(canonical(name), {})[p["人物ID"]] = p

    def person_of(row: dict) -> str | None:
        for name in (row["氏名"], row["届出上の氏名"]):
            if not name:
                continue
            found = list(index.get(canonical(name), {}).values())
            if len(found) > 1:
                found = [p for p in found if p["院"] == HOUSE[row["院"]]]
            if len(found) == 1:
                return found[0]["人物ID"]
        return None

    rosters: dict[str, dict] = {}
    members: dict[str, dict[tuple, dict]] = {}
    unlinked: set[str] = set()
    names: set[str] = set()
    for row in read_csv(GROUPS):
        if not SOUMU_PDF.fullmatch(row["資料URL"]):
            raise ValueError(f"総務省の名簿 PDF 以外の URL があります: {row['資料URL']}")
        names.add(row["氏名"])
        rosters.setdefault(row["資料URL"], {"name": row["名簿"], "url": row["資料URL"]})
        pid = person_of(row)
        if pid is None:
            unlinked.add(row["氏名"])
            continue
        group = members.setdefault(pid, {}).setdefault(
            (row["団体名"], row["種別"], row["届出先"]),
            {"name": row["団体名"], "kind": row["種別"], "filedWith": row["届出先"], "sources": []},
        )
        if row["資料URL"] not in group["sources"]:
            group["sources"].append(row["資料URL"])
    return {
        "schema": "political-funds-groups/v1",
        "method": "総務省「政治団体名簿」の現職国会議員の資金管理団体一覧・国会議員関係政治団体一覧（文字の PDF）を表にして、人物IDに一意に結べた議員だけ載せる。収入・支出の金額は含まない",
        "rosters": sorted(rosters.values(), key=lambda r: r["url"]),
        "counts": {"rosterMembers": len(names), "linkedMembers": len(members), "unlinkedMembers": len(unlinked),
                   "groups": sum(len(g) for g in members.values())},
        "members": {
            pid: sorted(groups.values(), key=lambda g: (KIND_ORDER.get(g["kind"], 9), g["filedWith"] != "総務大臣", g["filedWith"], g["name"]))
            for pid, groups in sorted(members.items())
        },
    }


def main() -> int:
    argparse.ArgumentParser().parse_args()
    payload = build()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(payload["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
