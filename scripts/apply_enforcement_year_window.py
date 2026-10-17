"""施行日が「政令で定める日」で空欄の行に、年単位の判定に足りる施行日を置く（暫定値）。

影響・損失の判定は年（暦年は12月31日、年度は翌年3月31日の時点）でしか施行日を使わない
（app/src/impact-batch.ts の asOfYear・startPeriod）。そのため施行の年と年度が決まれば、日が分からなくても判定は同じになる。

採る規則（推測で埋めない）:
1. 附則の「公布の日から起算して◯を超えない範囲内において政令で定める日」から期限を計算する（apply_enforcement_webfetch.decree_deadline）。
2. e-Gov の改正履歴から得た候補（施行日の候補列）のうち、公布日より後で期限以内の日がちょうど1つなら、その日を置く。
   改正履歴の施行日は一部の規定の日のこともあるので、取得方法に「暫定」と書く。
3. 2が無く、公布日と期限が同じ暦年・同じ年度なら、期限の日を置く。日は未確定だが、年単位の判定は日に依らない。
4. それ以外（年が決まらない、期限が読めない）は空欄のまま。既に施行日がある行は変えない。
"""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.apply_enforcement_webfetch import decree_deadline
from scripts.fetch_enforcement_fusoku import CAND_COL, NEW_COL

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "acquired" / "enforcement-dates" / "enforcement.csv"

METHOD_CANDIDATE = "e-Gov 改正履歴の施行日（附則の期限内でただ1つ、暫定値）"
METHOD_WINDOW = "年の確定（附則の期限と公布日が同じ年・同じ年度。日は未確定で期限の日を置く、暫定値）"


def fiscal_year(date: str) -> int:
    return int(date[:4]) - (1 if int(date[5:7]) < 4 else 0)


def same_year(a: str, b: str) -> bool:
    return a[:4] == b[:4] and fiscal_year(a) == fiscal_year(b)


def judge(row: dict) -> tuple[str, str, str] | None:
    """(施行日, 取得方法, 備考) を返す。決まらなければ None。"""
    promulgation = row["公布日"]
    deadline = decree_deadline(row[NEW_COL], promulgation)
    if not deadline or not promulgation:
        return None
    inside = sorted({d.strip() for d in row[CAND_COL].split(";") if promulgation < d.strip() <= deadline})
    if len(inside) == 1:
        return inside[0], METHOD_CANDIDATE, f"改正履歴の候補のうち附則の期限（{deadline}）以内の日は {inside[0]} だけ"
    if same_year(promulgation, deadline):
        return deadline, METHOD_WINDOW, f"施行日は {promulgation} から {deadline} の間（同じ年・同じ年度）。年単位の判定のため期限の日を置いた"
    return None


def apply(rows: list[dict]) -> list[str]:
    log = []
    for row in rows:
        if row["施行日"]:
            continue
        got = judge(row)
        if not got:
            continue
        date, method, note = got
        row["施行日"] = date
        row["取得方法"] = method
        row["備考"] = "；".join(filter(None, [note, row["備考"]]))
        log.append(f"{row['id']}: {date}（{method}）")
    return log


def main() -> None:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    log = apply(rows)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for line in log:
        print(line)
    print(f"施行日あり {sum(1 for r in rows if r['施行日'])} / {len(rows)} 本")


if __name__ == "__main__":
    main()
