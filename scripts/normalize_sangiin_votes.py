"""参議院の個人別賛否（parse_sangiin_votes_full.py の出力）を、Git に入る大きさに正規化する。

出力（--out-dir の下）:
- votes_index.csv：投票1件1行（投票ID・回次・投票日・議案名・公表と集計の票数・照合・出典URL）
- members.csv：回次ごとの議員と会派（議員ID・回次・議員名・会派）
- ballots/ballots_NNN.csv：回次ごとの個人別賛否（投票ID・議員ID・賛否コード）
  賛否コード：Y=賛成、N=反対、A=投票なし、その他は原文のまま。

使い方: python3 scripts/normalize_sangiin_votes.py --in-dir .local/sangiin-votes-parsed --out-dir data/acquired/sangiin-votes
"""
from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path

CODE = {'賛成': 'Y', '反対': 'N', '投票なし': 'A'}


STANDING_RE = re.compile(r'起立採決により[^<]*')
TITLE_RE = re.compile(r'案件名：.*?<TD[^>]*>(.*?)</TD>', re.S | re.I)


def standing(raw_root: Path, vid: str) -> tuple[str, str] | None:
    """起立採決のページなら（議案名, 結果の文）を返す。個人別の記録はない。"""
    path = raw_root / vid.split('-')[0] / f'{vid}.htm'
    if not path.exists():
        return None
    page = path.read_text(encoding='utf-8', errors='replace')
    m = STANDING_RE.search(page)
    if not m:
        return None
    t = TITLE_RE.search(page)
    title = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', t.group(1)))).strip() if t else ''
    return title, m.group(0).strip()


def vote_id(url: str) -> str:
    return url.rsplit('/', 1)[-1].removesuffix('.htm')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in-dir', type=Path, required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--raw-root', type=Path, help='原本の raw/ 。指定すると、読めなかった投票が起立採決かどうかを確かめる')
    ns = ap.parse_args(argv)
    out = ns.out_dir
    (out / 'ballots').mkdir(parents=True, exist_ok=True)

    with (ns.in_dir / 'summary.csv').open(encoding='utf-8') as fh:
        summary = list(csv.DictReader(fh))
    with (out / 'votes_index.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['投票ID', *summary[0].keys(), '採決方法'])
        for r in summary:
            vid = vote_id(r['出典URL'])
            method = '押しボタン'
            if r['照合'] != 'OK' and ns.raw_root:
                st = standing(ns.raw_root, vid)
                if st:
                    r['議案名'] = r['議案名'] or st[0]
                    r['照合'] = '個人別なし'
                    method = st[1]
            w.writerow([vid, *r.values(), method])

    members: dict[tuple[str, str, str], int] = {}
    total = 0
    for path in sorted(ns.in_dir.glob('votes_*.csv')):
        kaiji = path.stem.split('_')[1]
        rows = []
        with path.open(encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                key = (r['回次'], r['議員名'], r['会派'])
                mid = members.setdefault(key, len(members) + 1)
                rows.append((vote_id(r['出典URL']), mid, CODE.get(r['賛否'], r['賛否'])))
        if not rows:
            continue
        total += len(rows)
        with (out / 'ballots' / f'ballots_{kaiji}.csv').open('w', encoding='utf-8', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['投票ID', '議員ID', '賛否'])
            w.writerows(rows)

    with (out / 'members.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['議員ID', '回次', '議員名', '会派'])
        for (kaiji, name, party), mid in sorted(members.items(), key=lambda kv: kv[1]):
            w.writerow([mid, kaiji, name, party])
    print(f'投票 {len(summary)} 件、個人別 {total} 行、議員×回次 {len(members)} 件')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
