"""教育・研究の量の指標を公的機関から取得する（task-id education-stats、教育界の帳簿 R32 の入力）。

対象（公式の出典のみ）:
- OECD 科学技術指標 MSTI（DSD_MSTI@DF_MSTI）：研究開発費の対 GDP 比（全体・大学等・政府部門）、千人の就業者当たり研究者数、
  研究者に占める大学等の割合、比べる国の選び方に使う GDP（購買力平価）と就業者数。1995年〜。
- 世界銀行 WDI：教育への政府支出（対 GDP 比、SE.XPD.TOTL.GD.ZS）、高等教育の総就学率（SE.TER.ENRR）。

原本は --raw の下に保存し、URL・sha256・HTTP の結果を manifest.csv に残す（原本は Git に入れない）。
整えた表は --out の下の education-stats.csv に書く。列: 系列,国,区分,年,値,単位,出典URL,備考。
欠けた値は書かない（0で埋めない・補間しない）。OECD は変化率の行（TRANSFORMATION が _Z 以外）を除く。

使い方（リポジトリのルートで）:
  python3 scripts/fetch_education_stats.py
  python3 scripts/fetch_education_stats.py --rebuild   # 取得せず、保存済みの原本から表だけ作り直す
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INTERVAL_SECONDS = 1.1
UA = 'public-interest-lens education-stats (research; GitHub nexus-ai-2045/public-interest-lens)'
SDMX_ACCEPT = 'application/vnd.sdmx.data+csv; charset=utf-8'
OUT_COLUMNS = ['系列', '国', '区分', '年', '値', '単位', '出典URL', '備考']
MANIFEST_COLUMNS = ['url', 'path', 'sha256', 'http', 'fetched_at']
START_YEAR = 1995
# OECD 加盟38か国（比べる相手の基準は OECD 加盟国。設計書 3.0）。ほかの国・地域の集計は表にしない。
OECD_MEMBERS = frozenset(
    'AUS AUT BEL CAN CHL COL CRI CZE DNK EST FIN FRA DEU GRC HUN ISL IRL ISR ITA JPN KOR LVA LTU LUX MEX NLD NZL NOR POL PRT SVK SVN ESP SWE CHE TUR GBR USA'.split())

MSTI_URL = ('https://sdmx.oecd.org/public/rest/data/OECD.STI.STP,DSD_MSTI@DF_MSTI,1.3/all'
            f'?startPeriod={START_YEAR}&dimensionAtObservation=AllDimensions')
WB_URL = 'https://api.worldbank.org/v2/country/all/indicator/{code}?format=json&per_page=20000&date=1990:2025'

# 系列名 -> (MEASURE, UNIT_MEASURE, 単位, 備考)。TRANSFORMATION は _Z（水準）だけを使う。
MSTI_SERIES = {
    '研究開発費（全体、対GDP比）': ('G', 'PT_B1GQ', '%', 'GERD'),
    '研究開発費（大学等、対GDP比）': ('H', 'PT_B1GQ', '%', 'HERD'),
    '研究開発費（政府部門、対GDP比）': ('GV', 'PT_B1GQ', '%', 'GOVERD'),
    '研究者数（千人の就業者当たり）': ('T_RS', '10P3EMP', '人', 'FTE'),
    '研究者に占める大学等の割合': ('H_RS', 'PT_RSH', '%', 'FTE'),
    'GDP（購買力平価）': ('GDP', 'USD_PPP', '百万ドル', '比べる国の選び方に使う'),
    '就業者数': ('TOT_EMP', 'PS', '千人', '比べる国の選び方に使う'),
}
WB_SERIES = {
    'SE.XPD.TOTL.GD.ZS': ('教育への政府支出（対GDP比、世界銀行 WDI）', '%'),
    'SE.TER.ENRR': ('高等教育の総就学率（世界銀行 WDI）', '%'),
}


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fetch(url: str, dest: Path, manifest: Path, root: Path, accept: str = '*/*') -> bytes | None:
    """保存済みならそれを返す。なければ取得して manifest に残す。"""
    if dest.exists():
        return dest.read_bytes()
    time.sleep(INTERVAL_SECONDS)
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body, code = resp.read(), resp.status
    except Exception as exc:  # 取れなかった理由は標準エラーに出し、呼び出し側が「取得できず」とする
        print(f'取得できず: {url} ({exc})', file=sys.stderr)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    new = not manifest.exists()
    with manifest.open('a', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(MANIFEST_COLUMNS)
        try:
            shown = dest.relative_to(root)
        except ValueError:
            shown = dest
        w.writerow([url, str(shown), sha256_bytes(body), code, datetime.now(timezone.utc).isoformat(timespec='seconds')])
    return body


def msti_rows(text: str) -> list[dict]:
    """MSTI の SDMX CSV から、使う系列の水準の行だけを表に直す。国は ISO3、年は整数。"""
    want = {(m, u): name for name, (m, u, _unit, _note) in MSTI_SERIES.items()}
    units = {name: unit for name, (_m, _u, unit, _n) in MSTI_SERIES.items()}
    notes = {name: note for name, (_m, _u, _unit, note) in MSTI_SERIES.items()}
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        name = want.get((r['MEASURE'], r['UNIT_MEASURE']))
        if not name or r['REF_AREA'] not in OECD_MEMBERS or r.get('TRANSFORMATION', '_Z') != '_Z' or r.get('FREQ', 'A') != 'A':
            continue
        if not r['OBS_VALUE'] or not r['TIME_PERIOD'].isdigit():
            continue
        out.append({'系列': name, '国': r['REF_AREA'], '区分': '', '年': int(r['TIME_PERIOD']),
                    '値': r['OBS_VALUE'], '単位': units[name], '出典URL': MSTI_URL, '備考': notes[name]})
    return out


def wb_rows(body: bytes, code: str) -> list[dict]:
    data = json.loads(body)
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return []
    name, unit = WB_SERIES[code]
    url = WB_URL.format(code=code)
    out = []
    for p in data[1]:
        iso = p.get('countryiso3code')
        if iso not in OECD_MEMBERS or p.get('value') is None or not str(p.get('date', '')).isdigit():
            continue
        out.append({'系列': name, '国': iso, '区分': '', '年': int(p['date']), '値': repr(float(p['value'])),
                    '単位': unit, '出典URL': url, '備考': ''})
    return out


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--raw', type=Path, default=root / '.local' / 'education-stats' / 'raw')
    ap.add_argument('--out', type=Path, default=root / 'data' / 'acquired' / 'education')
    ap.add_argument('--rebuild', action='store_true', help='取得せず、保存済みの原本から表だけ作り直す')
    args = ap.parse_args(argv)
    manifest = args.out / 'manifest.csv'
    rows: list[dict] = []
    failed: list[str] = []

    def get(url: str, name: str, accept: str = '*/*') -> bytes | None:
        dest = args.raw / name
        if args.rebuild and not dest.exists():
            return None
        return fetch(url, dest, manifest, root, accept)

    body = get(MSTI_URL, 'oecd-msti.csv', SDMX_ACCEPT)
    if body is None:
        failed.append('OECD MSTI')
    else:
        rows += msti_rows(body.decode('utf-8'))
    for code in WB_SERIES:
        body = get(WB_URL.format(code=code), f'wb-{code}.json')
        if body is None:
            failed.append(code)
        else:
            rows += wb_rows(body, code)
    if not rows:
        print('表にできる行がない', file=sys.stderr)
        return 1
    rows.sort(key=lambda r: (r['系列'], r['国'], r['年']))
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / 'education-stats.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} 行を書いた。取得できなかった原本: {", ".join(failed) or "なし"}')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
