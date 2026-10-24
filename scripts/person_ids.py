#!/usr/bin/env python3
"""議員を氏名の文字列ではなく、安定した人物IDで分けるための台帳（data/derived/person-ids/）を作る。

入力（すべてリポジトリ内）
- 現職の名簿 data/acquired/diet-roster/current.csv（院・氏名・読み・会派・選挙区）
- 歴代の大臣・副大臣・政務官 data/acquired/office-holders/cabinet.csv
- 関与の一覧 data/derived/allocation-v1/involvements.csv（氏名・院）

人物IDの決め方
- 通常は canonical(氏名)：空白と敬称を除き、同一人物の字体ゆれ（髙→高 など）だけを寄せた文字列。
- 同じ時点の名簿に同じ canonical が複数いれば、同時に両院の議員にはなれないので必ず別人として分け、「鬼木誠（衆・福岡2）」のように院と選挙区を付ける（読み・会派が同じでも寄せない）。
- 人物IDは名簿のスナップショットから独立させる。既存の persons.csv を読み、一度付けた人物IDは変えない・消さない。
  一度分けた同姓同名は、片方が名簿から消えても分けたまま残す（院で決まらない行は決めきれない扱い）。新しい人だけを足す。
- 斉藤・斎藤・齋藤・齊藤のように字が違えば別人の表記は寄せない（寄せるのは下の表に理由のある字体だけ）。
- 方針：同姓同名の可能性がある名前は、一次資料で所属が決まる場合だけ人物IDに結び、それ以外は決めない（算入外）。
  関与の行の「院」は発言した会議の院で議員の所属院ではないので、解決には使わない。解決できるのは
  (1) 明示の対応表 overrides.csv（法律ID・証拠URL・人物ID・根拠URL）に載った行と、
  (2) 参議院の押しボタン投票の記録（議員ID→名前）から作った vote 行（参議院議員と確定できる）だけ。
  内閣名簿は院を持たないので、分けた名前には役職を付けない。

出力：persons.csv（人物ID,氏名,読み,院,選挙区,別表記）と、決めきれない名前の一覧 undecided.csv。
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.allocation_involvements import normalize_name  # noqa: E402

ROSTER = ROOT / "data" / "acquired" / "diet-roster" / "current.csv"
CABINET = ROOT / "data" / "acquired" / "office-holders" / "cabinet.csv"
INVOLVEMENTS = ROOT / "data" / "derived" / "allocation-v1" / "involvements.csv"
REFERENCE = ROOT / "app" / "public" / "distribution" / "members-reference.json"
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


# 内閣名簿の氏名の末尾に付く脚注の記号（小川 平二* など）。人名の一部ではない。
FOOTNOTE_MARKS = re.compile(r"[*※†‡]+$")


def clean_name(name: str) -> str:
    """normalize_name に、末尾の脚注記号を除く（藤村修* → 藤村修）。字体の置き換えはしない。"""
    return normalize_name(FOOTNOTE_MARKS.sub("", normalize_name(name)))


def canonical(name: str) -> str:
    """normalize_name と同じ正規化（NFKC・空白・敬称）に、脚注記号の除去と同一人物の字体ゆれの寄せを足す。"""
    return "".join(VARIANTS.get(c, c) for c in clean_name(name))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@dataclass
class Person:
    id: str
    name: str
    reading: str = ""
    house: str = ""
    district: str = ""
    party: str = ""
    aliases: set[str] = field(default_factory=set)


class Ledger:
    """人物の台帳。名簿で同じ canonical に複数いる名前（split）は、院で人物を決める。"""

    def __init__(self) -> None:
        self.persons: dict[str, Person] = {}
        self.by_canonical: dict[str, list[Person]] = defaultdict(list)
        self.undecided: list[dict] = []
        self.overrides: dict[tuple[str, str], str] = {}

    def is_split(self, canon: str) -> bool:
        return len(self.by_canonical.get(canon, [])) > 1

    def resolve(self, name: str, law: str = "", url: str = "", sangiin_vote: bool = False) -> tuple[str, str]:
        """(人物ID, 決められない理由)。台帳に無い名前は canonical をそのまま人物IDにする。
        同姓同名で分けた名前は、overrides に (法律ID, 証拠URL) がある行だけ決める（sangiin_vote は互換のために受けるが使わない）。
        行の院は発言した会議の院で所属院ではないので、ここでは使わない。"""
        canon = canonical(name)
        found = self.by_canonical.get(canon, [])
        if len(found) <= 1:
            return (found[0].id if found else canon), ""
        chosen = self.overrides.get((law, url))
        if chosen and any(p.id == chosen for p in found):
            return chosen, ""
        # 台帳の院は今の院だけで、所属の履歴は持たない（院を移った人がいる）。参議院の投票記録でも、今の院では決めない。
        return "", UNRESOLVED

    def display(self, pid: str, fallback: str = "") -> str:
        p = self.persons.get(pid)
        return p.name if p and p.name else fallback or pid


def _add(ledger: Ledger, person: Person) -> None:
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


def load_previous(ledger: Ledger, rows: list[dict]) -> None:
    """前に作った persons.csv の人物を、人物IDも院も選挙区もそのまま台帳に入れる（別表記は作り直す）。"""
    for r in rows:
        if FOOTNOTE_MARKS.search(r["人物ID"]):
            continue  # 脚注記号を除く前に付いた人物ID（小川平二* など）。人物ではなく表記の取りこぼしなので引き継がない
        _add(ledger, Person(r["人物ID"], r["氏名"], r["読み"], r["院"], r["選挙区"]))


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
                 reference: list[dict] | None = None) -> Ledger:
    """名簿の人物に、内閣名簿と関与の一覧にしか出ない人物（元職など）を足す。別表記は同じ人物IDに集める。
    previous（前の persons.csv）の人物は、人物IDを変えずに引き継ぐ。"""
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
    # 全議員の表（members-reference.json）にだけ出る歴代の人も台帳に残す。台帳に無いと、のちに同じ氏名の人が名簿に載ったとき、
    # 歴代の人の投票・提出が新しい人へ移ってしまう。参議院の投票記録に会派がある人は参議院、ほかは院を決めない。
    for m in reference or []:
        canon = canonical(m.get("name") or m["id"])
        if canon and canon not in ledger.by_canonical:
            _add(ledger, Person(canon, clean_name(m.get("name") or m["id"]), house="参議院" if m.get("lastSangiinParty") else ""))
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


PERSON_HEADER = ["人物ID", "氏名", "読み", "院", "選挙区", "別表記"]
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
    p.add_argument("--reference", type=Path, default=REFERENCE, help="前に作った全議員の表。歴代の人を台帳に残すために読む")
    p.add_argument("--annotate-involvements", action="store_true", help="関与の一覧に人物ID列を足し直し、役職を canonical で照合し直す")
    a = p.parse_args(argv)
    inv = read_csv(a.involvements) if a.involvements.exists() else []
    cabinet = read_csv(a.cabinet)
    previous = a.previous or a.out_dir / "persons.csv"
    ledger = build_ledger(read_csv(a.roster), cabinet, inv, read_csv(previous) if previous.exists() else None,
                          load_overrides(a.overrides),
                          json.loads(a.reference.read_text(encoding="utf-8"))["members"] if a.reference.exists() else None)
    rows = [{"人物ID": q.id, "氏名": q.name, "読み": q.reading, "院": q.house, "選挙区": q.district, "別表記": "／".join(sorted(q.aliases))}
            for q in sorted(ledger.persons.values(), key=lambda q: q.id)]
    write_csv(a.out_dir / "persons.csv", PERSON_HEADER, rows)
    # 人物ID は絶対に重ならない（重なったら別人を1人にしてしまう）。
    assert len({r["人物ID"] for r in rows}) == len(rows)
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


if __name__ == "__main__":
    raise SystemExit(main())
