"""議員ページで配る法律の参議院の採決ごとに、投票した議員の会派を書く（政党ランキング用、設計決定0014 の決定8）。

同じ回次の途中で会派が変わった議員は、参議院の投票の名簿（members.csv）に会派ごとの別の議員IDで載る。
回次と氏名だけで会派を引くと最後の会派で上書きされるので、採決ごとの投票（ballots）の議員IDから、その採決の時の会派を決める。

入力：data/derived/allocation-v1/votes.csv・votes-auto.csv（法律ごとの採決）、data/acquired/sangiin-votes/members.csv・ballots/
出力：data/derived/allocation-v1/vote-parties.csv（投票ID・議員名・会派・賛否。賛成 Y と反対 N だけ）
使い方：python3 scripts/build_vote_parties.py
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOC = ROOT / "data/derived/allocation-v1"
VOTES = ROOT / "data/acquired/sangiin-votes"
OUT = ALLOC / "vote-parties.csv"
HEADER = ["投票ID", "議員名", "会派", "賛否"]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build() -> list[dict[str, str]]:
    wanted = {r["投票ID"] for f in ("votes.csv", "votes-auto.csv") for r in _read(ALLOC / f)}
    members = {(r["回次"], r["議員ID"]): r for r in _read(VOTES / "members.csv")}
    rows = []
    for session in sorted({v.split("-")[0] for v in wanted}):
        path = VOTES / "ballots" / f"ballots_{session}.csv"
        for b in _read(path) if path.exists() else []:
            if b["投票ID"] not in wanted or b["賛否"] not in ("Y", "N"):
                continue
            m = members.get((session, b["議員ID"]))
            if not m:
                raise ValueError(f"議員の名簿にありません: {b['投票ID']} 議員ID={b['議員ID']}")
            rows.append({"投票ID": b["投票ID"], "議員名": m["議員名"], "会派": m["会派"], "賛否": b["賛否"]})
    rows.sort(key=lambda r: (r["投票ID"], r["議員名"]))
    return rows


def main() -> int:
    rows = build()
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"採決ごとの会派 {len(rows)}行（採決 {len({r['投票ID'] for r in rows})}件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
