#!/usr/bin/env python3
"""委員会の審議（data/acquired/committee-deliberation/amendments.csv）から、修正案の提出者を議員の因果の鎖（関与の一覧）に足す。

修正案を出した人は「法案の中身を変える能動的な行動」をした人なので、行動 amend として鎖に入れる（allocation-v1 の決まり）。
- 数える（算入=はい）のは、委員会で修正案が可決され、かつ個人への帰属を独立した2系統が一致して確かめた提出者だけ（AGENTS.md、ADR 0007）。
  会議録から機械で取った段階は「候補」で、算入=いいえ（除外理由に書く）。確認結果は data/acquired/committee-deliberation/amend-confirmed.csv
  （法律ID・院・氏名・系統A・系統B。両方が「確認」のときだけ採用）から読む。否決・採否不明も記録は残すが算入=いいえ。
- 提出者は、委員長が読み上げた筆頭提出者と、趣旨説明をした提出者代表。「外N名」の残りは会議録に名前が出ないので足さない。
- 委員長提出の修正案は、その委員会の委員長の名前（出席委員の役職欄）を提出者にする。
- 足すのは、関与の一覧（involvements.csv / involvements-auto.csv）に既にある法律だけ。人物IDは台帳で1人に決まるときだけ付け、
  複数に当たる同姓同名は算入=いいえ。すでに同じ法律・同じ人・同じ行動の行があれば足さない。
出力：data/derived/allocation-v1/involvements-auto.csv に追記する（前回この表が足した行は先に外すので、何度流しても同じ。
  順番は build_auto_involvements.py → このスクリプト → node scripts/build_public_members.mjs）。
使い方：python3 scripts/build_committee_amend_involvements.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.allocation_involvements import HEADER  # noqa: E402
from scripts.person_ids import UNRESOLVED, canonical  # noqa: E402

DERIVED = ROOT / 'data/derived'
AMENDMENTS = ROOT / 'data/acquired/committee-deliberation/amendments.csv'
CONFIRMED = ROOT / 'data/acquired/committee-deliberation/amend-confirmed.csv'
PERSONS = DERIVED / 'person-ids/persons.csv'
SOURCES = [DERIVED / 'allocation-v1/involvements.csv', DERIVED / 'allocation-v1/involvements-auto.csv']
AUTO = DERIVED / 'allocation-v1/involvements-auto.csv'
MARK = '修正案の提出（委員会の会議録）'


def _read(path: Path) -> list[dict]:
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def build() -> list[dict]:
    ids: dict[str, set[str]] = defaultdict(set)
    for p in _read(PERSONS):
        if p['人物ID']:
            for name in [p['氏名'], *filter(None, p.get('別表記', '').split(';'))]:
                ids[canonical(name)].add(p['人物ID'])

    def person(name: str) -> tuple[str, str]:
        found = ids.get(canonical(name), set())
        if len(found) > 1:
            return '', UNRESOLVED
        return (next(iter(found)) if found else canonical(name)), ''

    covered = set()
    existing = set()
    for src in SOURCES:
        if src.exists():
            for r in _read(src):
                if r['立場の根拠'] == MARK:
                    continue  # 前回この表が足した行は数え直す
                covered.add(r['法律ID'])
                if r['行動'] == 'amend':
                    existing.add((r['法律ID'], canonical(r['氏名']), r['院']))
    confirmed: dict[tuple, tuple[str, str]] = {}
    if CONFIRMED.exists():
        for c in _read(CONFIRMED):
            confirmed[(c['法律ID'], c['院'], canonical(c['氏名']))] = (c.get('系統A', ''), c.get('系統B', ''))
    best: dict[tuple, tuple] = {}  # 同じ法律・人・院の候補は集約して、可決された行動を優先して残す
    for a in _read(AMENDMENTS):
        if a['法律ID'] not in covered:
            continue
        adopted = a['修正案の結果'] == '可決'
        why = '' if adopted else ('委員会で修正案が否決された（法案を前に進めていない）' if a['修正案の結果'] == '否決' else '修正案の採否を会議録から特定できなかった')
        url = a['趣旨説明のURL'] or a['宣告のURL']
        for name, title in ((a['提出者(筆頭)'], '修正案の筆頭提出者（委員会）'), (a['趣旨説明者'], '修正案の提出者代表（趣旨説明、委員会）')):
            if not name or name == '委員長':
                continue
            key = (a['法律ID'], canonical(name), a['院'])
            if key in existing:
                continue
            rank = (0 if adopted else 1 if a['修正案の結果'] == '否決' else 2, a['日付'])
            if key in best and best[key][0] <= rank:
                continue
            pid, unresolved = person(name)
            ca, cb = confirmed.get((a['法律ID'], a['院'], canonical(name)), ('', ''))
            reason = why or ('' if unresolved or (ca == '確認' and cb == '確認') else '会議録から機械で抽出した候補（個人への帰属を2系統で確認するまで数えない。AGENTS.md）')
            best[key] = (rank, {'法律ID': a['法律ID'], '題名': a['題名'], '氏名': name, '氏名_原表記': name, '院': a['院'], '行動': 'amend',
                         '当時の肩書': title, '立場区分': 'other', '立場の根拠': MARK, '日付': a['日付'],
                         '証拠URL': url, '系統A': ca, '系統B': cb, '参院本会議の賛否': '',
                         '算入': 'いいえ' if (reason or unresolved) else 'はい', '除外理由': unresolved or reason, '人物ID': pid})
    rows = [v[1] for v in best.values()]
    rows.sort(key=lambda r: (r['法律ID'], r['院'], r['氏名']))
    return rows


def main() -> int:
    rows = build()
    kept = [r for r in _read(AUTO) if r['立場の根拠'] != MARK]
    with open(AUTO, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, HEADER)
        w.writeheader()
        w.writerows(kept + rows)
    print(f'修正案の提出者 {len(rows)}行（算入 {sum(r["算入"] == "はい" for r in rows)}）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
