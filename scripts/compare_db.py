"""計算方法の版を上げる前後の2つのデータベースを比べ、影響（上位がどう動くか）を Markdown で出す（設計決定0013 の 4）。

使い方：
  git stash などで前の版に戻し python3 scripts/build_database.py --no-charts --out /tmp/前.sqlite
  新しい版で python3 scripts/build_database.py --no-charts --out /tmp/新.sqlite
  python3 scripts/compare_db.py /tmp/前.sqlite /tmp/新.sqlite [--top 20] > 影響.md
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def cho(yen: int | float | None) -> str:
    return "—" if yen is None else f"{yen / 1e12:,.2f}兆円"


def rows(con: sqlite3.Connection, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()


def compare(before: Path, after: Path, top: int = 20) -> str:
    a, b = sqlite3.connect(before), sqlite3.connect(after)
    meta = lambda con: dict(rows(con, "SELECT key, value FROM meta"))  # noqa: E731
    out = [f"# 計算の版の影響：{meta(a).get('spec')} → {meta(b).get('spec')}", ""]
    versions = lambda con: {c: v for c, v in rows(con, "SELECT component, version FROM method_versions")}  # noqa: E731
    va, vb = versions(a), versions(b)
    changed = [f"{c}：{va.get(c, '（無し）')} → {vb.get(c, '（無し）')}" for c in sorted(set(va) | set(vb)) if va.get(c) != vb.get(c)]
    out += ["## 変わった部品", "", *([f"- {x}" for x in changed] or ["- なし"]), ""]
    sql = "SELECT certainty, side, COUNT(*), SUM(median) FROM laws WHERE outcome='額' GROUP BY 1, 2"
    ca, cb = {(c, s): (n, m) for c, s, n, m in rows(a, sql)}, {(c, s): (n, m) for c, s, n, m in rows(b, sql)}
    out += ["## 確かさ別の本数と額（中央値の合計。同じ観測の重なりを含む）", "", "| 確かさ | 向き | 本数（前→新） | 額（前→新） |", "|---|---|---|---|"]
    for key in sorted(set(ca) | set(cb), key=lambda k: ("高中低参".find(k[0] or "参"), k[1] or "")):
        (na, ma), (nb, mb) = ca.get(key, (0, 0)), cb.get(key, (0, 0))
        out.append(f"| {key[0]} | {key[1]} | {na} → {nb} | {cho(ma)} → {cho(mb)} |")
    out.append("")
    for title, sql in (
        ("法律の額の上位（確かな額。同じ観測を共有する法律は同じ額で並ぶ）", f"SELECT l.law_id, l.title, l.median FROM laws l WHERE l.certainty IN ('高','中','低') ORDER BY l.median DESC LIMIT {top}"),
        ("議員の上位（確かな額、純額の小さい順）", f"SELECT s.person_id, p.name, s.net_median FROM member_scores s JOIN people p USING (person_id) WHERE s.ledger='確か' ORDER BY s.rank LIMIT {top}"),
    ):
        ra, rb = rows(a, sql), rows(b, sql)
        pos_a = {r[0]: i + 1 for i, r in enumerate(ra)}
        out += [f"## {title}", "", "| 新の順位 | 前の順位 | 名前 | 額（新） |", "|---|---|---|---|"]
        for i, (key, name, value) in enumerate(rb, 1):
            out.append(f"| {i} | {pos_a.get(key, '圏外')} | {name} | {cho(value)} |")
        dropped = [r[1] for r in ra if r[0] not in {x[0] for x in rb}]
        out += ["", f"上位から外れた：{'、'.join(dropped) if dropped else 'なし'}", ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    print(compare(args.before, args.after, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
