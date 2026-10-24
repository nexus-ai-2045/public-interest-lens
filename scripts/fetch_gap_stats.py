"""impact-v1 で判定できなかった指標の不足系列を公的機関から取得する（task-id gap-stats）。

対象（公式の出典のみ。民間データは使わない）:
- 雇用の流動性（国際）: OECD 勤続年数別就業者割合（DSD_TENURE@DF_TENURE_FREQ。勤続1年未満・10年以上）
- 賃金（国際）: OECD 平均年間賃金（DSD_EARNINGS@AV_AN_WAGE。実質・名目、購買力平価ドル・自国通貨）
- 電子申請率: 総務省 行政手続オンライン化等の状況（平成20〜26年度の報道資料 PDF）と情報通信白書（平成27年度）
- ブロードバンド普及率: OECD ブロードバンド（DF_BB_TEL_DATABASE。2009年〜）、世界銀行 IT.NET.BBND.P2（固定ブロードバンド契約数、100人当たり）
- 利用件数（交通）: 国土交通省 空港管理状況調書（空港別乗降客数、暦年・年度）、鉄道統計年報「運輸成績の推移」（年度）
- 不良債権比率: 世界銀行 GFDD.SI.02（銀行の不良債権比率。日本は1998年から）

原本は --raw の下に保存し、URL・sha256・HTTP の結果を manifest.csv に残す（原本は Git に入れない）。
整えた表は --out の下に書く。列: 系列,国,区分,年,値,単位,出典URL,備考。
欠けた値は書かない（0で埋めない・補間しない）。表に落とせなかったものは status.csv に「取得できず」と理由を書く。

使い方（リポジトリのルートで。xls/xlsx と PDF を読むため xlrd・openpyxl・pdfplumber が要る。仮想環境はリポジトリの外に作る）:
  python3 scripts/fetch_gap_stats.py
  python3 scripts/fetch_gap_stats.py --rebuild   # 取得せず、保存済みの原本から表だけ作り直す
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COUNTRIES = ['JPN', 'USA', 'GBR', 'FRA', 'DEU', 'ITA', 'CAN', 'KOR', 'NLD', 'NOR', 'SWE', 'ESP', 'AUS']
INTERVAL_SECONDS = 1.1
UA = 'public-interest-lens gap-stats (research; GitHub nexus-ai-2045/public-interest-lens)'
SDMX_ACCEPT = 'application/vnd.sdmx.data+csv; charset=utf-8'
OUT_COLUMNS = ['系列', '国', '区分', '年', '値', '単位', '出典URL', '備考']
STATUS_COLUMNS = ['系列', '対象', '状況', '理由', '出典URL']
MANIFEST_COLUMNS = ['url', 'path', 'sha256', 'http', 'fetched_at']

OECD_BASE = 'https://sdmx.oecd.org/public/rest/data/'
TENURE_URL = (OECD_BASE + 'OECD.ELS.SAE,DSD_TENURE@DF_TENURE_FREQ,1.0/'
              + '+'.join(COUNTRIES) + '.TENURE_EMP+TENURE_EMP_DEP..F+M+_T._T.M_LT12+Y_GE10.A?startPeriod=1990')
WAGE_URL = OECD_BASE + 'OECD.ELS.SAE,DSD_EARNINGS@AV_AN_WAGE,1.0/?startPeriod=1990'
BB_URL = OECD_BASE + 'OECD.STI.DEP,DSD_BB_DATABASE@DF_BB_TEL_DATABASE,2.0/?startPeriod=1990'
WB_COUNTRIES = ';'.join(COUNTRIES)
WB_URL = 'https://api.worldbank.org/v2/country/' + WB_COUNTRIES + '/indicator/{code}?format=json&per_page=2000&date=1960:2025'
AIRPORT_NEW = 'https://www.mlit.go.jp/koku/content/002018023.xlsx'  # 暦年・年度別空港管理状況調書（H28～R7）
AIRPORT_OLD = 'https://www.mlit.go.jp/common/001475245.xls'  # 暦年・年度別空港管理状況調書（H19～H28）
RAIL_URL = 'https://www.mlit.go.jp/tetudo/content/001977439.xls'  # 鉄道統計年報 令和5年度（22）運輸成績の推移
EGOV_DOCS = [
    ('h20', 'https://www.soumu.go.jp/main_content/000031924.pdf', '平成20年度における行政手続オンライン化等の状況（平成21年8月7日）'),
    ('h22', 'https://www.soumu.go.jp/main_content/000151031.pdf', '平成22年度における行政手続オンライン化等の状況（平成24年3月21日）'),
    ('h24', 'https://www.soumu.go.jp/main_content/000265974.pdf', '平成24年度における行政手続オンライン化等の状況（平成25年12月25日）'),
    ('h25', 'https://www.soumu.go.jp/main_content/000328257.pdf', '平成25年度における行政手続オンライン化等の状況（平成26年12月22日）'),
    ('h26', 'https://www.soumu.go.jp/main_content/000391722.pdf', '平成26年度における行政手続オンライン化等の状況（平成27年12月25日）'),
]
WHITEPAPER_H29 = 'https://www.soumu.go.jp/johotsusintokei/whitepaper/ja/h29/html/nc262610.html'
WB_SERIES = {
    'GFDD.SI.02': ('銀行の不良債権比率（総貸出に対する%、世界銀行 GFDD）', '%'),
    'IT.NET.BBND.P2': ('固定ブロードバンド契約数（100人当たり、世界銀行 WDI）', '契約数/100人'),
}

TENURE_LABELS = {'M_LT12': '勤続1年未満', 'Y_GE10': '勤続10年以上'}
TENURE_MEASURE_LABELS = {'TENURE_EMP': '就業者全体', 'TENURE_EMP_DEP': '雇用者（被用者）'}
SEX_LABELS = {'_T': '男女計', 'F': '女性', 'M': '男性'}


# ---------- 共通 ----------

def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fetch(url: str, dest: Path, manifest: Path, root: Path, accept: str = '*/*') -> bytes | None:
    """保存済みならそれを返す。なければ取得して manifest に残す（1秒以上あけて取得）。"""
    if dest.exists():
        return dest.read_bytes()
    time.sleep(INTERVAL_SECONDS)
    status, body = 0, None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept}), timeout=300) as res:
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
        w.writerow([url, dest.relative_to(root).as_posix(), sha256_bytes(body) if body else '', status,
                    datetime.now(timezone.utc).isoformat(timespec='seconds')])
    if body is None or status != 200:
        print(f'取得できない: {url} http={status}', file=sys.stderr)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return body


def is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return False


def as_text(v) -> str:
    return '' if v is None else str(v).strip()


def jp_count(s: str) -> int:
    """「4億9,030万3,745」のような件数を整数にする。"""
    s = s.replace(',', '').replace('件', '')
    m = re.fullmatch(r'(?:(\d+)億)?(?:(\d+)万)?(\d+)?', s)
    if not m or not any(m.groups()):
        raise ValueError(f'件数を読めない: {s!r}')
    oku, man, rest = (int(g) if g else 0 for g in m.groups())
    return oku * 100_000_000 + man * 10_000 + rest


def sdmx_rows(text: str):
    return csv.DictReader(io.StringIO(text.lstrip('﻿')))


def put_unique(rows: dict, key, row: dict) -> None:
    if key in rows and rows[key]['値'] != row['値']:
        raise ValueError(f'同じキーで値が食い違う: {key}')
    rows[key] = row


def sorted_rows(rows) -> list[dict]:
    return sorted(rows, key=lambda r: (r['系列'], r['国'], r['区分'], int(r['年'])))


# ---------- OECD ----------

def parse_tenure(text: str, url: str) -> list[dict]:
    rows: dict = {}
    for rec in sdmx_rows(text):
        v = as_text(rec.get('OBS_VALUE'))
        if not v or rec['REF_AREA'] not in COUNTRIES or rec['AGE'] != '_T':
            continue
        if rec['TENURE'] not in TENURE_LABELS or rec['MEASURE'] not in TENURE_MEASURE_LABELS or rec['SEX'] not in SEX_LABELS:
            continue
        if rec['UNIT_MEASURE'] != 'PT_POP_SUB':
            raise ValueError(f'未知の UNIT_MEASURE: {rec["UNIT_MEASURE"]!r}')
        div = f'{TENURE_LABELS[rec["TENURE"]]}／{TENURE_MEASURE_LABELS[rec["MEASURE"]]}／{SEX_LABELS[rec["SEX"]]}'
        row = {'系列': '勤続年数別就業者割合（OECD）', '国': rec['REF_AREA'], '区分': div, '年': rec['TIME_PERIOD'], '値': v,
               '単位': '%（OECD単位 PT_POP_SUB。年齢計）', '出典URL': url,
               '備考': 'OECD DSD_TENURE@DF_TENURE_FREQ。勤続1年未満の割合が高いほど労働移動が大きい'}
        put_unique(rows, (rec['REF_AREA'], div, rec['TIME_PERIOD']), row)
    return sorted_rows(rows.values())


def money_unit(unit: str, mult: str) -> str:
    if mult not in ('0', ''):
        raise ValueError(f'未知の UNIT_MULT: {mult!r}')
    return {'USD_PPP': '米ドル（購買力平価）'}.get(unit, unit)


def parse_wages(text: str, url: str) -> list[dict]:
    rows: dict = {}
    for rec in sdmx_rows(text):
        v = as_text(rec.get('OBS_VALUE'))
        if not v or rec['REF_AREA'] not in COUNTRIES:
            continue
        if rec['MEASURE'] != 'WG' or rec['PAY_PERIOD'] != 'A' or rec['AGGREGATION_OPERATION'] != 'MEAN' or rec['SEX'] != '_Z':
            continue
        price = rec['PRICE_BASE']
        if price == 'Q':
            div = f'実質（{as_text(rec.get("BASE_PER"))}年価格）／{money_unit(rec["UNIT_MEASURE"], as_text(rec.get("UNIT_MULT")))}'
        elif price == 'V':
            div = f'名目／{money_unit(rec["UNIT_MEASURE"], as_text(rec.get("UNIT_MULT")))}'
        else:
            continue
        row = {'系列': '平均年間賃金（OECD）', '国': rec['REF_AREA'], '区分': div, '年': rec['TIME_PERIOD'], '値': v,
               '単位': money_unit(rec['UNIT_MEASURE'], as_text(rec.get('UNIT_MULT'))) + '／年', '出典URL': url,
               '備考': 'OECD DSD_EARNINGS@AV_AN_WAGE（平均年間賃金。経済全体）'}
        put_unique(rows, (rec['REF_AREA'], div, rec['TIME_PERIOD']), row)
    return sorted_rows(rows.values())


def parse_broadband(text: str, url: str) -> list[dict]:
    rows: dict = {}
    kinds = {('FBB', '100HB'): ('固定ブロードバンド契約数（人口100人当たり、OECD）', '契約数/100人'),
             ('FBB', 'SB'): ('固定ブロードバンド契約数（OECD）', '契約数'),
             ('MBB', '100HB'): ('モバイルブロードバンド契約数（人口100人当たり、OECD）', '契約数/100人')}
    for rec in sdmx_rows(text):
        v = as_text(rec.get('OBS_VALUE'))
        if not v or rec['REF_AREA'] not in COUNTRIES:
            continue
        if rec['FREQ'] != 'A' or rec['MEASURE'] != 'SUB' or rec['NETWORK_ACCESS_MODE'] != '_T' or rec['NETWORK_SPEED'] != '_Z':
            continue
        kind = kinds.get((rec['NETWORK_TYPE'], rec['UNIT_MEASURE']))
        if kind is None:
            continue
        if rec['UNIT_MEASURE'] == 'SB' and as_text(rec.get('UNIT_MULT')) not in ('0', ''):
            raise ValueError(f'未知の UNIT_MULT: {rec.get("UNIT_MULT")!r}')
        row = {'系列': kind[0], '国': rec['REF_AREA'], '区分': 'アクセス方式計・速度区分なし', '年': rec['TIME_PERIOD'], '値': v,
               '単位': kind[1], '出典URL': url, '備考': 'OECD DSD_BB_DATABASE@DF_BB_TEL_DATABASE（年次）'}
        put_unique(rows, (kind[0], rec['REF_AREA'], rec['TIME_PERIOD']), row)
    return sorted_rows(rows.values())


# ---------- 世界銀行 ----------

def parse_wb(text: str, url: str, code: str) -> list[dict]:
    label, unit = WB_SERIES[code]
    data = json.loads(text)
    if not isinstance(data, list) or len(data) < 2 or data[0].get('pages', 1) != 1:
        raise ValueError(f'世界銀行の応答を読めない（ページが分かれている可能性）: {code}')
    rows: dict = {}
    for obs in data[1] or []:
        if obs.get('value') is None or obs['countryiso3code'] not in COUNTRIES:
            continue
        row = {'系列': label, '国': obs['countryiso3code'], '区分': f'WB:{code}', '年': obs['date'], '値': repr(obs['value']),
               '単位': unit, '出典URL': url, '備考': f'世界銀行 {code}'}
        put_unique(rows, (obs['countryiso3code'], obs['date']), row)
    return sorted_rows(rows.values())


# ---------- 空港 ----------

def era_year(era: str, n: int) -> int:
    base = {'S': 1925, 'H': 1988, 'R': 2018}[era]
    return base + n


def year_tokens(tokens: list) -> list[int]:
    """平成・令和の年の並び（28,29,30,元,2,…）を西暦にする。昇順でなければ止める。"""
    era, prev, out = 'H', None, []
    for t in tokens:
        if isinstance(t, str) and t.strip() == '元':
            n, era = 1, 'R'
        elif is_number(t) and float(t) == int(t):
            n = int(t)
        elif isinstance(t, str) and re.fullmatch(r'\d+', t.strip()):
            n = int(t.strip())
        else:
            raise ValueError(f'年の表記を読めない: {t!r}')
        y = era_year(era, n)
        if prev is not None and y <= prev:
            raise ValueError(f'年が昇順でない: {tokens!r}')
        prev = y
        out.append(y)
    return out


def parse_airports(rows: list[list], source: str) -> dict:
    """空港別の乗降客数。{(空港名, 暦年|年度, 国際線|国内線|合計, 年): 値}。国際線＋国内線≠合計の行は含めない。"""
    out: dict = {}
    i, n = 0, len(rows)
    while i < n:
        r = rows[i]
        if len(r) > 2 and as_text(r[1]).replace(' ', '').replace('　', '').startswith('空港名'):
            name = re.sub(r'\s+', '', as_text(r[2]))
            i += 1
            groups: list[list] = [[]]
            heads = 0
            while i < n:
                r = rows[i]
                label = as_text(r[1]) if len(r) > 1 else ''
                if label.replace(' ', '') == '項目':
                    heads += 1
                    if heads >= 2:
                        break
                    i += 1
                    continue
                if len(r) > 1 and as_text(r[1]).replace(' ', '').replace('　', '').startswith('空港名'):
                    break
                if heads >= 1 and label and label not in ('年別',):
                    groups[-1].append(r)
                elif heads >= 1 and not label and groups[-1]:
                    groups.append([])
                i += 1
            groups = [g for g in groups if g]
            if len(groups) != 2:
                raise ValueError(f'{name}: 乗降客数の表の塊が2つでない（{len(groups)}）: {source}')
            for kind, g in zip(('暦年', '年度'), groups):
                years = year_tokens([r[1] for r in g])
                for y, r in zip(years, g):
                    intl, dom, tot = r[8], r[11], r[12]
                    if not (is_number(intl) and is_number(dom) and is_number(tot)):
                        continue
                    if round(intl) + round(dom) != round(tot):
                        continue
                    for lab, v in (('国際線', intl), ('国内線', dom), ('合計', tot)):
                        out[(name, kind, lab, y)] = round(v)
            continue
        i += 1
    return out


def sheet_rows(path: Path) -> list[tuple[str, list[list]]]:
    if path.suffix == '.xls':
        import xlrd
        wb = xlrd.open_workbook(str(path))
        return [(s.name, [s.row_values(k) for k in range(s.nrows)]) for s in wb.sheets()]
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    return [(w.title, [list(r) for r in w.iter_rows(values_only=True)]) for w in wb]


def airport_rows(files: list[tuple[Path, str, str]]) -> list[dict]:
    """files は古い順 [(パス, URL, 表示名)]。同じ年が重なれば新しい方で上書きし、違いがあれば備考に残さず新しい値を採る。"""
    merged: dict = {}
    for path, url, label in files:
        for (name, kind, lab, y), v in airport_from_file(path, label).items():
            merged[(name, kind, lab, y)] = (v, url, label)
    rows = []
    for (name, kind, lab, y), (v, url, label) in merged.items():
        rows.append({'系列': '空港別乗降客数（空港管理状況調書）', '国': 'JPN', '区分': f'{name}／{kind}／{lab}', '年': str(y), '値': str(v),
                     '単位': '人', '出典URL': url, '備考': f'国土交通省 {label}。国際線の乗降客数は通過客を含む小計'})
    return sorted_rows(rows)


def airport_from_file(path: Path, label: str) -> dict:
    sheets = [s for s in sheet_rows(path)
              if any('空港管理状況調書' in re.sub(r'\s+', '', as_text(c)) for r in s[1][:3] for c in r)]
    if len(sheets) != 1:
        raise ValueError(f'空港管理状況調書のシートが特定できない: {path.name}')
    return parse_airports(sheets[0][1], label)


# ---------- 鉄道 ----------

RAIL_SHEETS = {
    '旅客・貨物輸送数量': [(2, '民鉄', '旅客', '千人'), (3, '民鉄', '貨物', '千トン'), (4, '大手民鉄', '旅客', '千人'), (5, '公営', '旅客', '千人'),
                  (6, 'JR（国鉄）', '旅客', '千人'), (7, 'JR（国鉄）', '貨物', '千トン')],
    '輸送人キロ・トンキロ': [(2, '民鉄', '人キロ', '千人キロ'), (3, '民鉄', 'トンキロ', '千トンキロ'), (4, '大手民鉄', '人キロ', '千人キロ'),
                    (5, 'JR（国鉄）', '人キロ', '千人キロ'), (6, 'JR（国鉄）', 'トンキロ', '千トンキロ')],
}


def parse_rail(sheets: list[tuple[str, list[list]]], url: str) -> list[dict]:
    rows: dict = {}
    seen = set()
    for name, data in sheets:
        key = next((k for k in RAIL_SHEETS if k in name), None)
        if key is None or key in seen:
            continue
        seen.add(key)
        if '機関別' not in as_text(data[0][1]) or '民鉄' not in as_text(data[0][2]):
            raise ValueError(f'鉄道統計年報の表の見出しが想定と違う: {name}')
        era = None
        for r in data[3:]:
            if as_text(r[0]) in ('昭和', '平成', '令和'):
                era = {'昭和': 'S', '平成': 'H', '令和': 'R'}[as_text(r[0])]
            c = r[1]
            if era is None or c == '' or c is None:
                continue
            if isinstance(c, str) and c.strip() == '元':
                n = 1
            elif is_number(c):
                n = int(c)
            else:
                continue  # 注記の行
            y = era_year(era, n)
            for col, org, kind, unit in RAIL_SHEETS[key]:
                v = r[col]
                if not is_number(v):
                    continue
                div = f'{org}／{kind}'
                row = {'系列': '鉄道輸送実績（年度）', '国': 'JPN', '区分': div, '年': str(y), '値': repr(float(v)) if float(v) != int(v) else str(int(v)),
                       '単位': unit, '出典URL': url, '備考': '国土交通省 鉄道統計年報 令和5年度（22）運輸成績の推移。年は年度の開始年。JRは昭和61年度以前は国鉄'}
                put_unique(rows, (div, str(y)), row)
    missing = set(RAIL_SHEETS) - seen
    if missing:
        raise ValueError(f'鉄道統計年報の表が見つからない: {sorted(missing)}')
    out = list(rows.values())
    for (div, y), row in list(rows.items()):
        if div == '民鉄／旅客' and ('JR（国鉄）／旅客', y) in rows:
            jr = rows[('JR（国鉄）／旅客', y)]
            total = float(row['値']) + float(jr['値'])
            out.append({**row, '区分': '民鉄＋JR（国鉄）／旅客（合計）', '値': repr(total) if total != int(total) else str(int(total)),
                        '備考': row['備考'] + '。この行は民鉄と JR（国鉄）の旅客を本スクリプトで足した値（公表値ではない）'})
    return sorted_rows(out)


# ---------- 電子申請率 ----------

def squash(text: str) -> str:
    return re.sub(r'\s+', '', text)


PCT = r'([\d.]+)[%％]'


def egov_rows(label: str, text: str, url: str, title: str) -> list[dict]:
    """報道資料の本文から、国の行政機関が扱う申請・届出等手続のオンライン利用率を取り出す。期待する文が無ければ ValueError。"""
    t = squash(text)

    def find(pattern: str):
        m = re.search(pattern, t)
        if not m:
            raise ValueError(f'{label}: 期待する文が見つからない: {pattern}')
        return m

    def row(year: int, div: str, value: str, note: str) -> dict:
        return {'系列': '国の行政手続のオンライン利用率', '国': 'JPN', '区分': div, '年': str(year), '値': value, '単位': '%',
                '出典URL': url, '備考': f'総務省 {title}。{note}'}

    out: list[dict] = []
    if label == 'h20':
        m = find(r'オンライン化されている手続全体の件数は([\d,億万]+)件で、そのうちオンラインを利用した件数は([\d,億万]+)件（' + PCT + r'）となっており、19年度の実績（' + PCT + '）')
        total, used = jp_count(m.group(1)), jp_count(m.group(2))
        out.append(row(2008, '全申請・届出等手続', m.group(3), f'年間申請等件数{total:,}件中オンライン利用{used:,}件。平成20年度から府省ごとにまちまちだった集計方法を統一したため、19年度との差は集計方法の変更を含む'))
        out.append(row(2007, '全申請・届出等手続', m.group(4), '同資料が記す19年度の実績。集計方法が20年度と異なる'))
    elif label in ('h22', 'h24', 'h25'):
        fy = {'h22': 22, 'h24': 24, 'h25': 25}[label]
        m = find(rf'平成{fy}年度においては、' + PCT + r'（([\d,億万]+)件中([\d,億万]+)件）')
        total, used = jp_count(m.group(2)), jp_count(m.group(3))
        out.append(row(1988 + fy, '全申請・届出等手続（オンライン利用可能分）', m.group(1), f'年間申請等件数{total:,}件中オンライン利用{used:,}件'))
        key = find(r'重点手続（注[１]?）のオンライン利用率は、' + PCT)
        out.append(row(1988 + fy, '重点手続（71手続）', key.group(1), '国民・企業の利用頻度が高い手続を選んだ重点手続'))
        prev = find(rf'全体では、[\d.]+ポイント増加（{fy - 1}年度' + PCT + '）')
        prev2 = find(rf'重点手続について[はも]、[\d.]+ポイント増加（{fy - 1}年度' + PCT + '）')
        out.append(row(1988 + fy - 1, '全申請・届出等手続（オンライン利用可能分）', prev.group(1), f'同資料が記す{fy - 1}年度の値'))
        out.append(row(1988 + fy - 1, '重点手続（71手続）', prev2.group(1), f'同資料が記す{fy - 1}年度の値'))
    elif label == 'h26':
        m = find(r'平成26年度においては、' + PCT + r'（([\d,億万]+)件中([\d,億万]+)件）')
        total, used = jp_count(m.group(2)), jp_count(m.group(3))
        out.append(row(2014, '全申請・届出等手続（オンライン利用可能分）', m.group(1), f'年間申請等件数{total:,}件中オンライン利用{used:,}件'))
        k = find(r'改善促進手続におけるオンライン利用率' + PCT)
        out.append(row(2014, '改善促進手続', k.group(1), '平成26年度から選定された57手続'))
    elif label == 'h27':
        m = find(r'全申請・届出等件数\d*におけるオンライン利用率は、' + PCT + r'（オンライン利用件数は([\d,億万]+)件')
        out.append(row(2015, '全申請・届出等手続（オンライン利用可能分）', m.group(1), f'オンライン利用{jp_count(m.group(2)):,}件。情報通信白書 平成29年版が引く平成27年度の値'))
        k = find(r'改善促進手続\d*のオンライン利用率は、' + PCT + r'（オンライン利用件数は([\d,億万]+)件')
        out.append(row(2015, '改善促進手続', k.group(1), f'オンライン利用{jp_count(k.group(2)):,}件'))
    else:
        raise ValueError(f'未知の資料: {label}')
    return out


def dedupe_egov(rows: list[dict]) -> list[dict]:
    """同じ年度・区分が当年度の資料と翌年度の資料の両方にあるときは当年度の資料の行を残す。値が違えば止める。"""
    out: dict = {}
    for r in rows:
        k = (r['区分'], r['年'])
        if k in out:
            if out[k]['値'] != r['値']:
                raise ValueError(f'同じ年度・区分で値が食い違う: {k}')
            if '同資料が記す' in r['備考']:
                continue
        out[k] = r
    return list(out.values())


def pdf_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return '\n'.join((p.extract_text() or '') for p in pdf.pages)


def html_text(body: bytes) -> str:
    for enc in ('utf-8', 'cp932'):
        try:
            t = body.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('HTML の文字コードを判定できない')
    return re.sub(r'<[^>]+>', ' ', t)


# ---------- 取得できなかったもの ----------

STATUS_ROWS = [
    ['雇用の流動性（国際）', 'OECD 労働移動率（labour turnover）', '取得できず',
     'OECD の公開データフロー一覧に、労働移動率・離職率の国際比較表が無い（勤続年数別就業者割合 DF_TENURE_FREQ のみ。ELS 系の求職・離職は別の入手経路が要り、確かめていない）', 'https://sdmx.oecd.org/public/rest/dataflow/all'],
    ['雇用の流動性（国際）', '日本の勤続年数別就業者割合 2013年より前', '取得できず',
     'OECD の DF_TENURE_FREQ に日本は2013年以降の値しかない（雇用者の区分は日本に無い）。国内の雇用動向調査の入職率は more-stats に既にあるが、定義が違うため国際比較には使わない', TENURE_URL],
    ['電子申請率', '平成28年度以降の国の行政手続オンライン利用率', '取得できず',
     '平成28年度以降は集計表の形が変わり（府省共通手続の別など）、平成27年度までの「全申請・届出等手続」の率と同じ定義で続く値が資料にない。公表資料は年度ごとの PDF で、表形式の時系列も見つからない', 'https://www.soumu.go.jp/main_content/000743760.pdf'],
    ['電子申請率', '平成9〜18年度および平成23年度の報道資料', '取得できず',
     '平成21年度と平成23年度は翌年度の資料が記す前年度の値のみ（取得済み）。平成19年度より前の資料の所在を確かめていない', ''],
    ['電子行政の国際指標', '国連 電子政府開発指数（EGDI）／OECD デジタルガバメント指数', '取得できず',
     '国連のデータセンターは検索フォームで動的に作る画面で、固定のファイルの URL を確認できなかった。OECD のデジタルガバメント指数は2019年以降の調査のみで、機械可読の表を確かめていない', 'https://publicadministration.un.org/egovkb/en-us/Data-Center'],
    ['ブロードバンド普及率', '総務省 国内ブロードバンド契約数（四半期・年度）', '取得できず',
     '契約数の時系列表の所在を確認できなかった（電気通信サービスの契約数及びシェア等は四半期の PDF/Excel で、年を通した表を確かめていない）。OECD の日本の値で代える', ''],
    ['企業倒産件数', '公式の倒産件数の新規取得', '取得できず',
     '最高裁の司法統計（破産新受件数）は benefit-data に2005〜2025年（2014年を除く）が既にある。2000〜2004年と2014年は PDF から数を一意に読めず、1999年以前は司法統計検索システムに表が無い。商工リサーチ・帝国データバンクは民間のため使わない', 'https://www.courts.go.jp/saikosai/vc-files/saikosai/toukei/'],
    ['利用件数（交通）', '空港別乗降客数 2006年以前', '取得できず',
     '空港管理状況調書の公開ファイルは平成19年（2007年）分から（国土交通省の一覧ページで確認）。それより前の年の Excel は公開されていない', 'https://www.mlit.go.jp/koku/15_bf_000185.html'],
    ['利用件数（交通）', '鉄道輸送統計 駅別・路線別・事業者別の年次表', '取得できず',
     'e-Stat の年次表は画面が動的で、API の利用者登録（アプリケーションID）が要るため、ここでは取得していない。全国の年度合計（民鉄・JR）は鉄道統計年報の表で取得済み', 'https://www.e-stat.go.jp/stat-search/files?toukei=00600350'],
    ['不良債権比率', '日本の1997年以前の値', '取得できず',
     '世界銀行 GFDD.SI.02 の日本は1998年から。金融監督庁の資料（平成10年7月）にある平成9年3月期の従来基準公表不良債権（27.9兆円）は金額で、総貸出が同じ基準で無く比率にできない。大蔵省時代の全国銀行の比率の資料の所在を確かめていない', 'https://www.fsa.go.jp/p_fsa/news/newsj2/news-j-717.html'],
]


# ---------- 実行 ----------

def write_csv(path: Path, columns: list[str], rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for r in rows:
            w.writerow([r[c] for c in columns] if isinstance(r, dict) else r)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--raw', type=Path, default=root / '.local' / 'gap-stats' / 'raw')
    p.add_argument('--out', type=Path, default=root / 'data' / 'acquired' / 'gap-stats')
    p.add_argument('--rebuild', action='store_true', help='取得せず、保存済みの原本から表を作り直す')
    ns = p.parse_args(argv)
    ns.raw.mkdir(parents=True, exist_ok=True)
    ns.out.mkdir(parents=True, exist_ok=True)
    manifest = ns.out / 'manifest.csv'
    failed: list[str] = []

    def get(url: str, name: str, accept: str = '*/*') -> bytes | None:
        dest = ns.raw / name
        if ns.rebuild:
            body = dest.read_bytes() if dest.exists() else None
        else:
            body = fetch(url, dest, manifest, root, accept)
        if body is None:
            failed.append(name)
        return body

    def emit(name: str, rows: list[dict]) -> None:
        write_csv(ns.out / name, OUT_COLUMNS, rows)
        print(f'{name}: {len(rows)} 行')

    body = get(TENURE_URL, 'oecd-tenure.csv', SDMX_ACCEPT)
    if body:
        emit('oecd_tenure.csv', parse_tenure(body.decode('utf-8'), TENURE_URL))
    body = get(WAGE_URL, 'oecd-wages.csv', SDMX_ACCEPT)
    if body:
        emit('oecd_wages.csv', parse_wages(body.decode('utf-8'), WAGE_URL))
    bb_rows: list[dict] = []
    body = get(BB_URL, 'oecd-broadband.csv', SDMX_ACCEPT)
    if body:
        bb_rows += parse_broadband(body.decode('utf-8'), BB_URL)
    code = 'IT.NET.BBND.P2'
    url = WB_URL.format(code=code)
    body = get(url, f'wb-{code}.json')
    if body:
        bb_rows += parse_wb(body.decode('utf-8'), url, code)
    if bb_rows:
        emit('broadband.csv', sorted_rows(bb_rows))
    code = 'GFDD.SI.02'
    url = WB_URL.format(code=code)
    body = get(url, f'wb-{code}.json')
    if body:
        emit('npl_wb_gfdd.csv', parse_wb(body.decode('utf-8'), url, code))

    files = []
    for url, name, label in ((AIRPORT_OLD, 'airport-h19-h28.xls', '暦年・年度別空港管理状況調書（H19～H28）'),
                             (AIRPORT_NEW, 'airport-h28-r7.xlsx', '暦年・年度別空港管理状況調書（H28～R7）')):
        if get(url, name) is not None:
            files.append((ns.raw / name, url, label))
    if len(files) == 2:
        emit('airport_passengers.csv', airport_rows(files))
    if get(RAIL_URL, 'rail-unyu-seiseki.xls') is not None:
        emit('rail_transport.csv', parse_rail(sheet_rows(ns.raw / 'rail-unyu-seiseki.xls'), RAIL_URL))

    eg: list[dict] = []
    for label, url, title in EGOV_DOCS:
        if get(url, f'egov-{label}.pdf') is not None:
            eg += egov_rows(label, pdf_text(ns.raw / f'egov-{label}.pdf'), url, title)
    body = get(WHITEPAPER_H29, 'egov-whitepaper-h29.html')
    if body:
        eg += egov_rows('h27', html_text(body), WHITEPAPER_H29, '情報通信白書 平成29年版「電子行政の推進」')
    if eg:
        emit('egov_online_rate.csv', sorted_rows(dedupe_egov(eg)))

    write_csv(ns.out / 'status.csv', STATUS_COLUMNS, STATUS_ROWS)
    print(f'取得できなかった原本: {failed or "なし"}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
