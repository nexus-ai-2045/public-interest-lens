"""成立した法律ごとの、会派・議員の賛否を公開用の1ファイルにまとめる（/votes ページ用）。

入力：data/acquired/bill-census-full/enacted.csv（衆議院の議案経過。賛成会派・反対会派は第187回国会ごろから）、
      data/acquired/treaty-census/treaties.csv（条約と承認案件。国会が承認したものを法律と同じ形で足す。kind は「条約」「承認」）、
      data/acquired/sangiin-votes/（参議院本会議の採決の一覧・議員名簿・議員ごとの賛否）
出力：app/public/distribution/votes.json
対応づけ：参議院の議決日と同じ日の採決のうち、議案名（日程番号・括弧書き・「」書きを除く）が題名と完全に一致する1件だけ。
          2件以上当たるときと当たらないときは個人の賛否を載せない（推測でつながない）。
          起立採決は個人の記録が残らないので、会派別・個人別の数は載せない。
使い方：python3 scripts/build_public_votes.py
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "data/acquired/bill-census-full/enacted.csv"
TREATIES = ROOT / "data/acquired/treaty-census/treaties.csv"
VOTES = ROOT / "data/acquired/sangiin-votes"
OUT = ROOT / "app/public/distribution/votes.json"
ERA = {"令和": 2018, "平成": 1988, "昭和": 1925}


def era_date(text: str) -> str | None:
    m = re.match(r"(令和|平成|昭和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日", text or "")
    if not m:
        return None
    year = 1 if m[2] == "元" else int(m[2])
    return f"{ERA[m[1]] + year:04d}-{int(m[3]):02d}-{int(m[4]):02d}"


def norm_title(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"^日程第\d+\s*", "", t)
    t = re.sub(r"「[^」]*」", "", t)
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    return re.sub(r"\s+", "", t)


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def split_parties(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(";") if p.strip()]


def treaty_rows() -> list[dict[str, str]]:
    """国会が承認した条約・承認案件を、enacted.csv と同じ列名にそろえる（回次は提出回次、公布日は無い）。"""
    if not TREATIES.exists():
        return []
    return [{**t, "回次": t["提出回次"], "公布日": ""} for t in read(TREATIES) if t["審議状況"] in ("両院承認", "承認")]


def build() -> dict:
    enacted = read(CENSUS) + treaty_rows()
    votes = read(VOTES / "votes_index.csv")
    members = {(r["回次"], r["議員ID"]): r for r in read(VOTES / "members.csv")}
    by_date: dict[str, list[dict]] = defaultdict(list)
    for v in votes:
        by_date[v["投票日"]].append(v)
    ballots: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in sorted((VOTES / "ballots").glob("ballots_*.csv")):
        for b in read(path):
            ballots[b["投票ID"]].append((b["議員ID"], b["賛否"]))

    laws: list[dict] = []
    people: dict[str, dict] = {}
    matched = ambiguous = 0
    for e in enacted:
        shu_yes, shu_no = split_parties(e["賛成会派_衆"]), split_parties(e["反対会派_衆"])
        san_date = era_date(e["議決日_参"])
        hits = [v for v in by_date.get(san_date or "", []) if norm_title(v["議案名"]) == norm_title(e["題名"])]
        if len(hits) > 1:
            ambiguous += 1
        vote = hits[0] if len(hits) == 1 else None
        san = None
        if vote:
            matched += 1
            san = {"url": vote["出典URL"], "method": "ballot" if vote["採決方法"] == "押しボタン" else "standing", "date": san_date}
            if san["method"] == "ballot":
                group: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
                nos: list[str] = []
                for mid, mark in ballots.get(vote["投票ID"], []):
                    m = members.get((vote["回次"], mid))
                    if not m or mark not in ("Y", "N", "A"):
                        continue
                    group[m["会派"]][("Y", "N", "A").index(mark)] += 1
                    p = people.setdefault(m["議員名"], {"name": m["議員名"], "group": m["会派"], "yes": 0, "no": 0, "absent": 0, "last": ""})
                    p["group"], p["last"] = m["会派"], san_date or p["last"]
                    p["yes" if mark == "Y" else "no" if mark == "N" else "absent"] += 1
                    if mark == "N":
                        nos.append(m["議員名"])
                san["groups"] = {g: v for g, v in sorted(group.items())}
                san["no"] = sorted(nos)
        if not shu_yes and not (san and san["method"] == "ballot"):
            continue
        laws.append({
            "id": f"{e['種別']}-{e['提出回次']}-{e['番号']}", "title": e["題名"], "kind": e["種別"], "session": int(e["回次"]),
            "proposer": e["提出者"] or "内閣", "promulgated": era_date(e["公布日"]), "url": e["経過URL"],
            "shu": {"date": era_date(e["議決日_衆"]), "yes": shu_yes, "no": shu_no} if shu_yes else None,
            "san": san,
        })
    laws.sort(key=lambda l: ((l["promulgated"] or (l["shu"] or {}).get("date") or (l["san"] or {}).get("date") or ""), l["id"]), reverse=True)
    member_rows = sorted(people.values(), key=lambda p: (-p["no"], p["name"]))
    slot = {p["name"]: i for i, p in enumerate(member_rows)}
    for l in laws:
        if l["san"] and l["san"]["method"] == "ballot":
            l["san"]["no"] = [slot[name] for name in l["san"]["no"]]
    return {
        "schema": "public-votes/v1",
        "notes": [
            "衆議院は起立採決が多く、個人の賛否は記録に残りません。議案の経過に載る会派ごとの賛成・反対だけを使います（第187回国会＝2014年より前の法律は載っていません）。",
            "参議院は押しボタン式の採決だけ、議員ごとの賛否が残ります。起立採決の法律は会派別の数も出せません。",
            "参議院の採決は、議決日と議案名が完全に一致する1件だけをつないでいます。一致しない法律は個人の賛否を載せません。",
            "条約の承認と、法律の規定に基づく承認案件も同じ表に入れています（種別は「条約」「承認」。公布日は無いので議決日で並べます）。国会は条約を修正できず、承認か否かの1票です。",
            "議員は氏名で数えています。同姓同名は区別できません。会派名は採決した時の名前のままです（合流・改称が多いため）。",
        ],
        "counts": {"laws": len(laws), "treaties": sum(1 for l in laws if l["kind"] in ("条約", "承認")), "shugiin": sum(1 for l in laws if l["shu"]), "sangiinBallot": sum(1 for l in laws if l["san"] and l["san"]["method"] == "ballot"), "sangiinStanding": sum(1 for l in laws if l["san"] and l["san"]["method"] == "standing"), "members": len(member_rows), "ambiguous": ambiguous},
        "laws": laws,
        "members": member_rows,
    }


def main() -> int:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(data["counts"], f"{OUT.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
