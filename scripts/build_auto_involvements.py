"""議員ページで配る法律のうち、関与の一覧（involvements.csv）がまだ無い法律の関与を、一次資料の表から機械的に作る（allocation-v1、設計決定0014）。

関与の一覧は法律ごとに会議録を読んで作ってきたので、確かさ高・中・低の法律の一部（17本）にしか無かった。
その結果、議員ページに配る法律が便益側の5本だけになり、国賊側が「便益の法律に反対した議員」だけになっていた。
ここでは、人の判断を入れずに取れる行動だけを足す（委員長・修正案は会議録を読む必要があるので足さない）。
質疑は、会議録を2系統で読み直して決めた立場の表（scripts/build_auto_questions.py の questions-auto.csv）から、ここで作った法律の分だけ足す。

- 提出（decide）：衆法・参法は議案の提出者の欄（data/acquired/bill-census-full/enacted.csv）。提出者一覧があればその全員、
  無ければ「○○君」の1人だけのときに限る。提出者が決まらない法律（名前の分からない「外N名」・委員会提出）は足さない。
  閣法は内閣の提出なので、総理大臣1人に付けず、提出した回次の会期の最初から最後まで在任した閣僚（総理大臣を含む。設計確定 v2.1、
  app/src/cabinet-members.ts の cabinetForBill と同じ条件）の全員に付ける。総理大臣が会期中に替わる回次は、衆議院の付託日が交代より前の閣法だけ
  付託日に在任した閣僚に付ける（提出は付託より前なので、前の内閣の提出と決まる）。交代より後に付託された閣法は、どちらの内閣の提出か決められないので
  閣僚を付けない（未配分）。その法律の参議院の賛成・反対の行は残す。
  閣僚は国務大臣のこと。内閣官房副長官・総理府総務副長官・内閣法制局長官は官邸の名簿で閣僚の欄にあるが閣僚ではないので除く。閣法の提出者の分は役職の帳簿に入る。
  証拠は衆議院の議案の経過のページ。
- 参議院本会議で賛成（vote）：成立した日の押しボタン投票のうち、題名が一致する1つ（題名の末尾の「案」を除いて照らし、複数あれば原案・全部を採る）。証拠は投票の結果のページ。
  反対票は votes-auto.csv から scripts/build_opposing_votes.py が作る。
- 人物ID は scripts/build_opposing_votes.py と同じ（台帳で1人に決まればその人物ID、無ければ寄せた氏名、複数なら算入しない）。

入力（すべてリポジトリ内）：
  data/derived/publish-v1-triage-v2/publish.csv・data/derived/loss-v1-triage-v2/loss.csv（対象にする法律の選び方：額があり参考でなく、R3 でなく、公開ランキングに載った法律）
  app/public/distribution/ranking.json（公開ランキングに載った法律だけ）
  data/derived/allocation-v1/involvements.csv（すでに関与の一覧がある法律は足さない）
  data/acquired/bill-census-full/enacted.csv・data/acquired/office-holders/cabinet.csv
  data/acquired/sangiin-votes/votes_index.csv・members.csv・ballots/
  data/derived/person-ids/persons.csv
出力：data/derived/allocation-v1/involvements-auto.csv・votes-auto.csv
使い方：python3 scripts/build_auto_involvements.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.allocation_involvements import HEADER  # noqa: E402
from scripts.person_ids import UNRESOLVED, canonical  # noqa: E402

DERIVED = ROOT / "data/derived"
ACQUIRED = ROOT / "data/acquired"
PUBLISH = DERIVED / "publish-v1-triage-v2/publish.csv"
LOSS = DERIVED / "loss-v1-triage-v2/loss.csv"
RANKING = ROOT / "app/public/distribution/ranking.json"
CURATED = DERIVED / "allocation-v1/involvements.csv"
ENACTED = ACQUIRED / "bill-census-full/enacted.csv"
CABINET = ACQUIRED / "office-holders/cabinet.csv"
VOTES_INDEX = ACQUIRED / "sangiin-votes/votes_index.csv"
BALLOTS = ACQUIRED / "sangiin-votes/ballots"
MEMBERS = ACQUIRED / "sangiin-votes/members.csv"
PERSONS = DERIVED / "person-ids/persons.csv"
QUESTIONS = DERIVED / "allocation-v1/questions-auto.csv"
OUT = DERIVED / "allocation-v1/involvements-auto.csv"
OUT_VOTES = DERIVED / "allocation-v1/votes-auto.csv"
VOTES_HEADER = ["法律ID", "投票ID", "日付", "賛成", "反対", "URL"]
NOT_MINISTER = re.compile(r"副長官|法制局長官")
PRIME_MINISTER = "内閣総理大臣"
COMMITTEE = re.compile(r"(委員長|委員会|調査会長|審査会長)$")
WAREKI = re.compile(r"(平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def wareki(text: str) -> str:
    m = WAREKI.search(text or "")
    if not m:
        return ""
    year = (1 if m.group(2) == "元" else int(m.group(2))) + (1988 if m.group(1) == "平成" else 2018)
    return f"{year}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"


def norm(name: str) -> str:
    return re.sub(r"[\s　]", "", name or "").removesuffix("君")


def _squash(s: str) -> str:
    return re.sub(r"[\s　]", "", s)


def pick_vote(title: str, candidates: list[dict[str, str]]) -> dict[str, str] | None:
    """成立した日の参議院の投票から題名が一致する1つ（なければ None）。"""
    t = _squash(title).removesuffix("案")
    hits = [v for v in candidates if t + "案" in _squash(v["議案名"]) and int(v["集計_賛成"]) > int(v["集計_反対"])]
    if len(hits) > 1:
        hits = [v for v in hits if any(k in _squash(v["議案名"]) for k in (t + "案（", t + "案「")) or _squash(v["議案名"]).endswith(t + "案")]
    if len(hits) > 1:
        hits = [v for v in hits if "修正案" not in v["議案名"] or "原案" in v["議案名"]]
    if len(hits) > 1:
        hits = [v for v in hits if re.search("原案|全部", v["議案名"])]
    return hits[0] if len(hits) == 1 else None


def eligible() -> list[dict[str, str]]:
    """関与を作る対象（額があり参考でなく、R3 でない、公開ランキングに載った法律）のうち、関与の一覧が無いもの。"""
    loss = {r["id"]: r for r in _read(LOSS)}
    listed = {law["id"] for law in json.loads(RANKING.read_text(encoding="utf-8"))["laws"]}
    curated = {r["法律ID"] for r in _read(CURATED)}
    out = []
    for p in _read(PUBLISH):
        row = loss.get(p["id"])
        if not row or not row["損失または便益の額"] or row["参考フラグ"] == "参考" or p["判定表の行"] == "R3":
            continue
        if p["id"] in listed and p["id"] not in curated:
            out.append(p)
    return out


def cabinets(enacted: list[dict[str, str]], cabinet: list[dict[str, str]]) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """閣法を出した内閣の閣僚（氏名・役職）を、提出した回次ごと・付託日ごとに返す。{"session": {回次: 閣僚}, "day": {日付: 閣僚}}。

    回次ごと（app/src/cabinet-members.ts の cabinetForBill と同じ条件）：提出日の列が無いので、提出した回次の会期中の衆議院の付託日
    （継続審査でない閣法のもの）の最初と最後の両方で在任した閣僚だけ。途中で替わった閣僚は含めない。
    総理大臣が会期中に替わる回次は、どの内閣の提出かを回次では決められないので載せない。その回次の法律は、付託日ごと（その法律の付託日に在任した閣僚）で引く。
    ただし付託日の総理大臣が会期の最初の付託日の総理大臣と同じ（＝交代より前に付託された）法律だけ。交代より後の付託日は載せない（その法律は閣僚を付けない）。
    氏名は官邸の名簿の脚注の印（*）や字体のゆれを寄せてから比べる（寄せないと、同じ人が別人になり、通して在任した閣僚が落ちる）。
    兼務は1人に数え、役職は総理大臣を先頭に名簿の役職名の順で並べて「・」でつなぐ（名簿の行の順で変わらない）。
    """
    ministers = [dict(r, _n=canonical(r["氏名"])) for r in cabinet if r["区分"] == "閣僚" and r["就任日_西暦"] and not NOT_MINISTER.search(r["役職"])]

    def serving(date: str) -> dict[str, list[str]]:
        posts: dict[str, set[str]] = defaultdict(set)
        for r in ministers:
            if r["就任日_西暦"] <= date and (not r["退任日_西暦"] or date < r["退任日_西暦"]):
                posts[r["_n"]].add(r["役職"])
        return {name: sorted(roles, key=lambda role: (role != PRIME_MINISTER, role)) for name, roles in posts.items()}

    def members(posts: dict[str, list[str]], keep: set[str]) -> list[tuple[str, str]]:
        return sorted((name, "・".join(roles)) for name, roles in posts.items() if name in keep)

    def pm_of(posts: dict[str, list[str]]) -> str:
        return next((name for name, roles in sorted(posts.items()) if PRIME_MINISTER in roles), "")

    span: dict[str, list[str]] = {}
    session_days: dict[str, set[str]] = defaultdict(set)
    days: set[str] = set()
    for r in enacted:
        d = wareki(r["付託日_衆"]) if r["種別"] == "閣法" and r["回次"] == r["提出回次"] else ""
        if d:
            days.add(d)
            session_days[r["提出回次"]].add(d)
            s = span.setdefault(r["提出回次"], [d, d])
            s[0], s[1] = min(s[0], d), max(s[1], d)
    by_day = {d: serving(d) for d in days}
    by_session: dict[str, list[tuple[str, str]]] = {}
    by_referral: dict[str, list[tuple[str, str]]] = {}
    for session, (first, last) in span.items():
        if pm_of(by_day[first]) and pm_of(by_day[first]) == pm_of(by_day[last]):
            by_session[session] = members(by_day[first], set(by_day[last]))
        else:
            # 会期中に総理大臣が替わる回次：交代より前（最初の付託日と同じ総理大臣）に付託された法律の付託日だけ
            for d in session_days[session]:
                if pm_of(by_day[d]) and pm_of(by_day[d]) == pm_of(by_day[first]):
                    by_referral[d] = members(by_day[d], set(by_day[d]))
    return {"session": by_session, "day": by_referral}


def build() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ids: dict[str, set[str]] = defaultdict(set)
    for p in _read(PERSONS):
        if p["人物ID"]:
            for name in [p["氏名"], *filter(None, p.get("別表記", "").split(";"))]:
                ids[canonical(name)].add(p["人物ID"])

    def person(name: str) -> tuple[str, str]:
        found = ids.get(canonical(name), set())
        if len(found) > 1:
            return "", UNRESOLVED
        return (next(iter(found)) if found else canonical(name)), ""

    enacted = {f"{r['種別']}-{r['提出回次']}-{r['番号']}": r for r in _read(ENACTED)}
    by_day: dict[str, list[dict[str, str]]] = defaultdict(list)
    for v in _read(VOTES_INDEX):
        by_day[v["投票日"]].append(v)
    cabinet_of = cabinets(list(enacted.values()), _read(CABINET))

    names = {(m["回次"], m["議員ID"]): m["議員名"] for m in _read(MEMBERS)}
    rows: list[dict[str, str]] = []
    votes: list[dict[str, str]] = []
    wanted: dict[str, dict[str, str]] = {}
    for p in eligible():
        b = enacted.get(p["id"])
        if not b or not b["経過URL"].startswith("https://www.shugiin.go.jp/"):
            continue
        day = wareki(b["議決日_参"])
        vote = pick_vote(b["題名"], by_day.get(day, [])) if day else None
        if not vote:
            continue  # 参議院の個人別の賛否が無い法律は足さない
        base = {"法律ID": p["id"], "題名": b["題名"], "系統A": "", "系統B": "", "立場の根拠": ""}
        kind = b["種別"]
        proposers: list[tuple[str, str, str]] = []  # 氏名・肩書・立場区分
        if kind == "閣法":
            # 閣法は内閣の提出。総理大臣1人に付けず、会期を通して在任した閣僚の全員に付ける。
            # 総理大臣が会期中に替わる回次は、付託日が交代より前の法律だけ付託日に在任した閣僚に付け、交代より後の法律は付けない。
            referred = wareki(b["付託日_衆"]) if b["回次"] == b["提出回次"] else ""
            cabinet = cabinet_of["session"].get(b["提出回次"]) or cabinet_of["day"].get(referred, [])
            proposers = [(name, f"{role}（閣議決定の長）" if role.startswith(PRIME_MINISTER) else f"{role}（閣議決定に関わった閣僚）",
                          "prime_minister" if role.startswith(PRIME_MINISTER) else "minister_or_party_exec") for name, role in cabinet]
        elif not COMMITTEE.search(norm(b["提出者"].split("外")[0])):
            if b["提出者一覧"]:
                proposers = [(norm(n), "提出者", "other") for n in re.split(r"[;；、,]", b["提出者一覧"]) if norm(n)]
            elif b["提出者"] and "外" not in b["提出者"]:
                proposers = [(norm(b["提出者"]), "提出者", "other")]
        if not proposers and kind != "閣法":
            continue  # 提出者が決まらない法律（名前の分からない「外N名」・委員会提出）は足さない。交代より後に付託された閣法は閣僚を付けない（未配分）が、参議院の賛否の行は残す
        # 院は議案の種別で決まる提出者だけに書く。閣僚は参議院議員や民間人もいるので空にする（総理大臣だけは衆議院議員の慣行だが、名簿に院の列が無いので書かない）。
        house = "" if kind == "閣法" else "参議院" if kind == "参法" else "衆議院"
        for name, title, position in proposers:
            pid, why = person(name)
            rows.append({**base, "氏名": name, "氏名_原表記": name, "院": house, "行動": "decide", "当時の肩書": title, "立場区分": position,
                         "日付": wareki(b["付託日_衆"]) or day, "証拠URL": b["経過URL"], "参院本会議の賛否": "",
                         "算入": "いいえ" if why else "はい", "除外理由": why, "人物ID": pid})
        votes.append({"法律ID": p["id"], "投票ID": vote["投票ID"], "日付": vote["投票日"], "賛成": vote["集計_賛成"], "反対": vote["集計_反対"], "URL": vote["出典URL"]})
        wanted[vote["投票ID"]] = {**base, "日付": vote["投票日"], "証拠URL": vote["出典URL"]}
    sessions = {v.split("-")[0] for v in wanted}
    for session in sorted(sessions):
        path = BALLOTS / f"ballots_{session}.csv"
        for r in _read(path) if path.exists() else []:
            if r["投票ID"] not in wanted or r["賛否"] != "Y":
                continue
            name = names.get((session, r["議員ID"]))
            if not name:
                raise ValueError(f"議員名がありません: {r['投票ID']} 議員ID={r['議員ID']}")
            pid, why = person(name)
            rows.append({**wanted[r["投票ID"]], "氏名": name, "氏名_原表記": name, "院": "参議院", "行動": "vote", "当時の肩書": "", "立場区分": "other",
                         "参院本会議の賛否": "Y", "算入": "いいえ" if why else "はい", "除外理由": why, "人物ID": pid})
    built = {v["法律ID"] for v in votes}
    for q in _read(QUESTIONS) if QUESTIONS.exists() else []:
        if q["法律ID"] not in built:
            continue
        pid, why = person(q["氏名"])
        rows.append({**q, "算入": "いいえ" if why else q["算入"], "除外理由": why or q["除外理由"], "人物ID": pid})
    rows.sort(key=lambda r: (r["法律ID"], r["行動"], r["氏名"]))
    votes.sort(key=lambda r: r["法律ID"])
    return rows, votes


def main() -> int:
    rows, votes = build()
    _write(OUT, HEADER, rows)
    _write(OUT_VOTES, VOTES_HEADER, votes)
    print(f"自動の関与 {len(rows)}行・法律 {len(votes)}本（提出 {sum(r['行動'] == 'decide' for r in rows)}・参議院の賛成 {sum(r['行動'] == 'vote' for r in rows)}・質疑 {sum(r['行動'] == 'question' for r in rows)}・同姓同名で外した {sum(r['除外理由'] == UNRESOLVED for r in rows)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
