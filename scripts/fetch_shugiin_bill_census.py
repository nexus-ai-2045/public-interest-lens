"""衆議院「議案情報」から、回次ごとの議案一覧と、成立した法律案の審議経過を取得する（task-id bill-census-full）。

衆議院のサイトにあるのは第142回国会以降だけです（第141回以前の kaiji ページは 404）。
原本は --out の下の raw/ に保存し、URL・sha256・HTTP の結果を manifest.csv に残します。原本は Git に入れません。

使い方:
  python3 scripts/fetch_shugiin_bill_census.py --out .local/bill-census-full --from 142 --to 222
  python3 scripts/fetch_shugiin_bill_census.py --out .local/bill-census-full --keika   # 成立分の経過ページも取る
  python3 scripts/fetch_shugiin_bill_census.py --out .local/bill-census-full --parse-only  # 保存済みの原本から CSV だけ作り直す
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = 'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/'
INTERVAL_SECONDS = 1.1
KINDS = ('衆法', '参法', '閣法')
UA = 'public-interest-lens bill-census (research; contact via GitHub nexus-ai-2045/public-interest-lens)'


def fetch(url: str, dest: Path, manifest: Path) -> bytes | None:
    """1件取得して保存し、manifest に記録する。既に保存済みなら取得しない。"""
    if dest.exists():
        return dest.read_bytes()
    time.sleep(INTERVAL_SECONDS)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    status, body = 0, None
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            status, body = res.status, res.read()
    except urllib.error.HTTPError as e:
        status = e.code
    except (urllib.error.URLError, TimeoutError) as e:
        status = -1
        print(f'接続できない: {url} {e}', file=sys.stderr)
    new = not manifest.exists()
    with manifest.open('a', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['url', 'path', 'sha256', 'http', 'fetched_at'])
        sha = hashlib.sha256(body).hexdigest() if body else ''
        w.writerow([url, str(dest), sha, status, datetime.now(timezone.utc).isoformat(timespec='seconds')])
    if body is None or status != 200:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return body


def text(fragment: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', fragment))).strip()


def parse_listing(page: str, session: int, url: str) -> list[dict]:
    """kaiji ページの「衆法の一覧」「参法の一覧」「閣法の一覧」の表を行に分ける。"""
    rows = []
    parts = re.split(r'<caption[^>]*>(.*?)</caption>', page, flags=re.S)
    for caption, body in zip(parts[1::2], parts[2::2]):
        kind = text(caption).replace('の一覧', '')
        if kind not in KINDS:
            continue
        body = body.split('</table>', 1)[0]
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', body, flags=re.S):
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S)
            if len(tds) < 4:
                continue
            keika = re.search(r'href="\./keika/([^"]+)"', tr)
            rows.append({
                '掲載回次': session, '種別': kind, '提出回次': text(tds[0]), '番号': text(tds[1]),
                '議案件名': text(tds[2]), '審議状況': text(tds[3]),
                '経過URL': BASE + 'keika/' + keika.group(1) if keika else '', '出典URL': url,
            })
    return rows


def parse_keika(page: str) -> dict[str, str]:
    """経過ページの「項目／内容」の表を、項目名→内容の辞書にする。"""
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', page, flags=re.S):
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.S)
        if len(cells) == 2:
            key, value = text(cells[0]), text(cells[1])
            if key and key != '項目':
                out[key] = value
    return out


def split_pair(value: str) -> tuple[str, str]:
    """「平成28年 1月 4日 ／ 法務」のような「日付／内容」を2つに分ける。"""
    a, _, b = value.partition('／')
    return a.strip(), b.strip()


KEIKA_COLUMNS = ['議案提出者', '衆議院付託年月日／衆議院付託委員会', '衆議院審議終了年月日／衆議院審議結果', '衆議院審議時賛成会派',
                 '衆議院審議時反対会派', '参議院付託年月日／参議院付託委員会', '参議院審議終了年月日／参議院審議結果', '公布年月日／法律番号']


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--from', dest='first', type=int, default=142)
    p.add_argument('--to', dest='last', type=int, default=222)
    p.add_argument('--keika', action='store_true')
    p.add_argument('--parse-only', action='store_true')
    ns = p.parse_args(argv)
    raw, manifest = ns.out / 'raw', ns.out / 'manifest.csv'

    listing = []
    for session in range(ns.first, ns.last + 1):
        url = f'{BASE}kaiji{session:03d}.htm'
        dest = raw / f'kaiji{session:03d}.htm'
        body = dest.read_bytes() if ns.parse_only and dest.exists() else (None if ns.parse_only else fetch(url, dest, manifest))
        if body is None:
            print(f'第{session}回: 取得できない', file=sys.stderr)
            continue
        rows = parse_listing(body.decode('cp932', errors='replace'), session, url)
        listing.extend(rows)
        print(f'第{session}回: {len(rows)}行（成立 {sum(r["審議状況"] == "成立" for r in rows)}）')

    fields = ['掲載回次', '種別', '提出回次', '番号', '議案件名', '審議状況', '経過URL', '出典URL']
    with (ns.out / 'listing.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(listing)

    # 同じ議案は複数の回次に載る（継続審査）。成立は (種別, 提出回次, 番号) で1件に数える。
    enacted = {}
    for r in listing:
        if r['審議状況'] == '成立':
            enacted.setdefault((r['種別'], r['提出回次'], r['番号']), r)
    print(f'成立（重複を除く）: {len(enacted)}件')

    out_rows = []
    for (kind, sub, num), r in sorted(enacted.items(), key=lambda kv: (int(kv[0][1] or 0), kv[0][0], int(kv[0][2] or 0))):
        row = {'回次': r['掲載回次'], '種別': kind, '提出回次': sub, '番号': num, '題名': r['議案件名'],
               '新規か改正か': '改正' if re.search(r'の一部を改正する法律案$', r['議案件名']) else ''}
        if ns.keika and r['経過URL']:
            dest = raw / 'keika' / (r['経過URL'].rsplit('/', 1)[1])
            body = dest.read_bytes() if dest.exists() else (None if ns.parse_only else fetch(r['経過URL'], dest, manifest))
            kv = parse_keika(body.decode('cp932', errors='replace')) if body else {}
            row['提出者'] = kv.get('議案提出者', '')
            row['付託日_衆'], row['付託委員会_衆'] = split_pair(kv.get('衆議院付託年月日／衆議院付託委員会', ''))
            row['議決日_衆'], row['議決結果_衆'] = split_pair(kv.get('衆議院審議終了年月日／衆議院審議結果', ''))
            row['賛成会派_衆'] = kv.get('衆議院審議時賛成会派', '')
            row['反対会派_衆'] = kv.get('衆議院審議時反対会派', '')
            row['付託日_参'], row['付託委員会_参'] = split_pair(kv.get('参議院付託年月日／参議院付託委員会', ''))
            row['議決日_参'], row['議決結果_参'] = split_pair(kv.get('参議院審議終了年月日／参議院審議結果', ''))
            row['公布日'], row['法律番号'] = split_pair(kv.get('公布年月日／法律番号', ''))
            row['経過URL'] = r['経過URL']
            (ns.out / 'keika-json').mkdir(parents=True, exist_ok=True)
            (ns.out / 'keika-json' / f'{kind}-{sub}-{num}.json').write_text(json.dumps(kv, ensure_ascii=False, indent=1), encoding='utf-8')
        row['出典URL'] = r['出典URL']
        out_rows.append(row)

    cols = list(dict.fromkeys(k for row in out_rows for k in row))
    with (ns.out / 'enacted.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    return 0


if __name__ == '__main__':
    sys.exit(main())
