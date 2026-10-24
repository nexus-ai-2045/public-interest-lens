"""全議員の表（members-reference.json）の、人への配り先を一次資料と照らし合わせる。

app/src/members-reference.ts が配った全員・全法律の配り先（build_reference_members.mjs --attributions で書き出す）を、
別の実装で1件ずつ次のように確かめる。あわせて、配り先の額を人ごとに足すと公開ファイルの損失・便益（中央値）と一致することも確かめる
（top の5本だけでなく、合計と順位に入るすべての配り先が照合の対象になる）。
- 法律が公開ランキングにあり、確かさが「参考」であること。
- 提出者（proposer）：衆法・参法は成立法の一覧の「提出者」「提出者一覧」にその名前があること。
  閣法は内閣総理大臣で、提出した回次の会期中（継続審査でない閣法の衆議院の付託日のどれか）に在任していたこと。
- 人物ID：配り先の人物IDが人物台帳（persons.csv）にあり、氏名が同じ人物の氏名と canonical で一致すること。同姓同名で分けた名前は
  配っていないこと（台帳は今の院しか持たず院を移った人がいるので、院では決めない）。
- 参議院の賛成（vote）：参議院で議決した日の押しボタン投票のうち、議案名に題名を含むものに、その名前の議員の「賛成」があること。

1件でも合わなければ一覧を出して終了コード1を返す（rebuild_public.py はこのとき取り込まない）。
使い方: python3 scripts/check_reference_members.py [--attributions 配り先.csv]（省略時は作り直して照らす）
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.person_ids import canonical  # noqa: E402
REFERENCE = ROOT / "app/public/distribution/members-reference.json"
RANKING = ROOT / "app/public/distribution/ranking.json"
ENACTED = ROOT / "data/acquired/bill-census-full/enacted.csv"
VOTES_INDEX = ROOT / "data/acquired/sangiin-votes/votes_index.csv"
SANGIIN_MEMBERS = ROOT / "data/acquired/sangiin-votes/members.csv"
BALLOTS = ROOT / "data/acquired/sangiin-votes/ballots"
CABINET = ROOT / "data/acquired/office-holders/cabinet.csv"
PERSONS = ROOT / "data/derived/person-ids/persons.csv"

ERA = {"昭和": 1925, "平成": 1988, "令和": 2018}
COMMITTEE = re.compile(r"(委員長|委員会|調査会長|審査会長)$")
DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def squash(text: str) -> str:
    return re.sub(r"[\s　]", "", text or "")


def norm_name(text: str) -> str:
    return re.sub(r"君$", "", squash(text))


def wareki(text: str) -> str:
    m = re.match(r"(昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日", squash(text).translate(DIGITS))
    if not m:
        return ""
    year = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
    return f"{year:04d}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_attributions(out: Path) -> None:
    subprocess.run(["node", str(ROOT / "scripts/build_reference_members.mjs"), "--no-write", "--attributions", str(out)],
                   cwd=ROOT, check=True, capture_output=True, text=True)


def check(attributions_path: Path | None = None) -> list[str]:
    if attributions_path is None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attributions.csv"
            build_attributions(path)
            return check(path)
    attributions = read_csv(attributions_path)
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    ranking = {law["id"]: law for law in json.loads(RANKING.read_text(encoding="utf-8"))["laws"]}
    enacted = {f"{r['種別']}-{r['提出回次']}-{r['番号']}": r for r in read_csv(ENACTED)}
    pms = [r for r in read_csv(CABINET) if r["役職"] == "内閣総理大臣" and r["就任日_西暦"]]
    referrals: dict[str, set[str]] = {}
    for r in enacted.values():
        d = wareki(r["付託日_衆"]) if r["種別"] == "閣法" and r["回次"] == r["提出回次"] else ""
        if d:
            referrals.setdefault(r["提出回次"], set()).add(d)

    def pm_served(name: str, dates: set[str]) -> bool:
        return any(norm_name(p["氏名"]) == name and p["就任日_西暦"] <= d and (not p["退任日_西暦"] or d < p["退任日_西暦"])
                   for p in pms for d in dates)

    votes_by_day: dict[str, list[dict[str, str]]] = {}
    for v in read_csv(VOTES_INDEX):
        votes_by_day.setdefault(v["投票日"], []).append(v)
    ids_of: dict[str, set[str]] = {}
    for r in read_csv(SANGIIN_MEMBERS):
        ids_of.setdefault(norm_name(r["議員名"]), set()).add(r["議員ID"])

    errors: list[str] = []
    persons = {r["人物ID"]: r for r in read_csv(PERSONS)}
    by_canonical: dict[str, list[dict[str, str]]] = {}
    for p in persons.values():
        by_canonical.setdefault(canonical(p["氏名"]), []).append(p)
    # 人ごとの合計が公開ファイルと一致するか（配り先の一覧が公開ファイルの合計をすべて説明していること）。
    totals: dict[tuple[str, str], float] = {}
    for a in attributions:
        key = (a["member"], a["side"])
        totals[key] = totals.get(key, 0.0) + float(a["median"])
    published = {m["id"]: m for m in reference["members"]}
    for (member, side), total in totals.items():
        m = published.get(member)
        expected = m and (m["loss"] if side == "loss" else m["credit"])["median"]
        if m is None or abs(total - expected) > 1e-6 * max(1.0, abs(expected)):
            errors.append(f"{member}：配り先の{side}の合計が公開ファイルと合わない")
    for m in reference["members"]:
        for side, field in (("loss", "loss"), ("benefit", "credit")):
            if m[field]["median"] and (m["id"], side) not in totals:
                errors.append(f"{m['id']}：公開ファイルの{side}に配り先が無い")

    vote_entries = []
    unique = {(a["name"], a["lawId"], a["role"]): a for a in attributions}
    for (name, law_id, role), a in sorted(unique.items()):
        m = {"name": name, "id": a["member"]}
        where = f"{m['id']} / {law_id}（{role}）"
        law = ranking.get(law_id)
        bill = enacted.get(law_id)
        if not law or law.get("certainty") != "参考" or not bill:
            errors.append(f"{where}：公開ランキングの参考の法律、または成立法の一覧に無い")
            continue
        person = persons.get(a["member"])
        if person is not None and canonical(person["氏名"]) != canonical(name):
            errors.append(f"{where}：人物IDの氏名が出典の氏名と合わない")
        elif len(by_canonical.get(canonical(name), [])) > 1:
            # 台帳は今の院しか持たない（院を移った人がいる）ので、同姓同名は院でも配ってはいけない。
            errors.append(f"{where}：同姓同名の人を、一次資料で所属が決まらないまま配っている")
        elif a["member"] not in persons and a["member"] != canonical(name):
            errors.append(f"{where}：人物IDが人物台帳に無い")
        if role == "proposer":
            if law_id.startswith("閣法"):
                if not pm_served(m["name"], referrals.get(bill["提出回次"], set())):
                    errors.append(f"{where}：提出した回次の会期中に在任した内閣総理大臣ではない")
            elif COMMITTEE.search(re.sub(r"君(外.+名)?$", "", squash(bill["提出者"]))):
                errors.append(f"{where}：委員会提出の法律を人に配っている")
            elif m["name"] not in squash(bill["提出者"]) + squash(bill["提出者一覧"]):
                errors.append(f"{where}：成立法の一覧の提出者に名前が無い")
        else:
            vote_entries.append((m, bill, where))

    needed: dict[str, list[str]] = {}
    for m, bill, where in vote_entries:
        title = squash(bill["題名"])
        title = title[:-1] if title.endswith("案") else title
        hits = [v["投票ID"] for v in votes_by_day.get(wareki(bill["議決日_参"]), []) if title + "案" in squash(v["議案名"])]
        if not hits:
            errors.append(f"{where}：参議院で議決した日に、題名の合う押しボタン投票が無い")
        needed[where] = hits
    wanted = {vid for hits in needed.values() for vid in hits}
    yes: set[tuple[str, str]] = set()
    for path in sorted(BALLOTS.glob("*.csv")):
        for r in read_csv(path):
            if r["賛否"] == "Y" and r["投票ID"] in wanted:
                yes.add((r["投票ID"], r["議員ID"]))
    for m, bill, where in vote_entries:
        hits = needed[where]
        if hits and not any((vid, pid) in yes for vid in hits for pid in ids_of.get(m["name"], ())):
            errors.append(f"{where}：題名の合う投票に、この名前の議員の賛成が無い")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="全議員の表の配り先を一次資料と照らす")
    parser.add_argument("--attributions", type=Path, help="build_reference_members.mjs --attributions の出力（省略時は作り直す）")
    errors = check(parser.parse_args().attributions)
    if errors:
        print(f"全議員の表の配り先が一次資料と合わない：{len(errors)}件")
        for e in errors[:50]:
            print("  " + e)
        return 1
    print("全議員の表の配り先：一次資料と一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
