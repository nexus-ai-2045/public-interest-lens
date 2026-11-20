#!/usr/bin/env python3
"""議員を氏名の文字列ではなく、安定した人物IDで分けるための台帳（data/derived/person-ids/）を作る。

入力（すべてリポジトリ内）
- 現職の名簿 data/acquired/diet-roster/current.csv（院・氏名・読み・会派・選挙区）
- 同じ人の表記の対応表 data/acquired/diet-roster/same-person.csv（一次資料で確かめたものだけ）
- 元職の名簿 data/acquired/diet-roster/historical.csv（会議録の発言者から確かめた人。scripts/fetch_roster_kokkai.py）
- 歴代の大臣・副大臣・政務官 data/acquired/office-holders/cabinet.csv
- 関与の一覧 data/derived/allocation-v1/involvements.csv（氏名・院）

人物IDの決め方
- 通常は canonical(氏名)：空白と敬称を除き、同一人物の字体ゆれ（髙→高 など）だけを寄せた文字列。
- 同じ時点の名簿に同じ canonical が複数いれば、同時に両院の議員にはなれないので必ず別人として分け、「鬼木誠（衆・福岡2）」のように院と選挙区を付ける（読み・会派が同じでも寄せない）。
- 人物IDは名簿のスナップショットから独立させる。既存の persons.csv を読み、一度付けた人物IDは変えない・消さない。
  一度分けた同姓同名は、片方が名簿から消えても分けたまま残す（院で決まらない行は決めきれない扱い）。新しい人だけを足す。
- 斉藤・斎藤・齋藤・齊藤のように字が違えば別人の表記は寄せない（寄せるのは下の表に理由のある字体だけ）。
- 人物への結びは link_person（app 側は person-id.ts の linkPerson）だけが行う。キーは氏名と在任期間で、在任に院があれば院も見る。
  その日付に在任している人が1人ならその人。在任の外は誰にも結ばず理由つきで未結合。候補が2人以上で1人に決まらなければ、並びの先頭には寄せず未結合。
  台帳の「今の院」だけでは決めない（院を移った人がいる。関与の行の院は発言した会議の院で、所属院ではない）。
  在任が分からないときは氏名が1人でも結ばない（未結合）。院を指定したときは、その院の在任がある人だけに結ぶ。
  明示の対応表 overrides.csv（法律ID・証拠URL・人物ID・根拠URL）は、その人がその日付に在任しているときだけ結ぶ（在任の記録が無ければ従来どおり結ぶ）。
  内閣名簿は院を持たないので、分けた名前には役職を付けない。
- 在任の列（在任の院・在任開始・在任終了・在任の出典）は名簿から作る。値は手で書かない。
  参議院の会期は data/acquired/sangiin-votes/members.csv の回次と votes_index.csv の投票日。連続する回次は1つの在任。
  この在任は、台帳の今の院が衆議院の人には付けない（氏名が同じだけの別院の人に参議院の期間を載せない）。
  参議院の任期満了は current.csv。任期は6年で、開始は満了日の6年前の翌日。院が一致する人だけに付ける。
  閣僚の就任日・退任日は cabinet.csv。院は名簿に無いので在任の院は空。院を指定した結びには使わない。

出力：persons.csv（人物ID,氏名,読み,院,選挙区,別表記,在任の院,在任開始,在任終了,在任の出典）と、決めきれない名前の一覧 undecided.csv。
--annotate-involvements を付けると、関与の一覧に人物ID列を足し直し、役職の照合も canonical で更新する（作り直しの入口 rebuild_public.py が付ける）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.allocation_involvements import normalize_name  # noqa: E402

ROSTER = ROOT / "data" / "acquired" / "diet-roster" / "current.csv"
HISTORICAL = ROOT / "data" / "acquired" / "diet-roster" / "historical.csv"
SAME_PERSON = ROOT / "data" / "acquired" / "diet-roster" / "same-person.csv"
CABINET = ROOT / "data" / "acquired" / "office-holders" / "cabinet.csv"
INVOLVEMENTS = ROOT / "data" / "derived" / "allocation-v1" / "involvements.csv"
EXPOSURE = ROOT / "data" / "derived" / "exposure-v1" / "exposure-ranking.json"
SANGIIN_MEMBERS = ROOT / "data" / "acquired" / "sangiin-votes" / "members.csv"
SANGIIN_VOTES = ROOT / "data" / "acquired" / "sangiin-votes" / "votes_index.csv"
OUT_DIR = ROOT / "data" / "derived" / "person-ids"
OVERRIDES = OUT_DIR / "overrides.csv"
OVERRIDES_HEADER = ["法律ID", "証拠URL", "人物ID", "根拠URL"]
SANGIIN_VOTE_URL = "https://www.sangiin.go.jp/"

# 同一人物の字体ゆれだけを寄せる表。実データで、同じ人が出典ごとに違う字で書かれていたものに限る。
# 斉・斎・齋・齊のように、字が違えば別の姓として登録されている表記や、濱・邊のように実例で確かめていないものは入れない。
VARIANTS = {
    "髙": "高",  # 首相官邸の名簿は旧字の髙、国会の名簿・会議録は高（髙鳥修一、髙階恵美子 など）
    "﨑": "崎",  # 官邸は﨑（U+FA11）、国会は崎（磯﨑仁彦、尾﨑正直 など）
    "德": "徳",  # 官邸は旧字の德、国会は徳（田所嘉德、田中和德 など）
    "濵": "浜",  # 官邸は濵、国会は浜（濵地雅一）
    "澤": "沢",  # 官邸の名簿の中でも澤と沢が混在する（柳澤伯夫）
}
HOUSE_SHORT = {"衆議院": "衆", "参議院": "参"}
UNRESOLVED = "同姓同名で人物を決められない"
OUTSIDE_TERM = "未結合：在任期間の外（その日付に在任している人がいない）"
OUTSIDE_HOUSE = "未結合：その日付の在任は別の院で、この院には結べない"
AMBIGUOUS = "未結合：候補が2人以上あり、在任期間で1人に決められない"
NOT_IN_LEDGER = "未結合：人物台帳に無い"
NO_TERM = "未結合：在任期間が分からない"
SOURCE_SESSION = "data/acquired/sangiin-votes/members.csv の回次と data/acquired/sangiin-votes/votes_index.csv の投票日（連続する回次は1つの在任）"
SOURCE_STATUTORY = "data/acquired/diet-roster/current.csv の任期満了（参議院は6年、開始は満了日の6年前の翌日）"
SOURCE_CABINET = "data/acquired/office-holders/cabinet.csv の就任日_西暦と退任日_西暦（閣僚の在任。院は名簿に無い）"
WAREKI_TERM = re.compile(r"(令和|平成|昭和)(\d+|元)年(\d+)月(\d+)日")
WAREKI_EPOCH = {"令和": 2018, "平成": 1988, "昭和": 1925}
TERM_FIELDS = ["在任の院", "在任開始", "在任終了", "在任の出典"]
ALIAS_SPLIT = re.compile(r"[;／|、,/]")


# 内閣名簿の氏名の末尾に付く脚注の記号（小川 平二* など）。人名の一部ではない。
FOOTNOTE_MARKS = re.compile(r"[*※†‡]+$")


def clean_name(name: str) -> str:
    """normalize_name に、末尾の脚注記号を除く（藤村修* → 藤村修）。字体の置き換えはしない。"""
    return normalize_name(FOOTNOTE_MARKS.sub("", normalize_name(name)))


# 字体だけが違う同じ字の組（斎・齋・齊・斉 など）。canonical には入れない（別の姓の登録もあるため）が、
# 元職の名簿を足すとき「読みが同じで、字体だけが違う」人を同じ人の表記として結ぶ根拠にする。
GLYPH_GROUPS = ["斎齋齊斉", "辺邊邉", "高髙", "崎﨑嵜", "沢澤", "浜濱濵", "島嶋", "広廣", "桜櫻", "竜龍", "真眞", "国國", "関關", "徳德", "渕淵"]
GLYPH = {c: g[0] for g in GLYPH_GROUPS for c in g}


def glyph_equal(a: str, b: str) -> bool:
    return len(a) == len(b) and all(GLYPH.get(x, x) == GLYPH.get(y, y) for x, y in zip(a, b))


def canonical(name: str) -> str:
    """normalize_name と同じ正規化（NFKC・空白・敬称）に、脚注記号の除去と同一人物の字体ゆれの寄せを足す。"""
    return "".join(VARIANTS.get(c, c) for c in clean_name(name))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class OfficeTerm:
    """在任期間。start と end は YYYY-MM-DD。end が空なら start 以降は在任中。端の日は在任に含む。
    house が空でなければ、関与側の院と一致するときだけその在任を使う。"""

    start: str
    end: str = ""
    house: str = ""


@dataclass
class Person:
    id: str
    name: str
    reading: str = ""
    house: str = ""
    district: str = ""
    party: str = ""
    aliases: set[str] = field(default_factory=set)
    terms: list[OfficeTerm] = field(default_factory=list)


def _dedupe(candidates: list[Person]) -> list[Person]:
    out: list[Person] = []
    seen: set[str] = set()
    for person in candidates:
        if person.id in seen:
            continue
        seen.add(person.id)
        out.append(person)
    return out


def _term_matches(term: OfficeTerm, day: str, house: str, *, use_house: bool) -> bool:
    if not term.start or not day or day < term.start:
        return False
    if term.end and day > term.end:
        return False
    if use_house and house and term.house and term.house != house:
        return False
    return True


def _covers(term: OfficeTerm, on: str, house: str) -> bool:
    """日付があればその日が期間に入り、院があれば在任の院が一致する。院が空の在任は、院を指定した結びには使わない。"""
    if on and (not term.start or on < term.start or (term.end and on > term.end)):
        return False
    if house and term.house != house:
        return False
    return True


def link_person(candidates: list[Person], *, on: str = "", house: str = "") -> tuple[str, str]:
    """氏名で集めた候補を、在任期間（院を指定したときはその院の在任）で1人に決める。

    戻り値は (人物ID, 理由)。理由が空なら結んだ。人物IDが空なら未結合。
    候補が空なら ("", "")。台帳に無い名前を人物IDにするかは呼び側が決める。
    候補が2人以上で1人に決まらないときは、並びの先頭を採らない。
    在任が無い人は氏名が1人でも結ばない。在任の無い候補が混ざるときは、在任のある人にも寄せない。
    日付も院も無ければ在任と照合できないので結ばない。台帳の「今の院」だけでは決めない。
    """
    people = _dedupe(candidates)
    if not people:
        return "", ""
    if not on and not house:
        return ("", NO_TERM) if len(people) == 1 else ("", UNRESOLVED)
    if not any(person.terms for person in people):
        return ("", NO_TERM) if len(people) == 1 else ("", UNRESOLVED)
    if any(not person.terms for person in people):
        return "", AMBIGUOUS
    hits = [person for person in people if any(_covers(term, on, house) for term in person.terms)]
    if len(hits) == 1:
        return hits[0].id, ""
    if len(hits) > 1:
        return "", AMBIGUOUS
    if house and any(_covers(term, on, "") and term.house and term.house != house for person in people for term in person.terms):
        return "", OUTSIDE_HOUSE
    if on:
        return "", OUTSIDE_TERM
    return ("", NO_TERM) if len(people) == 1 else ("", UNRESOLVED)


def matching_people(rows: list[dict], name: str) -> list[Person]:
    """台帳の行のうち、氏名か別表記が canonical で一致する人。在任開始があれば在任期間を付ける。"""
    canon = canonical(name)
    out: list[Person] = []
    seen: set[str] = set()
    for row in rows:
        pid = (row.get("人物ID") or "").strip()
        if not pid or pid in seen:
            continue
        names = [row.get("氏名") or "", *ALIAS_SPLIT.split(row.get("別表記") or "")]
        if canon not in {canonical(item) for item in names if item.strip()}:
            continue
        seen.add(pid)
        out.append(Person(pid, row.get("氏名") or "", row.get("読み") or "", row.get("院") or "", row.get("選挙区") or "", terms=_terms_of(row)))
    return out


def resolve_person(rows: list[dict], name: str, *, on: str = "", house: str = "", missing: str = "canonical") -> tuple[str, str]:
    """台帳の行から人物を結ぶ入口。関与・提出者・政治資金・交付金はここを通す。

    missing='canonical' は台帳に無い名前を、寄せた氏名の人物IDにする（関与の一覧）。
    missing='blank' は結ばず、理由を未結合にする（提出者・政治資金・交付金）。
    """
    people = matching_people(rows, name)
    if people:
        return link_person(people, on=on, house=house)
    if missing == "canonical":
        return canonical(name), ""
    if missing == "blank":
        return "", NOT_IN_LEDGER
    raise ValueError(f"missing の値が違います: {missing}")


def _is_link_reason(text: str) -> bool:
    """人物の結びで付けた除外理由か。立場や賛否の理由は含めない。"""
    return text == UNRESOLVED or text.startswith("未結合：")


def _override_ok(person: Person, on: str, house: str) -> bool:
    """対応表は、その人がその日付に在任しているときだけ使う。在任の記録が無ければ日付では否定しない。"""
    if not on or not person.terms:
        return True
    return any(_term_matches(term, on, house, use_house=True) for term in person.terms)


class Ledger:
    """人物の台帳。同じ canonical が複数いるときは link_person（在任期間）で決め、決まらなければ未結合。"""

    def __init__(self) -> None:
        self.persons: dict[str, Person] = {}
        self.by_canonical: dict[str, list[Person]] = defaultdict(list)
        self.undecided: list[dict] = []
        self.overrides: dict[tuple[str, str], str] = {}

    def is_split(self, canon: str) -> bool:
        return len(self.by_canonical.get(canon, [])) > 1

    def resolve(self, name: str, law: str = "", url: str = "", sangiin_vote: bool = False, *, on: str = "", house: str = "") -> tuple[str, str]:
        """(人物ID, 決められない理由)。結び方は link_person。台帳に無い名前は canonical をそのまま人物IDにする。
        sangiin_vote は互換のために受ける。今の院や投票の種別では決めない（在任期間に院があるときだけ院を見る）。"""
        del sangiin_vote
        people = _dedupe(self.by_canonical.get(canonical(name), []))
        if not people:
            return canonical(name), ""
        pid, why = link_person(people, on=on, house=house)
        if pid:
            return pid, ""
        chosen = self.overrides.get((law, url)) if law or url else None
        target = self.persons.get(chosen) if chosen else None
        if target is not None and any(person.id == target.id for person in people) and _override_ok(target, on, house):
            return target.id, ""
        return "", why or UNRESOLVED

    def display(self, pid: str, fallback: str = "") -> str:
        p = self.persons.get(pid)
        return p.name if p and p.name else fallback or pid


def _add(ledger: Ledger, person: Person) -> None:
    if not person.id.strip():
        return  # 氏名の空の行（内閣名簿の空欄など）は人物ではない。台帳に全列空の行を作らない
    ledger.persons[person.id] = person
    ledger.by_canonical[canonical(person.name)].append(person)


def load_overrides(path: Path | None) -> dict[tuple[str, str], str]:
    """(法律ID, 証拠URL) → 人物ID。根拠URL（所属を示す一次資料）が https でなければ誤りとして止める。"""
    if path is None or not path.exists():
        return {}
    out: dict[tuple[str, str], str] = {}
    for r in read_csv(path):
        if not r["法律ID"] or not r["証拠URL"] or not r["人物ID"]:
            raise ValueError(f"overrides.csv に空の列があります: {r}")
        if not r["根拠URL"].startswith("https://"):
            raise ValueError(f"overrides.csv の根拠URLが https ではありません: {r['人物ID']}")
        if out.setdefault((r["法律ID"], r["証拠URL"]), r["人物ID"]) != r["人物ID"]:
            raise ValueError(f"overrides.csv で同じ行に別の人物IDがあります: {r['法律ID']} {r['証拠URL']}")
    return out


def _split_term_field(row: dict, key: str) -> list[str]:
    return [part.strip() for part in (row.get(key) or "").split(";")]


def _terms_of(row: dict) -> list[OfficeTerm]:
    """在任開始がある行だけ在任期間にする。複数は `;` で揃えて入っている。列が無い台帳は空。"""
    starts = _split_term_field(row, "在任開始")
    ends = _split_term_field(row, "在任終了")
    houses = _split_term_field(row, "在任の院")
    terms: list[OfficeTerm] = []
    for index, start in enumerate(starts):
        if not start:
            continue
        terms.append(OfficeTerm(start, ends[index] if index < len(ends) else "", houses[index] if index < len(houses) else ""))
    return terms


def load_previous(ledger: Ledger, rows: list[dict]) -> None:
    """前に作った persons.csv の人物を、人物IDも院も選挙区もそのまま台帳に入れる（別表記は作り直す）。"""
    for r in rows:
        if FOOTNOTE_MARKS.search(r["人物ID"]):
            continue  # 脚注記号を除く前に付いた人物ID（小川平二* など）。人物ではなく表記の取りこぼしなので引き継がない
        _add(ledger, Person(r["人物ID"], r["氏名"], r["読み"], r["院"], r["選挙区"], terms=_terms_of(r)))


def _qualified(canon: str, r: dict) -> str:
    return f"{canon}（{HOUSE_SHORT.get(r['院'], r['院'])}・{r['選挙区']}）"


def load_roster(ledger: Ledger, rows: list[dict]) -> None:
    """名簿の人物を台帳に足す。すでにいる人（前の台帳）は人物IDを変えずに属性だけ更新し、名簿から消えた人も残す。
    新しく同じ canonical が並ぶときは、新しい方に院と選挙区を付けた人物IDを付ける（前からいる人のIDは変えない）。
    台帳が空のとき同じ canonical が複数なら、院が違い読みも会派も同じ2人だけ同一人物とみなして1人にし、
    それ以外（読みか会派が違う、同じ院で選挙区が違う）は全員に院と選挙区を付けて分ける。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[canonical(r["氏名"])].append(r)
    for canon, rs in sorted(groups.items()):
        existing = list(ledger.by_canonical.get(canon, []))
        claimed: set[str] = set()
        pending: list[dict] = []

        def take(r: dict, p: Person) -> None:
            claimed.add(p.id)
            p.name, p.reading, p.house, p.district, p.party = clean_name(r["氏名"]), r["読み"], r["院"], r["選挙区"], r["会派"]

        # 院・選挙区・読みが同じ人 → 院と読みが同じ人の順に、前からいる人と結ぶ。名簿に載っていなかった人（読みの無い元職・歴代の人）とは
        # 氏名だけでは同じ人か決められないので結ばない（新しい方は院と選挙区付きのIDになり、元職の行は overrides で結ぶまで算入外）。
        # 院と選挙区が同じでも読みが違えば結ばない（同じ選挙区に入った同姓同名の後任を前の人に混ぜない）。
        rest = list(rs)
        for match in (
            lambda r, p: p.reading and p.house == r["院"] and p.district == r["選挙区"] and p.reading == r["読み"],
            lambda r, p: p.reading and p.house == r["院"] and p.reading == r["読み"],
        ):
            # 候補が1人に絞れ、その候補を求める名簿の行も1行だけのときに結ぶ（区割り変更や同名新人の加入で2人以上・2行以上が
            # 当てはまるときは、並び順で決めずに後段の未決定へ送る）。
            hits = [[p for p in existing if p.id not in claimed and match(r, p)] for r in rest]
            wanted = Counter(h[0].id for h in hits if len(h) == 1)
            left = []
            for r, h in zip(rest, hits):
                if len(h) == 1 and wanted[h[0].id] == 1:
                    take(r, h[0])
                else:
                    left.append(r)
            rest = left
        pending = rest
        if not pending:
            continue
        if existing:
            # 院を移った人：前の台帳に同じ氏名が1人だけで読みが同じなら、IDを引き継いで院・選挙区を更新する。
            if len(existing) == 1 and existing[0].reading and existing[0].id not in claimed:
                same = [r for r in pending if r["読み"] == existing[0].reading]
                moved = same[0] if len(same) == 1 else None  # 読みの同じ行が2行以上なら、どちらが移った人か決めない
                if len(same) > 1:
                    ledger.undecided.append({"氏名": canon, "区分": "名簿", "理由": f"前の台帳の1人に当たる名簿の行が{len(same)}行あり、どれが同じ人か決められない（新しいIDで分け、前の人の行は overrides で結ぶまで算入外）", "件数": len(same)})
                if moved is not None:
                    take(moved, existing[0])
                    pending = [r for r in pending if r is not moved]
            for r in pending:
                if len(existing) > 1 and r["読み"] and all(p.reading and p.reading != r["読み"] for p in existing):
                    # 前の台帳の同じ氏名の誰とも読みが違えば、前の人ではなく新しい人（院と選挙区付きのIDで足す）。
                    _new(ledger, canon, r, _qualified(canon, r))
                elif len(existing) > 1:
                    # 前の台帳に同じ氏名が複数いて、名簿の1人をどれとも結べない。新しいIDは作らず、overrides で結ぶまで決めない。
                    ledger.undecided.append({"氏名": canon, "区分": "名簿", "理由": f"前の台帳に同じ氏名が{len(existing)}人いて、名簿の{r['院']}・{r['選挙区']}をどれとも結べない（overrides.csv で結ぶまで算入外）", "件数": 1})
                else:
                    _new(ledger, canon, r, _qualified(canon, r))
        elif len(pending) == 1:
            _new(ledger, canon, pending[0], canon)
        else:
            # 同じ時点の名簿に同じ氏名が複数いれば別人（同時に両院の議員にはなれない）。読み・会派が同じでも寄せない。
            if len({r["院"] for r in pending}) < len(pending):
                ledger.undecided.append({"氏名": canon, "区分": "名簿", "理由": "同じ院に同じ表記が複数いる（選挙区を付けて分けた）", "件数": len(pending)})
            for r in pending:
                _new(ledger, canon, r, _qualified(canon, r))


def _new(ledger: Ledger, canon: str, r: dict, pid: str) -> None:
    if pid in ledger.persons:
        same = ledger.persons[pid]
        if not r["読み"] or same.reading == r["読み"]:  # 院・選挙区・読みも同じ完全な重複は1人にする
            return
        # 比例区など、院と選挙区が同じで読みが違う別人。読みを足して重ならないIDにする。
        reading = re.sub(r"\s+", "", r["読み"])
        pid = f"{pid[:-1]}・{reading}）"
        if pid in ledger.persons:
            return
    _add(ledger, Person(pid, clean_name(r["氏名"]), r["読み"], r["院"], r["選挙区"], r["会派"]))


def build_ledger(roster: list[dict], cabinet: list[dict] | None = None, involvements: list[dict] | None = None,
                 previous: list[dict] | None = None, overrides: dict[tuple[str, str], str] | None = None,
                 historical: list[dict] | None = None,
                 same: list[dict] | None = None) -> Ledger:
    """名簿の人物に、内閣名簿と関与の一覧にしか出ない人物（元職など）を足す。別表記は同じ人物IDに集める。
    previous（前の persons.csv）の人物は、人物IDを変えずに引き継ぐ。歴代の人（今の名簿にいない人）も前の台帳で残る。
    台帳に残さないと、のちに同じ氏名の人が名簿に載ったとき、歴代の人の投票・提出が新しい人へ移ってしまう。"""
    ledger = Ledger()
    ledger.overrides = overrides or {}
    load_previous(ledger, previous or [])
    load_roster(ledger, roster)
    spellings: dict[str, Counter] = defaultdict(Counter)
    houses: dict[str, Counter] = defaultdict(Counter)
    for r in involvements or []:
        n = clean_name(r["氏名"])
        spellings[canonical(n)][n] += 10  # 関与の一覧の表記を優先して、表示の氏名にする
        if r.get("院"):
            houses[canonical(n)][r["院"]] += 1
    for r in cabinet or []:
        n = clean_name(r["氏名"])
        spellings[canonical(n)][n] += 1
    for canon, counts in sorted(spellings.items()):
        if canon in ledger.by_canonical:
            targets = ledger.by_canonical[canon]
        else:
            top = sorted(counts, key=lambda s: (-counts[s], s))[0]
            hs = houses[canon]
            p = Person(canon, top, house=next(iter(hs)) if len(hs) == 1 else "")
            _add(ledger, p)
            targets = [p]
        for p in targets:
            p.aliases |= {s for s in counts if s != p.name}
    # 元職の名簿（会議録の発言者から確かめた人。scripts/fetch_roster_kokkai.py）。台帳に同じ氏名がいれば結ばない（同姓同名を混ぜない）。
    # 読みが複数ある（同姓同名の疑い）人は台帳に入れず、一覧に残す。
    for h in historical or []:
        canon = canonical(h["氏名"])
        if h.get("同姓同名の疑い"):
            ledger.undecided.append({"氏名": canon, "区分": "元職の名簿", "理由": "会議録の発言者の読みが複数ある（同姓同名の疑い）ので台帳に入れない", "件数": 1})
        elif canon not in ledger.by_canonical:
            reading = re.sub(r"\s+", "", h["読み"])
            twins = [q for q in ledger.persons.values()
                     if q.reading and re.sub(r"\s+", "", q.reading) == reading and q.name != clean_name(h["氏名"]) and glyph_equal(canonical(q.name), canon)]
            if len(twins) == 1:  # 読みが同じで字体だけ違う：同じ人の別表記（斎藤／齋藤 など）
                twins[0].aliases.add(clean_name(h["氏名"]))
                ledger.by_canonical[canon].append(twins[0])
                continue
            houses = h["院"].split("・")
            _add(ledger, Person(canon, clean_name(h["氏名"]), h["読み"], houses[0] if len(houses) == 1 else "", "", h["会派（最多）"]))
    # 一次資料（根拠URL）で同じ人と確かめた表記を、先の人物IDの別表記に寄せる（same-person.csv）。別の人物IDとして残っていれば台帳から外す。
    for r in same or []:
        keep, other = ledger.persons.get(r["人物ID"]), clean_name(r["同じ人の別表記"])
        if not keep or not r["根拠URL"].startswith("https://"):
            continue
        for q in list(ledger.by_canonical.get(canonical(other), [])):
            if q is not keep:
                ledger.persons.pop(q.id, None)
        ledger.by_canonical[canonical(other)] = [keep]
        keep.aliases.add(other)
    # 分けた名前が、院の分からない関与の行に出ていないかを一覧に残す。
    for canon, ps in sorted(ledger.by_canonical.items()):
        if len(ps) < 2:
            continue
        cab = sum(canonical(r["氏名"]) == canon for r in cabinet or [])
        if cab:
            ledger.undecided.append({"氏名": canon, "区分": "内閣名簿", "理由": "同姓同名を院で分けた名前。内閣名簿は院を持たないので役職を付けない", "件数": cab})
        n = sum(canonical(r["氏名"]) == canon and ledger.resolve(r["氏名"], r["法律ID"], r["証拠URL"], _is_sangiin_vote(r))[1] for r in involvements or [])
        if n:
            ledger.undecided.append({"氏名": canon, "区分": "関与", "理由": "一次資料で所属が決まらない（overrides.csv に載せるまで算入外）", "件数": n})
    return ledger


def _is_sangiin_vote(r: dict) -> bool:
    """参議院の押しボタン投票の記録（議員ID→名前）から作った行。参議院議員と確定できる。"""
    return r.get("行動") == "vote" and r.get("証拠URL", "").startswith(SANGIIN_VOTE_URL)


def unify_names(rows: list[dict], ledger: Ledger) -> None:
    """同じ人物IDの行は同じ氏名にそろえる。名簿の人物は名簿の表記、それ以外は行でいちばん多い表記（同数なら canonical に近い方）。"""
    count: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.get("人物ID"):
            count[r["人物ID"]][r["氏名"]] += 1
    for r in rows:
        pid = r.get("人物ID")
        if not pid:
            continue
        p = ledger.persons.get(pid)
        if p and p.reading:  # 名簿の人物（読みがある）
            r["氏名"] = p.name
        else:
            c = count[pid]
            r["氏名"] = sorted(c, key=lambda s: (-c[s], s != pid, s))[0]


def wareki_iso(text: str) -> str:
    """任期満了の和暦（令和10年7月25日）を YYYY-MM-DD にする。日付でなければ空。"""
    match = WAREKI_TERM.fullmatch(re.sub(r"\s+", "", text or ""))
    if not match:
        return ""
    year = WAREKI_EPOCH[match.group(1)] + (1 if match.group(2) == "元" else int(match.group(2)))
    return f"{year:04d}-{int(match.group(3)):02d}-{int(match.group(4)):02d}"


def _shift_years(iso: str, years: int) -> date:
    year, month, day = (int(part) for part in iso.split("-"))
    try:
        return date(year + years, month, day)
    except ValueError:
        return date(year + years, month, day - 1)


def _merge_spans(spans: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """重なる、または隣り合う期間を1つにする。終了が空なら、その日以降はずっと在任。"""
    merged: list[list[str]] = []
    for start, end in sorted(spans, key=lambda item: (item[0], item[1] or "9999-99-99")):
        if not start:
            continue
        if not merged:
            merged.append([start, end])
            continue
        previous = merged[-1][1]
        touches = previous == "" or start <= (date.fromisoformat(previous) + timedelta(days=1)).isoformat()
        if touches:
            if previous == "" or end == "":
                merged[-1][1] = ""
            elif end > previous:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def sangiin_session_runs(members: list[dict], votes: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """議員名ごとに、投票のある回次の連続区間を1つの在任（最初の投票日〜最後の投票日）にする。"""
    span: dict[str, tuple[str, str]] = {}
    for vote in votes:
        session, day = vote.get("回次") or "", vote.get("投票日") or ""
        if not session or not day:
            continue
        start, end = span.get(session, (day, day))
        span[session] = (min(start, day), max(end, day))
    order = {session: index for index, session in enumerate(sorted(span, key=int))}
    by_name: dict[str, set[str]] = defaultdict(set)
    for member in members:
        session = member.get("回次") or ""
        if session in span and member.get("議員名"):
            by_name[canonical(member["議員名"])].add(session)
    runs: dict[str, list[tuple[str, str]]] = {}
    for name, sessions in by_name.items():
        ordered = sorted(sessions, key=lambda session: order[session])
        start = previous = ordered[0]
        built: list[tuple[str, str]] = []
        for session in ordered[1:]:
            if order[session] == order[previous] + 1:
                previous = session
                continue
            built.append((span[start][0], span[previous][1]))
            start = previous = session
        built.append((span[start][0], span[previous][1]))
        runs[name] = built
    return runs


def statutory_sangiin_terms(roster: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """現職名簿の任期満了から、参議院の6年（満了日の6年前の翌日〜満了日）を氏名ごとに作る。"""
    found: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in roster:
        if row.get("院") != "参議院":
            continue
        end = wareki_iso(row.get("任期満了") or "")
        if not end or not row.get("氏名"):
            continue
        start = (_shift_years(end, -6) + timedelta(days=1)).isoformat()
        found[canonical(row["氏名"])].append((start, end))
    return found


def cabinet_spans(cabinet: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """閣僚名簿の就任日から、退任日の前日まで。退任日が空なら、就任日以降は在任。退任日は含まない。"""
    raw: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in cabinet:
        start = (row.get("就任日_西暦") or "").strip()
        if not start or not row.get("氏名"):
            continue
        until = (row.get("退任日_西暦") or "").strip()
        if until:
            end = (date.fromisoformat(until) - timedelta(days=1)).isoformat()
            if end < start:
                continue
        else:
            end = ""
        raw[canonical(row["氏名"])].append((start, end))
    return {name: _merge_spans(spans) for name, spans in raw.items()}


def fill_term_columns(rows: list[dict], members: list[dict], votes: list[dict], roster: list[dict], cabinet: list[dict]) -> None:
    """人物の行に在任の列を足す。値は名簿から作り、氏名が同じだけの別院の人には参議院の在任を付けない。"""
    runs = sangiin_session_runs(members, votes)
    statutory = statutory_sangiin_terms(roster)
    offices = cabinet_spans(cabinet)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for key in TERM_FIELDS:
            row.setdefault(key, "")
        if row.get("人物ID"):
            grouped[canonical(row.get("氏名") or "")].append(row)
    packed: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for name, group in grouped.items():
        receivers = [row for row in group if (row.get("院") or "") != "衆議院"]
        if len(receivers) == 1:
            for start, end in runs.get(name, []):
                packed[receivers[0]["人物ID"]].append((start, end, "参議院", SOURCE_SESSION))
            for start, end in statutory.get(name, []):
                if (receivers[0].get("院") or "") == "参議院":
                    packed[receivers[0]["人物ID"]].append((start, end, "参議院", SOURCE_STATUTORY))
        if len(group) == 1:
            for start, end in offices.get(name, []):
                packed[group[0]["人物ID"]].append((start, end, "", SOURCE_CABINET))
    for row in rows:
        terms = sorted(set(packed.get(row.get("人物ID") or "", [])), key=lambda term: (term[0], term[1], term[2], term[3]))
        row["在任開始"] = ";".join(term[0] for term in terms)
        row["在任終了"] = ";".join(term[1] for term in terms)
        row["在任の院"] = ";".join(term[2] for term in terms)
        row["在任の出典"] = ";".join(term[3] for term in terms)


def apply_terms(ledger: Ledger, members: list[dict], votes: list[dict], roster: list[dict], cabinet: list[dict]) -> None:
    """台帳の人物に、名簿から作った在任を足す。すでに付いている在任は消さない。"""
    rows = [{"人物ID": person.id, "氏名": person.name, "院": person.house} for person in ledger.persons.values()]
    fill_term_columns(rows, members, votes, roster, cabinet)
    by_id = {row["人物ID"]: row for row in rows}
    for person in ledger.persons.values():
        seen = {(term.start, term.end, term.house) for term in person.terms}
        for term in _terms_of(by_id.get(person.id, {})):
            key = (term.start, term.end, term.house)
            if key not in seen:
                person.terms.append(term)
                seen.add(key)


def count_sangiin_house_links(rows: list[dict], members: list[dict]) -> tuple[int, int]:
    """参議院の議員名を院だけ指定して結んだとき、台帳の今の院が衆議院になる件数と、未結合の件数。氏名は返さない。"""
    ledger = Ledger()
    load_previous(ledger, rows)
    names = {canonical(row["議員名"]) for row in members if row.get("議員名")}
    cross = unlinked = 0
    for name in names:
        person_id, _why = ledger.resolve(name, house="参議院")
        person = ledger.persons.get(person_id)
        if person is not None and person.house == "衆議院":
            cross += 1
        if not person_id:
            unlinked += 1
    return cross, unlinked


PERSON_HEADER = ["人物ID", "氏名", "読み", "院", "選挙区", "別表記", *TERM_FIELDS]
UNDECIDED_HEADER = ["氏名", "区分", "理由", "件数"]


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--roster", type=Path, default=ROSTER)
    p.add_argument("--cabinet", type=Path, default=CABINET)
    p.add_argument("--involvements", type=Path, default=INVOLVEMENTS)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--overrides", type=Path, default=OVERRIDES, help="同姓同名の行を人物IDに結ぶ対応表（法律ID,証拠URL,人物ID,根拠URL）")
    p.add_argument("--previous", type=Path, help="前の persons.csv（既定は出力先の persons.csv）。付けた人物IDはここから引き継いで変えない")
    p.add_argument("--historical", type=Path, default=HISTORICAL, help="元職の名簿（会議録の発言者から確かめた人）")
    p.add_argument("--same-person", type=Path, default=SAME_PERSON, help="一次資料で同じ人と確かめた表記の対応表")
    p.add_argument("--annotate-involvements", action="store_true", help="関与の一覧に人物ID列を足し直し、役職を canonical で照合し直す")
    a = p.parse_args(argv)
    inv = read_csv(a.involvements) if a.involvements.exists() else []
    cabinet = read_csv(a.cabinet)
    previous = a.previous or a.out_dir / "persons.csv"
    ledger = build_ledger(read_csv(a.roster), cabinet, inv, read_csv(previous) if previous.exists() else None,
                          load_overrides(a.overrides),
                          read_csv(a.historical) if a.historical.exists() else None,
                          read_csv(a.same_person) if a.same_person.exists() else None)
    rows = [{"人物ID": q.id, "氏名": q.name, "読み": q.reading, "院": q.house, "選挙区": q.district, "別表記": "／".join(sorted(q.aliases))}
            for q in sorted(ledger.persons.values(), key=lambda q: q.id)]
    members = read_csv(SANGIIN_MEMBERS) if SANGIIN_MEMBERS.exists() else []
    votes = read_csv(SANGIIN_VOTES) if SANGIIN_VOTES.exists() else []
    fill_term_columns(rows, members, votes, read_csv(a.roster) if a.roster.exists() else [], cabinet)
    write_csv(a.out_dir / "persons.csv", PERSON_HEADER, rows)
    cross, unlinked = count_sangiin_house_links(rows, members)
    print(f"別院 {cross} 未結合 {unlinked}")
    # 人物ID は絶対に重ならない（重なったら別人を1人にしてしまう）。空の人物IDの行も作らない。
    assert len({r["人物ID"] for r in rows}) == len(rows)
    assert all(r["人物ID"].strip() for r in rows), "人物IDが空の行があります"
    undecided = list(ledger.undecided)
    if a.annotate_involvements and inv:
        from scripts import allocation_involvements as ai

        fixed, rows_out = ai.annotate(inv, ledger, ai.Cabinet(cabinet, canonical))
        ai.write_csv(a.involvements, ai.HEADER, rows_out)
        print(f"関与 {len(rows_out)} 行に人物IDを付けた（氏名・役職・算入を直した行 {fixed}）")
    write_csv(a.out_dir / "undecided.csv", UNDECIDED_HEADER, undecided)
    split = sorted({q.id for q in ledger.persons.values() if "（" in q.id})
    print(f"人物 {len(rows)} 人（名簿 {sum(bool(q.reading) for q in ledger.persons.values())}、分けた人物 {len(split)}）、決めきれない名前 {len(undecided)} 件")
    return 0


def ranked_people(exposure: Path = EXPOSURE, persons: Path | None = None) -> list[tuple[str, str]]:
    """曝露ランキング（exposure-ranking.json）で点がある（tier が null でない）人の (人物ID, 氏名)。氏名は人物台帳（persons.csv）で引く。
    国会での活動の取得・公開（scripts/fetch_kokkai_member_*.py・build_member_activity.py）の対象。台帳に無い人物IDは氏名を人物IDで代える。"""
    people = json.loads(exposure.read_text(encoding="utf-8"))["people"]
    names = {r["人物ID"]: r["氏名"] for r in read_csv(persons or OUT_DIR / "persons.csv")}
    return [(p["actorId"], names.get(p["actorId"], p["actorId"])) for p in people if p.get("tier") is not None]


if __name__ == "__main__":
    raise SystemExit(main())

