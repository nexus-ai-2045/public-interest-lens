"""OECD の産業別付加価値（国民経済計算 表6）を取得する（task-id oecd-industry）。

loss-rule-v1 が比較国の「同じ定義の分野の実質付加価値」を必要とするための取得です。
- データフロー: OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE6,2.0（Annual value added and its components by economic activity）
- 取引 B1G（総付加価値）、部門 S1（経済全体）、単位 XDC（自国通貨）
- 価格: V=名目（current prices）、L=連鎖実質（chain linked volume）、LR=連鎖実質（再基準化）
- 産業: _T=全産業、J=情報通信、I=宿泊・飲食、K=金融・保険、H=運輸・保管（ISIC Rev.4）

原本は raw ディレクトリに国ごとに保存し、URL・sha256・HTTP の結果を manifest.csv に残します（原本は Git に入れない）。
整えた表は industry_va.csv（列: 国,産業,指標,価格,年,値,単位,基準年,出典URL）に書きます。
欠けた年は書きません（0で埋めない・補間しない）。

使い方:
  python3 scripts/fetch_oecd_industry.py
  python3 scripts/fetch_oecd_industry.py --rebuild   # 取得せず、保存済みの原本から表だけ作り直す
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COUNTRIES = ['JPN', 'USA', 'GBR', 'FRA', 'DEU', 'ITA', 'CAN', 'KOR', 'NLD', 'NOR', 'SWE', 'ESP', 'AUS']
ACTIVITIES = {
    '_T': '全産業',
    'J': '情報通信（ISIC Rev.4 J）',
    'I': '宿泊・飲食サービス（ISIC Rev.4 I）',
    'K': '金融・保険（ISIC Rev.4 K）',
    'H': '運輸・保管（ISIC Rev.4 H）',
}
PRICES = {
    'V': '名目（current prices）',
    'L': '連鎖実質（chain linked volume）',
    'LR': '連鎖実質・再基準化（chain linked volume rebased）',
}
BASE = 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE6,2.0/'
ACCEPT = 'application/vnd.sdmx.data+csv; charset=utf-8'
INTERVAL_SECONDS = 1.1
UA = 'public-interest-lens oecd-industry (research; GitHub nexus-ai-2045/public-interest-lens)'
OUT_COLUMNS = ['国', '産業', '指標', '価格', '年', '値', '単位', '基準年', '出典URL']
MANIFEST_COLUMNS = ['url', 'path', 'sha256', 'http', 'fetched_at']


def build_url(country: str) -> str:
    """次元の順: FREQ.REF_AREA.SECTOR.COUNTERPART.TRANSACTION.INSTR_ASSET.ACTIVITY.EXPENDITURE.UNIT.PRICE_BASE.TRANSFORMATION.TABLE"""
    key = '.'.join(['A', country, 'S1', 'S1', 'B1G', '_Z', '+'.join(ACTIVITIES), '_Z', 'XDC', '+'.join(PRICES), 'N', ''])
    return f'{BASE}{key}?startPeriod=1970'


def unit_label(currency: str, unit_mult: str) -> str:
    mult = {'0': '', '3': '千', '6': '百万', '9': '十億'}.get(unit_mult)
    if mult is None:
        raise ValueError(f'未知の UNIT_MULT: {unit_mult!r}')
    return f'{mult}{currency}'


def parse_table(text: str, url: str) -> list[dict[str, str]]:
    """SDMX-CSV（labels=id）を整えた行にする。値が空の行は捨てる。同じキーで値が食い違えば止める。"""
    rows: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for rec in csv.DictReader(io.StringIO(text.lstrip('﻿'))):
        value = (rec.get('OBS_VALUE') or '').strip()
        if not value:
            continue
        if rec['TRANSACTION'] != 'B1G' or rec['SECTOR'] != 'S1' or rec['UNIT_MEASURE'] != 'XDC':
            continue
        act, price = rec['ACTIVITY'], rec['PRICE_BASE']
        if act not in ACTIVITIES or price not in PRICES:
            continue
        key = (rec['REF_AREA'], act, price, rec['TIME_PERIOD'])
        row = {
            '国': rec['REF_AREA'],
            '産業': act,
            '指標': '総付加価値（B1G）',
            '価格': price,
            '年': rec['TIME_PERIOD'],
            '値': value,
            '単位': unit_label(rec['CURRENCY'], rec['UNIT_MULT']),
            '基準年': (rec.get('REF_YEAR_PRICE') or '').strip() if price != 'V' else '',
            '出典URL': url,
        }
        if key in rows and rows[key]['値'] != value:
            raise ValueError(f'同じキーで値が食い違う: {key}')
        rows[key] = row
    return sorted(rows.values(), key=lambda r: (r['国'], r['産業'], r['価格'], int(r['年'])))


def fetch(url: str, dest: Path, manifest: Path, root: Path) -> bytes | None:
    if dest.exists():
        return dest.read_bytes()
    time.sleep(INTERVAL_SECONDS)
    status, body = 0, None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': ACCEPT}), timeout=180) as res:
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
            w.writerow(MANIFEST_COLUMNS)
        w.writerow([url, dest.relative_to(root).as_posix(), hashlib.sha256(body).hexdigest() if body else '', status,
                    datetime.now(timezone.utc).isoformat(timespec='seconds')])
    if body is None or status != 200:
        print(f'取得できない: {url} http={status}', file=sys.stderr)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return body


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--raw', type=Path, default=root / '.local' / 'oecd-industry' / 'raw')
    p.add_argument('--out', type=Path, default=root / 'data' / 'acquired' / 'oecd-industry')
    p.add_argument('--rebuild', action='store_true', help='取得せず、保存済みの原本から表を作り直す')
    ns = p.parse_args(argv)
    ns.raw.mkdir(parents=True, exist_ok=True)
    ns.out.mkdir(parents=True, exist_ok=True)
    manifest = ns.out / 'manifest.csv'
    failed = []
    all_rows: list[dict[str, str]] = []
    for c in COUNTRIES:
        url = build_url(c)
        dest = ns.raw / f'table6-{c}.csv'
        if ns.rebuild:
            body = dest.read_bytes() if dest.exists() else None
        else:
            body = fetch(url, dest, manifest, root)
        if body is None:
            failed.append(c)
            continue
        all_rows.extend(parse_table(body.decode('utf-8'), url))
    with (ns.out / 'industry_va.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(all_rows)
    print(f'{len(all_rows)} 行を書きました。取得できなかった国: {failed or "なし"}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
