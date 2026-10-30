#!/usr/bin/env python3
"""互いに結びついていないデータを洗い出す。キー（法律ID・人物ID・氏名・団体名）の突き合わせで、孤立した行を数える。

LINKS に「どのファイルのどの列が、どの台帳に載っているべきか」を1行ずつ書く。足りない関係はここへ足す。
出力:
  data/derived/link-audit/summary.csv  … 関係ごとの件数（行数・空欄・台帳に無い）
  data/derived/link-audit/orphans.csv  … 孤立した行（関係名・ファイル・行番号・キー）。1関係あたり上限 --cap 件
  docs/未結合データ台帳.md              … 人が読む表（summary と同じ数字）
推測では埋めない。結べない理由は「空欄」「台帳に無い」の2つに分けて数える。

使い方: python3 scripts/audit_links.py [--cap 200]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.org_names import org_key  # noqa: E402

D = ROOT / "data"
OUT_DIR = D / "derived/link-audit"
DOC = ROOT / "docs/未結合データ台帳.md"


def rows(rel: str) -> list[dict[str, str]]:
    with open(D / rel, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def nospace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


@dataclass
class Link:
    name: str  # 関係の名前
    src: str  # 結ぶ側のファイル（data/ から）
    col: str  # 結ぶ側のキーの列
    target: str  # 台帳の名前（TARGETS のキー）
    norm: str = ""  # "nospace" / "org" / ""
    why: str = ""  # 結べないときの既知の理由（空なら未調査）


def targets() -> dict[str, set[str]]:
    persons = rows("derived/person-ids/persons.csv")
    ids = {p["人物ID"] for p in persons if p["人物ID"]}
    names = {nospace(n) for p in persons if p["人物ID"] for n in [p["氏名"], *filter(None, re.split(r"[;／]", p["別表記"]))]}
    laws = {r["id"] for r in rows("derived/all-laws-v1/outcomes.csv")}
    unenacted = {r["id"] for r in rows("derived/unenacted-bills-v1/scale.csv")}
    treaties = {r["id"] for r in rows("derived/treaties-v1/outcomes.csv")}
    org = {org_key(r["団体"]) for r in rows("derived/org-ledger-v1/org-stances.csv")}
    org |= {org_key(r["団体名"]) for r in rows("acquired/pressure-groups/positions.csv")}
    return {"人物ID": ids, "氏名": names, "法律": laws, "未成立法案": unenacted, "条約": treaties, "団体": org}


LINKS = [
    Link("関与→人物ID", "derived/allocation-v1/involvements.csv", "人物ID", "人物ID"),
    Link("関与→法律", "derived/allocation-v1/involvements.csv", "法律ID", "法律"),
    Link("採決→法律", "derived/allocation-v1/votes.csv", "法律ID", "法律"),
    Link("圧力団体の立場→法律", "acquired/pressure-groups/positions.csv", "法律ID", "法律",
         why="要望は「法令名」への求めで、特定の法案ではない。改正法IDは経済界の帳簿（chain.csv）が要望→改正で結ぶ。推測で埋めない"),
    Link("経済界の要望→改正法", "derived/business-ledger-v1/chain.csv", "改正法ID", "法律"),
    Link("閣法の所管→法律", "derived/ministry-v1/cabinet-bills.csv", "法律ID", "法律"),
    Link("族議員の表→人物ID", "derived/zoku-v1/member-field-ties.csv", "人物ID", "人物ID",
         why="同姓同名は結ばない（台帳でちょうど1人に決まる名前だけ）"),
    Link("支部の政党交付金→人物ID", "derived/party-subsidy/branch-subsidy-2025.csv", "人物ID", "人物ID",
         why="代表者の記載が無い政党・支部の行（個人ではない）。名前が載る行は結べている"),
    Link("議連の役職→氏名", "acquired/diet-leagues/memberships.csv", "氏名", "氏名", "nospace"),
    Link("政治資金の関係団体→氏名", "acquired/political-funds/member-groups.csv", "氏名", "氏名", "nospace",
         why="残りは会議録（1986-07以降）に議員としての発言が無い、または表記が違う人。diet-roster/historical-unmatched.csv に理由つき"),
    Link("提出者（未成立法案）→人物ID", "derived/unenacted-bills-v1/submitters.csv", "筆頭の人物ID", "人物ID",
         why="委員会の提出（提出者が委員長の役職名）5件、提出者の記載なし4件、台帳に無い3件。院を移った人はもう一方の院の同名1人に結ぶ"),
    Link("提出者（未成立法案）→未成立法案", "derived/unenacted-bills-v1/submitters.csv", "id", "未成立法案"),
    Link("団体の立場→圧力団体", "derived/org-ledger-v1/org-stances.csv", "団体", "団体", "org"),
    Link("経済界の要望の提案主体→団体の帳簿", "derived/business-ledger-v1/by-proposer.csv", "提案主体", "団体", "org",
         why="団体の立場の帳簿は審議会・ヒアリングで発言した団体だけ。要望だけの団体は載らない（取り込み未着手）"),
]


def key(v: str, norm: str) -> str:
    return nospace(v) if norm == "nospace" else org_key(v) if norm == "org" else v.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=200)
    a = ap.parse_args()
    tg = targets()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary, orphans = [], []
    for ln in LINKS:
        try:
            data = rows(ln.src)
        except FileNotFoundError:
            summary.append([ln.name, ln.src, ln.col, ln.target, 0, 0, 0, "ファイルが無い"])
            continue
        blank = missing = 0
        kept = 0
        for i, r in enumerate(data, start=2):
            v = r.get(ln.col, "")
            if not v.strip():
                blank += 1
                kind = "空欄"
            elif key(v, ln.norm) not in tg[ln.target]:
                missing += 1
                kind = "台帳に無い"
            else:
                continue
            if kept < a.cap:
                orphans.append([ln.name, ln.src, i, kind, v])
                kept += 1
        summary.append([ln.name, ln.src, ln.col, ln.target, len(data), blank, missing, ln.why])
    with open(OUT_DIR / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["関係", "ファイル", "キー列", "台帳", "行数", "空欄", "台帳に無い", "既知の理由"])
        w.writerows(summary)
    with open(OUT_DIR / "orphans.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["関係", "ファイル", "行番号", "種類", "キー"])
        w.writerows(orphans)
    lines = ["# 未結合データ台帳", "", "`python3 scripts/audit_links.py` が作る。孤立行の一覧は `data/derived/link-audit/orphans.csv`（1関係あたり上限件）。", "",
             "| 関係 | 行数 | 空欄 | 台帳に無い | 結べた割合 | 既知の理由 |", "|---|---:|---:|---:|---:|---|"]
    for n, _, _, _, tot, bl, ms, why in summary:
        ok = f"{(tot - bl - ms) / tot:.0%}" if tot else "-"
        lines.append(f"| {n} | {tot} | {bl} | {ms} | {ok} | {why} |")
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for s in summary:
        print(f"{s[0]}: {s[4]}行 空欄{s[5]} 台帳に無い{s[6]}")


if __name__ == "__main__":
    main()
