"""メディア関係団体の国会での参考人出席の取得（メディアの帳簿の1本目）。

国会会議録検索システムの API（speech）で、発言者の役割が「参考人」の発言から、肩書にメディア関係団体の名前を含むものを集める。
個人名は保存しない（所属団体・肩書の区分だけ）。会議ごと・団体ごとに1行にまとめる。論調・内容の評価はしない。
- 団体の区分：日本民間放送連盟／日本新聞協会／日本放送協会／日本ケーブルテレビ連盟／日本雑誌協会／放送局・新聞社・通信社（社名のある肩書）
- 保存先：data/acquired/media-ledger/diet-witnesses.csv

使い方（リポジトリのルートで）: python3 scripts/fetch_media_witnesses.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/acquired/media-ledger/diet-witnesses.csv'
API = 'https://kokkai.ndl.go.jp/api/speech'
# 検索語（本文に団体名が出る参考人の発言を拾う）。肩書の正規表現で絞り直すので、広めに取る。
QUERIES = ('日本民間放送連盟', '民間放送連盟', '日本新聞協会', '日本放送協会', 'ケーブルテレビ連盟', '雑誌協会', '新聞社', '放送局', '通信社', '民放')
# 肩書 → 団体の区分。上から先に当たったものを採る。
KINDS = (
    ('日本民間放送連盟', re.compile(r'民間放送連盟|民放連')),
    ('日本新聞協会', re.compile(r'新聞協会')),
    ('日本放送協会', re.compile(r'日本放送協会|ＮＨＫ|NHK')),
    ('日本ケーブルテレビ連盟', re.compile(r'ケーブルテレビ連盟')),
    ('日本雑誌協会', re.compile(r'雑誌協会')),
    ('放送局・新聞社・通信社', re.compile(r'(放送|テレビ|新聞|通信社|共同通信|時事通信)[^、]{0,12}(株式会社|㈱|社)|(株式会社|㈱)[^、]{0,12}(放送|テレビ|新聞)|(新聞|放送|通信)社')),
)
HEADER = ['会議ID', '国会回次', '日付', '院', '会議名', '団体の区分', '肩書', '案件', '会議録URL']
MEETING_API = 'https://kokkai.ndl.go.jp/api/meeting'
AGENDA = re.compile(r'本日の会議に付した案件(.{0,600}?)(?:─{3,}|$)', re.S)


def get(params: dict, tries: int = 4) -> dict:
    return get_url(f'{API}?{urllib.parse.urlencode(params)}', tries)


def get_url(url: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # 通信の一時的な失敗は間を置いて取り直す
            if i == tries - 1:
                raise
            print(f'  retry {i + 1}: {e}', file=sys.stderr)
            time.sleep(2 * (i + 1))
    raise RuntimeError('unreachable')


def classify(position: str) -> str | None:
    for kind, pat in KINDS:
        if pat.search(position or ''):
            return kind
    return None


def agenda(issue_id: str) -> str:
    """会議録の冒頭にある「本日の会議に付した案件」の記載を、空白をつめて返す。"""
    res = get_url(f'{MEETING_API}?{urllib.parse.urlencode({"issueID": issue_id, "recordPacking": "json", "maximumRecords": 1})}')
    recs = res.get('meetingRecord') or []
    if not recs or not recs[0].get('speechRecord'):
        return ''
    head = recs[0]['speechRecord'][0].get('speech', '')
    m = AGENDA.search(head)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''


def collect() -> list[dict[str, str]]:
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for q in QUERIES:
        start = 1
        while True:
            res = get({'any': q, 'speakerRole': '参考人', 'maximumRecords': 100, 'startRecord': start, 'recordPacking': 'json'})
            recs = res.get('speechRecord') or []
            for s in recs:
                kind = classify(s.get('speakerPosition', ''))
                if not kind:
                    continue
                key = (s['issueID'], kind)
                if key in rows:
                    continue
                rows[key] = {
                    '会議ID': s['issueID'], '国会回次': str(s.get('session', '')), '日付': s['date'], '院': s['nameOfHouse'], '会議名': s['nameOfMeeting'],
                    '団体の区分': kind, '肩書': s['speakerPosition'], '案件': '',
                    '会議録URL': f"https://kokkai.ndl.go.jp/txt/{s['issueID']}",
                }
            nxt = res.get('nextRecordPosition')
            print(f'{q}: {start}..{start + len(recs) - 1} / {res.get("numberOfRecords")}', file=sys.stderr)
            if not nxt:
                break
            start = nxt
            time.sleep(0.3)
    # 日本放送協会（予算・決算の承認審議）以外は、法案との対応を見るため会議の案件も取る
    for r in rows.values():
        if r['団体の区分'] != '日本放送協会':
            r['案件'] = agenda(r['会議ID'])
            time.sleep(0.2)
    return sorted(rows.values(), key=lambda r: (r['日付'], r['会議ID'], r['団体の区分']))


def main() -> int:
    rows = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} 行 → {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
