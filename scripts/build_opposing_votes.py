"""議員ページで配る法律の、参議院本会議で反対した議員の一覧を作る（allocation-v1 の「反対した側」、設計決定0014）。

賛成した議員は関与の一覧（involvements.csv の行動 vote）に入っているが、反対した議員は入っていない。
反対票は「その法律を止めようとした行動」なので、法律の額の向きを逆にして配る（損失の法律に反対＝プラス、便益の法律に反対＝マイナス）。

入力（すべてリポジトリ内）：
  data/derived/allocation-v1/votes.csv           法律ID → 参議院の投票ID（votes-auto.csv も。scripts/build_auto_involvements.py）
  data/acquired/sangiin-votes/ballots/ballots_<回次>.csv  投票ID・議員ID・賛否（Y/N）
  data/acquired/sangiin-votes/members.csv         回次・議員ID → 議員名
  data/derived/person-ids/persons.csv             人物ID の台帳（氏名・別表記）
人物ID の決め方は scripts/person_ids.py の Ledger.resolve と同じ：台帳で1人に決まればその人物ID、台帳に無ければ正規化した氏名、
同姓同名で複数いれば決めずに「算入=いいえ」にする（院では決めない）。

出力：data/derived/allocation-v1/opposing.csv
使い方：python3 scripts/build_opposing_votes.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.person_ids import UNRESOLVED, canonical  # noqa: E402

VOTES = ROOT / "data/derived/allocation-v1/votes.csv"
AUTO_VOTES = ROOT / "data/derived/allocation-v1/votes-auto.csv"  # scripts/build_auto_involvements.py
BALLOTS = ROOT / "data/acquired/sangiin-votes/ballots"
MEMBERS = ROOT / "data/acquired/sangiin-votes/members.csv"
PERSONS = ROOT / "data/derived/person-ids/persons.csv"
OUT = ROOT / "data/derived/allocation-v1/opposing.csv"
HEADER = ["法律ID", "投票ID", "氏名", "人物ID", "証拠URL", "算入", "除外理由"]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build() -> list[dict[str, str]]:
    ids: dict[str, set[str]] = defaultdict(set)
    for p in _read(PERSONS):
        if not p["人物ID"]:
            continue
        for name in [p["氏名"], *filter(None, p.get("別表記", "").split(";"))]:
            ids[canonical(name)].add(p["人物ID"])
    names = {(m["回次"], m["議員ID"]): m["議員名"] for m in _read(MEMBERS)}
    ballots: dict[str, list[dict[str, str]]] = {}
    out = []
    for v in sorted(_read(VOTES) + (_read(AUTO_VOTES) if AUTO_VOTES.exists() else []), key=lambda r: r["法律ID"]):
        session = v["投票ID"].split("-")[0]
        if session not in ballots:
            path = BALLOTS / f"ballots_{session}.csv"
            ballots[session] = _read(path) if path.exists() else []
        for b in ballots[session]:
            if b["投票ID"] != v["投票ID"] or b["賛否"] != "N":
                continue
            name = names.get((session, b["議員ID"]))
            if not name:
                raise ValueError(f"議員名がありません: {v['投票ID']} 議員ID={b['議員ID']}")
            found = ids.get(canonical(name), set())
            pid, why = (next(iter(found)) if found else canonical(name), "") if len(found) <= 1 else ("", UNRESOLVED)
            out.append({"法律ID": v["法律ID"], "投票ID": v["投票ID"], "氏名": name, "人物ID": pid, "証拠URL": v["URL"],
                        "算入": "いいえ" if why else "はい", "除外理由": why})
    return out


def main() -> int:
    rows = build()
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print(f"反対票 {len(rows)}行（算入 {sum(r['算入'] == 'はい' for r in rows)}・同姓同名で外した {sum(r['算入'] != 'はい' for r in rows)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
