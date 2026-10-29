"""メディアの帳簿（点数の外の別帳簿）。メディア業界自身に関わる法律・制度での関与の事実を、一次資料つきで並べる。

主役は国会議員で、メディアは背後の力。ここは確かめられる事実だけを記録し、論調・思想の良し悪しで点を付けない。
個人（記者・役員など）は名指しせず、団体・会社・肩書の区分だけで数える。額は付けない。
- bills.csv：題名にメディア規制の語（放送・電波・有線テレビ・新聞 など）を含む成立法と、その法律での参考人出席の件数
- member-links.csv：上の法律での議員の関与（既存の関与の表から。因果の鎖への入口。法律ID・人物ID・証拠URLつき）
- witnesses.csv：メディア関係団体が国会で参考人として出席した会議（会議録の発言者区分「参考人」の肩書から。会議ごと・団体ごと）
- events.csv：制度ごとの出来事（原本で確認できたものだけ）。data/acquired/media-ledger/facts_*.json から
- series.csv：新聞発行部数・民放営業収入などの年次系列（公表値の転記）
- summary.json：件数と、この帳簿の限界

入力：data/acquired/media-ledger/（diet-witnesses.csv は scripts/fetch_media_witnesses.py で取得、facts_*.json・series_media.json は原本で確認した記録）、
data/derived/all-laws-v1/outcomes.csv、data/derived/allocation-v1/involvements*.csv

使い方（リポジトリのルートで）: python3 scripts/build_media_ledger.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACQ = ROOT / 'data/acquired/media-ledger'
OUT = ROOT / 'data/derived/media-ledger-v1'
LAWS = ROOT / 'data/derived/all-laws-v1/outcomes.csv'
INVOLVEMENTS = (ROOT / 'data/derived/allocation-v1/involvements.csv', ROOT / 'data/derived/allocation-v1/involvements-auto.csv')
# メディア自身の規制・特権に関わる法律の題名の語。
MEDIA_LAW = re.compile(r'放送|電波|有線テレビ|有線ラジオ|新聞|通信・放送')
# 放送・通信を所管する委員会（業界の利害が直接出る場）。
INDUSTRY_COMMITTEE = re.compile(r'総務|逓信|郵政|電気通信|情報通信|通信|放送')
ISSUE_FROM_URL = re.compile(r'kokkai\.ndl\.go\.jp/txt/([0-9A-Z]+)')
CONFIRMED = '原本で確認'


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def load_facts(name: str) -> list[dict]:
    path = ACQ / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def usable(fact: dict) -> bool:
    """原本で確認した記録だけを使う（出典URLと原文の抜粋がそろっているもの）。"""
    return fact.get('confidence') == CONFIRMED and bool(fact.get('source_url')) and bool(fact.get('quote'))


def build() -> dict:
    witnesses = read_csv(ACQ / 'diet-witnesses.csv')
    for w in witnesses:
        w['放送・通信の所管委員会'] = 'はい' if INDUSTRY_COMMITTEE.search(w['会議名']) else 'いいえ'
    by_issue: dict[str, list[dict]] = defaultdict(list)
    for w in witnesses:
        by_issue[w['会議ID']].append(w)

    laws = [r for r in read_csv(LAWS) if MEDIA_LAW.search(r['題名'])]
    law_ids = {r['id'] for r in laws}
    links: dict[tuple[str, str], dict] = {}
    law_issues: dict[str, set[str]] = defaultdict(set)
    for path in INVOLVEMENTS:
        for r in read_csv(path):
            if r['法律ID'] not in law_ids:
                continue
            m = ISSUE_FROM_URL.search(r.get('証拠URL', ''))
            if m:
                law_issues[r['法律ID']].add(m.group(1))
            key = (r['法律ID'], r['氏名'] + '|' + r['行動'] + '|' + r.get('証拠URL', ''))
            if key in links:
                continue
            links[key] = {'法律ID': r['法律ID'], '題名': r['題名'], '氏名': r['氏名'], '人物ID': r.get('人物ID', ''), '院': r['院'],
                          '行動': r['行動'], '当時の肩書': r.get('当時の肩書', ''), '立場区分': r.get('立場区分', ''),
                          '日付': r.get('日付', ''), '証拠URL': r.get('証拠URL', '')}
    link_rows = sorted(links.values(), key=lambda r: (r['法律ID'], r['日付'], r['氏名'], r['行動']))

    bill_rows = []
    for r in sorted(laws, key=lambda r: r['id']):
        matched = sorted({w['会議ID'] for i in law_issues.get(r['id'], ()) for w in by_issue.get(i, [])})
        kinds = sorted({w['団体の区分'] for i in matched for w in by_issue[i]})
        bill_rows.append({'法律ID': r['id'], '題名': r['題名'], '結果': r['結果'], '確かさ': r['確かさ'],
                          '参考人が出席した会議の数': len(matched), '出席した団体の区分': '、'.join(kinds),
                          '議員の関与の記録': sum(1 for l in link_rows if l['法律ID'] == r['id']),
                          '会議ID': ' '.join(matched)})
    write_csv(OUT / 'bills.csv', list(bill_rows[0]), bill_rows)
    write_csv(OUT / 'member-links.csv', list(link_rows[0]), link_rows)
    wrows = sorted(({k: w[k] for k in ('会議ID', '日付', '院', '会議名', '団体の区分', '肩書', '放送・通信の所管委員会', '会議録URL')} for w in witnesses),
                   key=lambda r: (r['日付'], r['会議ID'], r['団体の区分']))
    write_csv(OUT / 'witnesses.csv', list(wrows[0]), wrows)

    events = []
    for name, kind in (('facts_rules.json', '制度'), ('facts_councils.json', '審議会・要望')):
        for f in load_facts(name):
            if usable(f):
                detail = f.get('detail')
                events.append({'区分': kind, '主題': f.get('topic') or f.get('kind', ''), '日付': f.get('date', ''),
                               '相手・会議体': f.get('actor') or f.get('body', ''), '内容': f.get('action') or (json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else detail or ''),
                               '結果': f.get('outcome', ''), '出典URL': f['source_url'], '原文の抜粋': f['quote']})
    events.sort(key=lambda r: (r['主題'], r['日付']))
    if events:
        write_csv(OUT / 'events.csv', list(events[0]), events)
    series = [s for s in load_facts('series_media.json') if usable(s)]
    series.sort(key=lambda s: (s['series'], str(s['year'])))
    if series:
        write_csv(OUT / 'series.csv', ['系列', '年', '値', '単位', '出典URL', '原文の抜粋'],
                  [{'系列': s['series'], '年': s['year'], '値': s['value'], '単位': s['unit'], '出典URL': s['source_url'], '原文の抜粋': s['quote']} for s in series])

    by_kind: dict[str, int] = defaultdict(int)
    for w in witnesses:
        by_kind[w['団体の区分']] += 1
    summary = {
        '版': 'media-ledger-v1',
        '参考人の出席（会議×団体）': len(witnesses),
        '団体の区分ごと': dict(sorted(by_kind.items())),
        '放送・通信の所管委員会での出席': sum(1 for w in witnesses if w['放送・通信の所管委員会'] == 'はい'),
        'メディア規制の語を題名に含む成立法': len(bill_rows),
        'うち参考人の出席した会議と結べた法律': sum(1 for b in bill_rows if b['参考人が出席した会議の数']),
        '議員の関与の記録': len(link_rows),
        '制度・審議会の出来事（原本で確認）': len(events),
        '年次系列の値': len(series),
        '限界': [
            '日本に政治へのロビー活動の登録制度は無く、記録できるのは国会会議録・官公庁の公表資料に残った関与だけ。要望の全体は分からない。',
            '参考人の出席は会議録の発言者区分と肩書から数えた。検索語に団体名が出ない発言は拾えない場合がある。',
            '論調・内容・思想の評価はしない。個人名は保存しない。額は付けない。点数・順位には使わない。',
            '政治資金の関係（寄附・パーティー券）は、支払先がメディア関連と一次資料で結べた分だけを別の PR で足す。',
        ],
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False))
    sys.exit(0)
