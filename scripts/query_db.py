"""data/db/queries.sql のよく使う問い合わせを実行する。

使い方：
  python3 scripts/query_db.py                         # 問い合わせの一覧
  python3 scripts/query_db.py 議員の内訳 person=麻生太郎
  python3 scripts/query_db.py 年ごとの額 --csv > 年ごと.csv
  python3 scripts/query_db.py --db 別の.sqlite 議員の順位 limit=20
データベースが無ければ先に python3 scripts/build_database.py を実行する。
"""
from __future__ import annotations

import argparse
import csv
import re
import signal
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "data" / "db" / "queries.sql"
DB = ROOT / "data" / "db" / "kokuzoku.sqlite"


def load_queries(path: Path = QUERIES) -> dict[str, tuple[str, str]]:
    """名前 →（説明, SQL）。"""
    out: dict[str, tuple[str, str]] = {}
    for block in re.split(r"^-- name: ", path.read_text(encoding="utf-8"), flags=re.M)[1:]:
        name, _, body = block.partition("\n")
        notes = [line[3:] for line in body.splitlines() if line.startswith("-- ")]
        sql = "\n".join(line for line in body.splitlines() if not line.startswith("--")).strip()
        out[name.strip()] = (" ".join(notes), sql)
    return out


def run(con: sqlite3.Connection, sql: str, params: dict[str, str]) -> tuple[list[str], list[tuple]]:
    needed = set(re.findall(r"(?<![\w':]):([a-z]\w*)", sql))  # 文字列の中の ':LR' は引数ではない
    defaults = {"limit": "30"}
    missing = needed - set(params) - set(defaults)
    if missing:
        raise SystemExit(f"引数が足りません: {', '.join(sorted(missing))}（例 {next(iter(missing))}=...）")
    cur = con.execute(sql, {k: params.get(k, defaults.get(k)) for k in needed})
    return [d[0] for d in cur.description], cur.fetchall()


def main() -> int:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # head などで途中で切っても例外を出さない
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?")
    parser.add_argument("params", nargs="*", help="key=value")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--csv", action="store_true")
    args = parser.parse_args()
    queries = load_queries()
    if not args.name:
        for name, (note, _) in queries.items():
            print(f"{name}：{note}")
        return 0
    if args.name not in queries:
        raise SystemExit(f"問い合わせ「{args.name}」はありません。一覧は引数なしで実行")
    if not args.db.exists():
        raise SystemExit(f"{args.db} がありません。python3 scripts/build_database.py で作ってください")
    params = dict(p.split("=", 1) for p in args.params)
    cols, rows = run(sqlite3.connect(args.db), queries[args.name][1], params)
    if args.csv:
        w = csv.writer(sys.stdout)
        w.writerow(cols)
        w.writerows(rows)
    else:
        print("\t".join(cols))
        for r in rows:
            print("\t".join("" if v is None else str(v) for v in r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
