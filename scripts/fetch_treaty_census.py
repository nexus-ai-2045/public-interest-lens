"""衆議院「議案情報」から、条約と承認案件（承認を求めるの件）の一覧と審議経過を取得する（task-id treaty-census）。

法律案（閣法・衆法・参法）は fetch_shugiin_bill_census.py が取る。国会は条約も承認の議決をするので、その分をここで取る。
  条約  条約の締結について承認を求めるの件（経済連携協定・租税条約・投資協定・航空協定・防衛協定など）
  承認  法律の規定に基づく承認を求めるの件（例：特定船舶の入港禁止の実施）
承諾（予備費の使用の承諾）・決算・予算は別の財政の帳簿の範囲なので取らない（一覧の件数だけ数える）。
条約は国会が修正できないので、結果は承認・不承認・未了のどれかになる。
原本は --out の下の raw/ に保存し、manifest.csv に URL・sha256・HTTP の結果を残す。原本は Git に入れない。

使い方:
  python3 scripts/fetch_treaty_census.py --out .local/treaty-census --from 142 --to 222
  python3 scripts/fetch_treaty_census.py --out .local/treaty-census --parse-only --csv data/acquired/treaty-census/treaties.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_shugiin_bill_census import BASE, fetch, parse_keika, split_pair, text  # noqa: E402

KINDS = ('条約', '承認')
COLUMNS = ['種別', '提出回次', '番号', '題名', '審議状況', '提出者', '付託日_衆', '付託委員会_衆', '議決日_衆', '議決結果_衆',
           '賛成会派_衆', '反対会派_衆', '付託日_参', '付託委員会_参', '議決日_参', '議決結果_参', '経過URL', '出典URL']


def parse_listing(page: str, session: int, url: str) -> tuple[list[dict], dict[str, int]]:
    """kaiji ページの条約・承認の表を行に分ける。2つ目は他の表（承諾など）の行数。"""
    rows, other = [], {}
    parts = re.split(r'<caption[^>]*>(.*?)</caption>', page, flags=re.S | re.I)
    for caption, body in zip(parts[1::2], parts[2::2]):
        kind = text(caption).replace('の一覧', '')
        body = re.split(r'</table>', body, maxsplit=1, flags=re.I)[0]
        trs = re.findall(r'<tr[^>]*>(.*?)</tr>', body, flags=re.S | re.I)
        tds_rows = [re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S | re.I) for tr in trs]
        tds_rows = [t for t in tds_rows if len(t) >= 4]
        if kind not in KINDS:
            other[kind] = len(tds_rows)
            continue
        for tr, tds in zip([t for t in trs if len(re.findall(r'<td', t)) >= 4], tds_rows):
            keika = re.search(r'href="\./keika/([^"]+)"', tr)
            rows.append({
                '掲載回次': session, '種別': kind, '提出回次': text(tds[0]), '番号': text(tds[1]), '題名': text(tds[2]),
                '審議状況': text(tds[3]), '経過URL': BASE + 'keika/' + keika.group(1) if keika else '', '出典URL': url,
            })
    return rows, other


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--csv', type=Path, help='結果の CSV（既定は --out/treaties.csv）')
    p.add_argument('--from', dest='first', type=int, default=142)
    p.add_argument('--to', dest='last', type=int, default=222)
    p.add_argument('--parse-only', action='store_true')
    ns = p.parse_args(argv)
    raw, manifest = ns.out / 'raw', ns.out / 'manifest.csv'
    raw.mkdir(parents=True, exist_ok=True)

    listing, skipped = [], {}
    for session in range(ns.first, ns.last + 1):
        dest = raw / f'kaiji{session:03d}.htm'
        url = f'{BASE}kaiji{session:03d}.htm'
        body = dest.read_bytes() if dest.exists() else (None if ns.parse_only else fetch(url, dest, manifest))
        if body is None:
            print(f'第{session}回: 取得できない', file=sys.stderr)
            continue
        rows, other = parse_listing(body.decode('cp932', errors='replace'), session, url)
        listing.extend(rows)
        for k, v in other.items():
            skipped[k] = skipped.get(k, 0) + v

    # 継続審査で複数の回次に載る。(種別, 提出回次, 番号) で1件にし、最後に載った回次の状態を取る。
    latest = {}
    for r in listing:
        latest[(r['種別'], r['提出回次'], r['番号'])] = r

    out_rows = []
    for (kind, sub, num), r in sorted(latest.items(), key=lambda kv: (int(kv[0][1] or 0), kv[0][0], int(kv[0][2] or 0))):
        row = {c: '' for c in COLUMNS}
        row.update({'種別': kind, '提出回次': sub, '番号': num, '題名': r['題名'], '審議状況': r['審議状況'],
                    '経過URL': r['経過URL'], '出典URL': r['出典URL']})
        if r['経過URL']:
            dest = raw / 'keika' / r['経過URL'].rsplit('/', 1)[1]
            body = dest.read_bytes() if dest.exists() else (None if ns.parse_only else fetch(r['経過URL'], dest, manifest))
            kv = parse_keika(body.decode('cp932', errors='replace')) if body else {}
            row['提出者'] = kv.get('議案提出者', '')
            row['付託日_衆'], row['付託委員会_衆'] = split_pair(kv.get('衆議院付託年月日／衆議院付託委員会', ''))
            row['議決日_衆'], row['議決結果_衆'] = split_pair(kv.get('衆議院審議終了年月日／衆議院審議結果', ''))
            row['賛成会派_衆'] = kv.get('衆議院審議時賛成会派', '')
            row['反対会派_衆'] = kv.get('衆議院審議時反対会派', '')
            row['付託日_参'], row['付託委員会_参'] = split_pair(kv.get('参議院付託年月日／参議院付託委員会', ''))
            row['議決日_参'], row['議決結果_参'] = split_pair(kv.get('参議院審議終了年月日／参議院審議結果', ''))
        out_rows.append(row)

    csv_path = ns.csv or ns.out / 'treaties.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    by_kind = {k: sum(r['種別'] == k for r in out_rows) for k in KINDS}
    print(f'条約・承認 {len(out_rows)}件 {by_kind}／取らなかった表（延べ行数）{skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
