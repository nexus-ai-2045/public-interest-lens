"""団体の帳簿と省庁の抵抗の件数（霞が関の案の3番目、団体の帳簿の1本目）。

止めた側の記録（data/acquired/blocking-actors/）のうち、原本照合済み（機械の照合と AI 2系統が一致）の行だけを数える。
額は付けない（額のある法律に結び付けるのは後の PR）。報道・評論は使わない。個人（学者・委員・官僚）は名指しせず、区分でまとめる。
- 省庁の抵抗の件数：規制改革ホットラインで「対応不可」とした回答、WG のヒアリングで反対・慎重とした発言、
  規制改革会議のフォローアップで反対・慎重・未措置とされた事項を、所管省庁ごとに数える（共管は各省庁に1件ずつ）。
- 団体の立場：審議会・検討会で、名前のある団体（業界団体・消費者団体・自治体など）が示した立場を、団体ごとに数える。
  学者・委員・肩書の無い発言者は団体の名前を出さず、区分ごとに数える。

使い方（リポジトリのルートで）: python3 scripts/build_org_ledger.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/acquired/blocking-actors'
OUT_MINISTRY = ROOT / 'data/derived/org-ledger-v1/ministry-resistance.csv'
OUT_ORG = ROOT / 'data/derived/org-ledger-v1/org-stances.csv'
VERIFIED = '原本照合済み'
# 名前を出す区分（団体）。ほかの区分（学者・委員・弁護士・所属なし）は区分だけで数える。
NAMED_KINDS = ('業界団体', 'その他（消費者団体）')
NAMED_ORG = re.compile(r'(協会|連盟|連合|医師会|薬剤師会|歯科医師会|団体|機構|協議会|東京都|道府県|市|町|村)')


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return [r for r in csv.DictReader(f) if r.get('確度', '').startswith(VERIFIED)]


def ministries(text: str) -> list[str]:
    """「厚生労働省・観光庁」は2つ、「厚生労働省（氏名記載なし）」は厚生労働省。"""
    text = re.sub(r'（[^）]*）', '', text or '').strip()
    return [m for m in re.split(r'[・、,]', text) if m] or ['（記載なし）']


def org_name(text: str) -> str:
    """「日本薬剤師会（議事録の表記）」「日本ホテル協会 専務理事」から団体名だけを取る。"""
    name = re.split(r'[\s　（(]', text.strip())[0]
    return name or '（団体名の記載なし）'


def records() -> list[dict]:
    """数える記録の一覧（原本照合済みの行だけ）。省庁の抵抗・ホットラインの回答・団体の立場を1行ずつ。

    build() と scripts/build_backing_forces.py（背後の力を議員の因果の鎖へ結ぶ）が同じ一覧を使う。
    「どの行を数えるか」の正本はここだけで、結び付けの側が数え方を持ち直さない。
    """
    out: list[dict] = []
    req = BASE / '1_regulatory-requests'
    for f in ('hotline.csv', 'hotline-h26-h27.csv', 'hotline-h29-later.csv'):
        for r in read(req / f):
            for m in ministries(r['所管省庁']):
                out.append({'帳簿': '省庁', '種類': '対応不可' if '対応不可' in r['対応分類'] else '回答', '省庁': m,
                            '日付': r['受付日'], '法令': r['該当法令'], '技術': r['関連技術'], '出典URL': r['出典URL']})
    for r in read(req / 'wg-hearings.csv'):
        if r['立場（反対・慎重）'] in ('反対', '慎重'):
            for m in ministries(r['所管省庁']):
                out.append({'帳簿': '省庁', '種類': 'ヒアリングで反対・慎重', '省庁': m, '日付': r['開催日'], '法令': r['該当法令'],
                            '技術': r['関連技術'], '出典URL': r['出典URL']})
    for r in read(req / 'council-followup.csv'):
        if r['省庁の立場（反対・慎重・未措置）'] in ('反対', '慎重', '未措置'):
            for m in ministries(r['所管省庁']):
                out.append({'帳簿': '省庁', '種類': 'フォローアップで反対・慎重・未措置', '省庁': m, '日付': r['年月日'], '法令': r['該当法令'],
                            '技術': r['関連技術'], '出典URL': r['出典URL']})
    for f in sorted((BASE / '2_shingikai').glob('*.csv')):
        for r in read(f):
            kind, who = r['発言者の区分'], r['発言者の所属・肩書']
            named = kind in NAMED_KINDS or (kind not in ('学者', '有識者', '省庁') and NAMED_ORG.search(org_name(who)) is not None)
            out.append({'帳簿': '団体', '団体': org_name(who) if named else f'（{kind}・名前は出さない）', '区分': kind, '立場': r['立場'],
                        '日付': r['開催日'], '法令': r['関連法令'], '技術': r['関連技術'], '出典URL': r['出典URL']})
    return out


def build() -> dict[str, int]:
    book: dict[str, dict] = defaultdict(lambda: {'対応不可': 0, '回答': 0, 'ヒアリングで反対・慎重': 0, 'フォローアップで反対・慎重・未措置': 0, '出典URL': set()})
    orgs: dict[tuple[str, str], dict] = defaultdict(lambda: {'反対': 0, '慎重': 0, '条件付き賛成': 0, '賛成': 0, '技術': set(), '出典URL': set()})
    for rec in records():
        if rec['帳簿'] == '省庁':
            t = book[rec['省庁']]
            if rec['種類'] in ('対応不可', '回答'):
                t['回答'] += 1
            if rec['種類'] != '回答':
                t[rec['種類']] += 1
                t['出典URL'].add(rec['出典URL'])
        else:
            t = orgs[(rec['団体'], rec['区分'])]
            if rec['立場'] in t:
                t[rec['立場']] += 1
            if rec['技術']:
                t['技術'].add(rec['技術'])
            t['出典URL'].add(rec['出典URL'])
    rows = []
    for m, t in book.items():
        total = t['対応不可'] + t['ヒアリングで反対・慎重'] + t['フォローアップで反対・慎重・未措置']
        rows.append({'省庁': m, '抵抗の件数': total, '対応不可': t['対応不可'], 'ホットラインの回答': t['回答'],
                     '対応不可の割合': f"{t['対応不可'] / t['回答']:.3f}" if t['回答'] else '',
                     'ヒアリングで反対・慎重': t['ヒアリングで反対・慎重'], 'フォローアップで反対・慎重・未措置': t['フォローアップで反対・慎重・未措置'],
                     '出典URL': ' '.join(sorted(t['出典URL']))})
    rows.sort(key=lambda r: (-r['抵抗の件数'], r['省庁']))
    write(OUT_MINISTRY, rows)
    org_rows = [{'団体': name, '区分': kind, '反対': t['反対'], '慎重': t['慎重'], '条件付き賛成': t['条件付き賛成'], '賛成': t['賛成'],
                 '関連技術': '、'.join(sorted(t['技術'])), '出典URL': ' '.join(sorted(t['出典URL']))} for (name, kind), t in orgs.items()]
    org_rows.sort(key=lambda r: (-(r['反対'] + r['慎重']), r['団体']))
    write(OUT_ORG, org_rows)
    return {'省庁': len(rows), '抵抗の件数': sum(r['抵抗の件数'] for r in rows), '団体': len(org_rows)}


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False))
    sys.exit(0)
