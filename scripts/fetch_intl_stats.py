"""国際比較の統計を公的機関の API から取得する（task-id intl-stats）。

- OECD（SDMX）：消費者物価の COICOP 別年平均（DF_PRICES_ALL。区分は CP01〜CP12、CP045 など、この表にある粒度だけ）
- 世界銀行（WDI）：一人当たり GDP（PPP 実質・実質）、GDP（実質・名目）、産業別の付加価値の GDP 比、人口、労働力

原本は --out の下の raw/ に保存し、URL・sha256・HTTP の結果を manifest.csv に残します（原本は Git に入れない）。
整えた表は --out の下の intl-stats.csv（列: 国,指標,年,値,単位,基準年,出典URL）に書きます。欠けた年は書きません（0で埋めない）。

使い方:
  python3 scripts/fetch_intl_stats.py --out .local/intl-stats
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COUNTRIES = ['JPN', 'USA', 'GBR', 'FRA', 'DEU', 'ITA', 'CAN', 'KOR', 'NLD', 'NOR', 'SWE', 'ESP', 'AUS']
WB_INDICATORS = {
    'NY.GDP.PCAP.PP.KD': '一人当たりGDP（PPP、2021年国際ドル）',
    'NY.GDP.PCAP.KD': '一人当たりGDP（2015年米ドル）',
    'NY.GDP.MKTP.KD': '実質GDP（2015年米ドル）',
    'NY.GDP.MKTP.CD': '名目GDP（米ドル）',
    'NV.IND.MANF.ZS': '製造業の付加価値（GDP比%）',
    'NV.SRV.TOTL.ZS': 'サービス業の付加価値（GDP比%）',
    'NV.AGR.TOTL.ZS': '農林水産業の付加価値（GDP比%）',
    'IT.NET.USER.ZS': 'インターネット利用者（人口比%）',
    'GB.XPD.RSDV.GD.ZS': '研究開発費（GDP比%）',
    'SP.POP.TOTL': '人口',
    'SL.TLF.TOTL.IN': '労働力人口',
}
OECD_CPI = ('https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/'
            + '+'.join(COUNTRIES) + '.A.N.CPI.IX..N._Z?startPeriod=1970')
INTERVAL_SECONDS = 1.1
UA = 'public-interest-lens intl-stats (research; GitHub nexus-ai-2045/public-interest-lens)'


def fetch(url: str, dest: Path, manifest: Path, accept: str = '*/*') -> bytes | None:
    if dest.exists():
        return dest.read_bytes()
    time.sleep(INTERVAL_SECONDS)
    status, body = 0, None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept}), timeout=180) as res:
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
        w.writerow([url, str(dest), hashlib.sha256(body).hexdigest() if body else '', status, datetime.now(timezone.utc).isoformat(timespec='seconds')])
    if body is None or status != 200:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', type=Path, required=True)
    ns = p.parse_args(argv)
    raw, manifest = ns.out / 'raw', ns.out / 'manifest.csv'
    raw.mkdir(parents=True, exist_ok=True)
    rows = []

    body = fetch(OECD_CPI, raw / 'oecd-cpi.csv', manifest, accept='application/vnd.sdmx.data+csv; charset=utf-8')
    if body:
        for r in csv.DictReader(io.StringIO(body.decode('utf-8-sig'))):
            if r['OBS_VALUE']:
                rows.append({'国': r['REF_AREA'], '指標': f'CPI:{r["EXPENDITURE"]}', '年': r['TIME_PERIOD'], '値': r['OBS_VALUE'],
                             '単位': '指数', '基準年': r.get('BASE_PER', ''), '出典URL': OECD_CPI})
    for code, label in WB_INDICATORS.items():
        for country in COUNTRIES:
            url = f'https://api.worldbank.org/v2/country/{country}/indicator/{code}?format=json&per_page=100&date=1960:2025'
            body = fetch(url, raw / 'wb' / f'{code}-{country}.json', manifest)
            if not body:
                continue
            data = json.loads(body)
            for obs in (data[1] or []) if len(data) > 1 else []:
                if obs.get('value') is not None:
                    rows.append({'国': country, '指標': f'WB:{code}', '年': obs['date'], '値': obs['value'], '単位': label, '基準年': '', '出典URL': url})

    with (ns.out / 'intl-stats.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['国', '指標', '年', '値', '単位', '基準年', '出典URL'])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r['指標'], r['国'], r['年'])))
    print(f'{len(rows)}行')
    return 0


if __name__ == '__main__':
    sys.exit(main())
