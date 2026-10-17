"""不足していた公的統計を取得して整える（task-id more-stats）。

対象（公式の出典のみ。民間データは使わない）:
- 雇用の流動性: 厚生労働省 雇用動向調査（入職率・離職率、産業別、就業形態・性別、年齢階級別の転職入職率）、
  総務省 労働力調査 長期時系列表10(3)（転職者数・転職者比率）
- 賃金: 厚生労働省 毎月勤労統計調査 実数・指数累積データ（現金給与総額ほか。産業別、年平均）
- 貸出残高: 日本銀行 時系列統計データ検索サイト（API）の「貸出先別貸出金」LA01（国内銀行、四半期末残高。年は12月末）
- 不良債権比率: 金融庁 金融再生法開示債権の状況等（全国銀行、半期）
- 発電構成・エネルギー効率: 資源エネルギー庁 総合エネルギー統計 時系列表（年度）
- 国際比較: 世界銀行 WDI（不良債権比率、銀行の民間向け与信、電源構成、エネルギー集約度）

原本は --raw の下に保存し、URL・sha256・取得時刻を manifest.csv に残す（原本は Git に入れない）。
整えた表は --out の下に書く。列: 系列,区分,年,値,単位,出典URL,備考。欠けた値は書かない（0や推定で埋めない）。

使い方（リポジトリのルートで。xls/xlsx を読むため xlrd と openpyxl が要る）:
  python3 scripts/fetch_more_stats.py fetch --raw .local/more-stats/raw --manifest data/acquired/more-stats/manifest.csv
  python3 scripts/fetch_more_stats.py build --raw .local/more-stats/raw --out data/acquired/more-stats
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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INTERVAL_SECONDS = 1.2
UA = 'public-interest-lens more-stats (research; GitHub nexus-ai-2045/public-interest-lens)'
# 資源エネルギー庁のサイトは UA が研究用の名乗りだと 404 を返すため、この1ホストだけ一般的なブラウザ UA と参照元を付ける
BROWSER_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'
ESTAT = 'https://www.e-stat.go.jp/stat-search/file-download?statInfId=%s&fileKind=%s'
OUT_HEADER = ['系列', '区分', '年', '値', '単位', '出典URL', '備考']

# 雇用動向調査 年次別推移（e-Stat 提供分類1「年次別推移」。表番号→ファイルID）
KOYO = [('koyo_t1.xls', '000040490255', '4', '第1表 就業形態、性別入職・離職率'),
        ('koyo_t2.xls', '000040490256', '4', '第2表 産業（大分類）別入職・離職率'),
        ('koyo_t4-2.xls', '000040490259', '4', '第4-2表 性、年齢階級別転職入職率')]
MK_CUM = ('mk_cumulative.csv', '000032189776', '1')  # 毎月勤労統計 実数・指数累積データ 表1 実数
MK_SYM = ('mk_symbols.pdf', '000032189778', '2')     # 記号の見方（産業コード・規模・就業形態）
LFS_103 = ('lfs_10-3.xlsx', '000031770645', '0')     # 労働力調査 長期時系列表10(3)

BOJ_API = 'https://www.stat-search.boj.or.jp/api/v1/'
BOJ_DB = 'la01'
BOJ_BATCH = 10

FSA_PAGES = [  # 金融再生法開示債権の状況等。各回の表1に全国銀行の約10年分がある。新しい回ほど優先
    ('20060808', 'data01.xlsx'), ('20120824', '01.xlsx'), ('20160812', '01.xlsx'), ('20260227', '01.xlsx')]

ENECHO_XLSX = 'https://www.enecho.meti.go.jp/statistics/total_energy/xls/stte/stte_jikeiretu2024fykaku.xlsx'
ENECHO_REFERER = 'https://www.enecho.meti.go.jp/statistics/total_energy/results.html'

WB_COUNTRIES = ['JPN', 'USA', 'GBR', 'FRA', 'DEU', 'ITA', 'CAN', 'KOR', 'NLD', 'NOR', 'SWE', 'ESP', 'AUS']
WB_INDICATORS = {
    'FB.AST.NPER.ZS': ('銀行の不良債権比率（総貸出に対する%）', '%'),
    'FD.AST.PRVT.GD.ZS': ('預金銀行の民間向け国内与信（GDP比%）', '%'),
    'FS.AST.PRVT.GD.ZS': ('金融部門の民間向け国内与信（GDP比%）', '%'),
    'EG.EGY.PRIM.PP.KD': ('一次エネルギー集約度（MJ/2021年PPP米ドル）', 'MJ/米ドル'),
    'EG.ELC.NUCL.ZS': ('原子力の発電比率（%）', '%'),
    'EG.ELC.HYRO.ZS': ('水力の発電比率（%）', '%'),
    'EG.ELC.RNEW.ZS': ('再生可能エネルギーの発電比率（水力含む、%）', '%'),
    'EG.ELC.FOSL.ZS': ('化石燃料の発電比率（%）', '%'),
    'EG.ELC.COAL.ZS': ('石炭の発電比率（%）', '%'),
    'EG.ELC.NGAS.ZS': ('天然ガスの発電比率（%）', '%'),
    'EG.ELC.PETR.ZS': ('石油の発電比率（%）', '%'),
}


# ---------------------------------------------------------------- 共通

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch(url: str, dest: Path, manifest: Path, repo_rel: str, headers: dict | None = None) -> bytes | None:
    """URL を dest に保存して manifest に追記する。dest があれば再取得しない。"""
    if dest.exists():
        return dest.read_bytes()
    time.sleep(INTERVAL_SECONDS)
    hdr = {'User-Agent': UA, 'Accept': '*/*'}
    hdr.update(headers or {})
    body = None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=180) as res:
            body = res.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f'取得できない: {url} {e}', file=sys.stderr)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    new = not manifest.exists()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open('a', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['file', 'url', 'sha256', 'fetched_at'])
        w.writerow([repo_rel, url, sha256_bytes(body), datetime.now(timezone.utc).isoformat(timespec='seconds')])
    return body


def clean(s) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s))) if s is not None else ''


ERA = {'昭和': 1925, '平成': 1988, '令和': 2018}


def era_year_label(cell, cur_era: str | None):
    """見出しセルを (西暦, 元号) にする。'平成\\n3年' '令和\\n元年' は元号つき、数値 4.0 は直前の元号の年、西暦の数値はそのまま。"""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        v = int(cell)
        if v >= 1900:
            return v, cur_era
        return (ERA[cur_era] + v, cur_era) if cur_era else (None, cur_era)
    if isinstance(cell, str):
        t = clean(cell)
        m = re.match(r'(昭和|平成|令和)(元|\d+)年?', t)
        if m:
            n = 1 if m.group(2) == '元' else int(m.group(2))
            return ERA[m.group(1)] + n, m.group(1)
        m = re.match(r'(\d{4})年?$', t)
        if m:
            return int(m.group(1)), cur_era
    return None, cur_era


def to_number(x):
    """数値セルを (float, 補完推計か) に。< > で囲まれた値は補完推計。数でなければ None。"""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x), False
    if isinstance(x, str):
        t = clean(x)
        sup = t.startswith('<') and t.endswith('>')
        t = t.strip('<>')
        try:
            return float(t), sup
        except ValueError:
            return None
    return None


def fmt(v: float) -> str:
    s = repr(float(round(v, 10)))
    return s[:-2] if s.endswith('.0') else s


def read_sheets(path: Path):
    """[(シート名, 行のリスト)]。xls は xlrd、xlsx は openpyxl（どちらも実行時に読み込む）。"""
    if path.suffix == '.xls':
        import xlrd
        wb = xlrd.open_workbook(str(path))
        return [(ws.name, [[(c if c != '' else None) for c in ws.row_values(i)] for i in range(ws.nrows)]) for ws in wb.sheets()]
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]


# ---------------------------------------------------------------- 雇用動向調査

def parse_matrix_table(rows, header_idx, first_col, series_cols, label_cols, rename=None, skip_label_cols=()):
    """階層見出し（左の列に親→子）と年の見出し行をもつ表を長い形にする。

    series_cols: 系列名になる列（複数あれば、空でない最後のもの）。
    label_cols: 区分になる列。親が変わると子の持ち越しを消す。
    戻り値: [(系列, 区分, 年, 値, 元号, 補完推計か)]
    """
    rename = rename or {}
    years, era = {}, None
    for c in range(first_col, len(rows[header_idx])):
        y, era = era_year_label(rows[header_idx][c], era)
        if y:
            years[c] = (y, era)
    levels = {}
    out = []
    all_cols = sorted(set(series_cols) | set(label_cols) | set(skip_label_cols))
    for r in rows[header_idx + 1:]:
        if all(x is None for x in r):
            continue
        changed = False
        for c in all_cols:
            v = r[c] if c < len(r) else None
            if v is not None and clean(v) != '':
                levels[c] = clean(v)
                for d in all_cols:
                    if d > c:
                        levels.pop(d, None)
                changed = True
        if not changed:
            continue
        data = [(c, to_number(r[c])) for c in years if c < len(r) and to_number(r[c]) is not None]
        if not data:
            continue
        sc = [levels[c] for c in series_cols if c in levels]
        if not sc:
            continue
        series = sc[-1]
        labs = []
        for c in label_cols:
            if c in levels:
                t = re.sub(r'\d+\)$', '', levels[c])
                labs.append(rename.get((c, t), t))
        for c, (v, sup) in data:
            out.append((series, '/'.join(labs), years[c][0], v, years[c][1], sup))
    return out


KOYO_SPEC = {
    # 第1表: 列1=系列、列2=副系列(未就業入職率・転職入職率)、列3=就業形態、列4=性
    't1': dict(header_idx=3, first_col=6, series_cols=[1, 2], label_cols=[3, 4], skip=(),
               rename={(3, '計'): '就業形態計', (4, '計'): '男女計'}),
    # 第2表: 列0=入職率/離職率、列1=産業コード、列2=産業、列3=製造業の内訳
    't2': dict(header_idx=3, first_col=5, series_cols=[0], label_cols=[2, 3], skip=(1,), rename={}),
    # 第4-2表: 列0=性、列3=年齢階級（系列名は表に無く、転職入職率に固定）
    't4-2': dict(header_idx=3, first_col=5, series_cols=[0], label_cols=[0, 3], skip=(), rename={(0, '計'): '男女計'}),
}


def build_koyo(raw: Path, urls: dict) -> list:
    out = []
    for fn, _sid, _kind, title in KOYO:
        key = fn.replace('koyo_', '').replace('.xls', '')
        spec = KOYO_SPEC[key]
        for sheet_name, rows in read_sheets(raw / fn):
            recs = parse_matrix_table(rows, spec['header_idx'], spec['first_col'], spec['series_cols'], spec['label_cols'],
                                      spec['rename'], spec['skip'])
            for series, lab, y, v, _era, sup in recs:
                if key == 't4-2':
                    series = '転職入職率'
                out.append([clean(series), lab, y, fmt(v), '%', urls[fn], f'{title}（シート:{sheet_name}）' + ('。補完推計値' if sup else '')])
    return out


# ---------------------------------------------------------------- 労働力調査

def build_lfs(raw: Path, urls: dict) -> list:
    out = []
    sheets = dict(read_sheets(raw / LFS_103[0]))
    for sx in ('総数', '男', '女'):
        rows = sheets[sx]
        # 6行目(index5)が見出し。転職者(万人)は列2-8、転職者比率(%)は列9-15
        age = [clean(x) for x in rows[5]]
        for r in rows[9:]:
            y = r[1] if len(r) > 1 else None
            if not isinstance(y, (int, float)) or isinstance(y, bool):
                continue
            for c in range(2, 16):
                n = to_number(r[c]) if c < len(r) else None
                if n is None:
                    continue
                v, sup = n
                is_num = c <= 8
                label = '男女計' if sx == '総数' else sx
                out.append(['転職者数' if is_num else '転職者比率', f'{label}/{"全年齢" if age[c] == "総数" else age[c]}', int(y), fmt(v),
                            '万人' if is_num else '%', urls[LFS_103[0]], '労働力調査 長期時系列表10(3) 年平均' + ('。補完推計値' if sup else '')])
    return out


# ---------------------------------------------------------------- 毎月勤労統計

MK_MEASURES = ['現金給与総額', 'きまって支給する給与', '所定内給与', '所定外給与', '特別給与', '総実労働時間', '所定内労働時間', '所定外労働時間', '出勤日数']
MK_UNIT = {'現金給与総額': '円', 'きまって支給する給与': '円', '所定内給与': '円', '所定外給与': '円', '特別給与': '円',
           '総実労働時間': '時間', '所定内労働時間': '時間', '所定外労働時間': '時間', '出勤日数': '日'}
MK_SIZE = {'T': '事業所規模5人以上', '0': '事業所規模30人以上'}  # 5人以上は1990年から、30人以上は調査産業計で1970年から
MK_FORM = {'0': '就業形態計', '1': '一般労働者', '2': 'パートタイム労働者'}
MK_INDUSTRY = {
    'TL': '調査産業計', 'C': '鉱業，採石業，砂利採取業', 'D': '建設業', 'E': '製造業', 'F': '電気・ガス・熱供給・水道業', 'G': '情報通信業',
    'H': '運輸業，郵便業', 'I': '卸売業，小売業', 'J': '金融業，保険業', 'K': '不動産業，物品賃貸業', 'L': '学術研究，専門・技術サービス業',
    'M': '宿泊業，飲食サービス業', 'N': '生活関連サービス業，娯楽業', 'O': '教育，学習支援業', 'P': '医療，福祉', 'Q': '複合サービス事業',
    'R': 'サービス業（他に分類されないもの）',
    'F33': '電気業', 'G37': '通信業', 'G39': '情報サービス業', 'G41': '映像・音声・文字情報制作業', 'H42': '鉄道業', 'H43': '道路旅客運送業',
    'H44': '道路貨物運送業', 'I-1': '卸売業', 'I-2': '小売業', 'J62': '銀行業', 'J63': '協同組織金融業',
    'J64': '貸金業，クレジットカード業等非預金信用機関', 'J65': '金融商品取引業，商品先物取引業', 'J67': '保険業',
    'M75': '宿泊業', 'M76': '飲食店', 'D06': '総合工事業', 'D07': '職別工事業(設備工事業を除く)', 'D08': '設備工事業',
    'P83': '医療業', 'P85': '社会保険・社会福祉・介護事業', 'R91': '職業紹介・労働者派遣業',
    'E-1': '消費関連製造業', 'E-2': '素材関連製造業', 'E-3': '機械関連製造業',
}


def parse_mk_csv(text: str, url: str) -> list:
    """毎月勤労統計 実数・指数累積データ（CSV）から、年平均(月=CY)・事業所規模5人以上・主要な指標を取り出す。"""
    out = []
    rd = csv.reader(io.StringIO(text))
    head = next(rd)
    idx = {h: i for i, h in enumerate(head)}
    for r in rd:
        if len(r) < len(head) or r[idx['種別']] != '実数' or r[idx['月']] != 'CY':
            continue
        size = MK_SIZE.get(r[idx['規模']])
        if size is None or r[idx['就業形態']] not in MK_FORM:
            continue
        code = r[idx['産業分類']].strip()
        name = MK_INDUSTRY.get(code)
        if name is None:
            continue
        for m in MK_MEASURES:
            v = r[idx[m]].strip()
            if v == '':
                continue
            try:
                num = float(v)
            except ValueError:
                continue
            out.append([m, f'{name}/{MK_FORM[r[idx["就業形態"]]]}/{size}', int(r[idx['年']]), fmt(num), MK_UNIT[m], url,
                        f'毎月勤労統計調査 実数・指数累積データ 年平均。産業コード{code}'])
    return out


# ---------------------------------------------------------------- 日本銀行

def boj_sector(name: str) -> str:
    return name.split('／残高')[0].replace('／', '/')


def boj_select_codes(meta: dict) -> list:
    sel = []
    for r in meta['RESULTSET']:
        code = r['SERIES_CODE']
        if code and r['FREQUENCY'] == 'QUARTERLY' and code.split('_')[1].startswith(('DLLI5DS2T', 'DLLI5DS2S')):
            sel.append((code, r['NAME_OF_TIME_SERIES_J']))
    return sel


def parse_boj_csv(text: str, names: dict, url: str) -> list:
    """BOJ API の CSV（列: SERIES_CODE..., SURVEY_DATES, VALUES）から、12月末（第4四半期=04）の残高を年の値にする。"""
    out = []
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('SERIES_CODE,'))
    for r in csv.DictReader(lines[start:]):
        d = r['SURVEY_DATES']
        v = r['VALUES']
        if len(d) != 6 or d[4:] != '04' or to_number(v) is None:
            continue
        out.append(['貸出先別貸出金 残高（国内銀行、銀行・信託・海外店勘定の合計）', boj_sector(names[r['SERIES_CODE']]), int(d[:4]), fmt(float(v)), '億円', url,
                    f'日本銀行 時系列統計データ検索サイト LA01 系列{r["SERIES_CODE"]}。四半期末残高のうち12月末'])
    return out


# ---------------------------------------------------------------- 金融庁

def fsa_period(label):
    """'11年3月期'（平成）や '2016年9月期' を (西暦, 月) にする。"""
    t = clean(label)
    m = re.match(r'(\d{4})年(\d+)月期$', t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r'(\d{1,2})年(\d+)月期$', t)
    if m:
        return 1988 + int(m.group(1)), int(m.group(2))
    return None


FSA_ROWS = {'総与信': ('総与信', '億円'), '金融再生法開示債権': ('金融再生法開示債権', '億円'), '破産更生等債権': ('破産更生等債権', '億円'),
            '危険債権': ('危険債権', '億円'), '要管理債権': ('要管理債権', '億円'), '正常債権': ('正常債権', '億円'), '不良債権比率': ('不良債権比率', '%')}


def parse_fsa_table1(rows, group='全国銀行'):
    """表1から指定グループ（全国銀行）の各行を {(期末年, 月): {項目: 値}} にする。"""
    hdr = None
    for r in rows[:8]:
        if sum(1 for x in r if isinstance(x, str) and fsa_period(x)) >= 4:
            hdr = r
            break
    if hdr is None:
        return {}
    cols = {c: fsa_period(x) for c, x in enumerate(hdr) if isinstance(x, str) and fsa_period(x)}
    start = None
    for i, r in enumerate(rows):
        if any(isinstance(x, str) and clean(x) == group for x in r[:3]):
            start = i
            break
    if start is None:
        return {}
    res = {}
    for r in rows[start:start + 8]:
        # 先頭行は「全国銀行」と総与信が同じ行にある。項目名は先頭5列の文字のうち、グループ名以外
        labs = [re.sub(r'\(.*?\)$', '', clean(x)) for x in r[:5] if isinstance(x, str) and clean(x) and clean(x) != group]
        label = next((k for k in FSA_ROWS for lab in labs if lab.startswith(k)), None)
        if label is None:
            continue
        for c, per in cols.items():
            v = r[c] if c < len(r) else None
            n = to_number(v)
            if n is not None and not isinstance(v, str):
                res.setdefault(per, {})[label] = n[0]
    return res


def build_fsa(raw: Path, urls: dict) -> list:
    merged, src = {}, {}   # 新しい回で上書き
    for d, fn in FSA_PAGES:
        tbl = parse_fsa_table1(read_sheets(raw / f'fsa_{d}_{fn}')[0][1])
        for per, items in tbl.items():
            for k, v in items.items():
                merged[(per, k)] = v
                src[(per, k)] = d
    out = []
    for (per, k), v in sorted(merged.items()):
        year, month = per
        label, unit = FSA_ROWS[k]
        out.append(['総与信（全国銀行）' if k == '総与信' else '金融再生法開示債権（全国銀行）', f'{label}/{month}月期', year, fmt(v), unit,
                    urls[f'fsa_{src[(per, k)]}'], f'金融庁 金融再生法開示債権等の推移 表1 全国銀行。{src[(per, k)]}公表分の値（重なる期は新しい公表を採用）'])
    return out


# ---------------------------------------------------------------- 資源エネルギー庁

def parse_energy_sheet(title: str, rows: list, url: str) -> list:
    """総合エネルギー統計 時系列表の1シート。「年度」見出し行ごとのブロックを読み、単位は直前の行の（…）から取る。構成比・前年度比は読まない。"""
    out = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if len(r) > 1 and clean(r[1]) == '年度':
            unit = ''
            for k in range(i - 1, max(i - 4, -1), -1):
                for x in rows[k]:
                    if isinstance(x, str) and re.match(r'^\(.*\)$', clean(x)):
                        unit = clean(x)[1:-1]
                if unit:
                    break
            years = {c: int(r[c]) for c in range(2, len(r)) if isinstance(r[c], (int, float)) and not isinstance(r[c], bool) and 1900 < r[c] < 2100}
            j = i + 1
            while j < len(rows) and any(x is not None for x in rows[j][:3]) and clean(rows[j][1]) != '年度':
                lab = clean(rows[j][1])
                if lab and not lab.startswith('※') and unit not in ('構成比', '前年度比'):
                    for c, y in years.items():
                        n = to_number(rows[j][c]) if c < len(rows[j]) else None
                        if n is not None:
                            out.append([title, lab, y, fmt(n[0]), unit, url, '資源エネルギー庁 総合エネルギー統計 時系列表（年度）'])
                j += 1
            i = j
        else:
            i += 1
    return out


def build_energy(raw: Path, urls: dict) -> list:
    out = []
    for name, rows in read_sheets(raw / 'enecho_jikeiretsu.xlsx'):
        if name != 'Contents':
            out += parse_energy_sheet(name, rows, urls['enecho_jikeiretsu.xlsx'])
    return out


# ---------------------------------------------------------------- 世界銀行

def parse_wb_json(body: bytes, name: str, unit: str, url: str) -> list:
    data = json.loads(body)
    out = []
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return out
    for rec in data[1]:
        if rec.get('value') is None:
            continue
        out.append([name, rec['countryiso3code'] or rec['country']['id'], int(rec['date']), fmt(float(rec['value'])), unit, url,
                    f'世界銀行 WDI {rec["indicator"]["id"]}'])
    return out


# ---------------------------------------------------------------- 実行

def write_csv(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(OUT_HEADER)
        w.writerows(rows)


def do_fetch(raw: Path, manifest: Path):
    def rel(p):
        return str(Path('.local/more-stats/raw') / p)
    for fn, sid, kind, _t in KOYO:
        fetch(ESTAT % (sid, kind), raw / fn, manifest, rel(fn))
    for fn, sid, kind in (MK_CUM, MK_SYM, LFS_103):
        fetch(ESTAT % (sid, kind), raw / fn, manifest, rel(fn))
    meta_url = f'{BOJ_API}getMetadata?format=json&lang=jp&db={BOJ_DB}'
    body = fetch(meta_url, raw / 'boj_la01_metadata.json', manifest, rel('boj_la01_metadata.json'))
    if body:
        codes = [c for c, _n in boj_select_codes(json.loads(body))]
        for k in range(0, len(codes), BOJ_BATCH):
            chunk = codes[k:k + BOJ_BATCH]
            pos, part = None, 0
            while True:
                url = (f'{BOJ_API}getDataCode?format=csv&lang=jp&db={BOJ_DB}&startDate=197001&code=' + ','.join(chunk)
                       + (f'&startPosition={pos}' if pos else ''))
                fn = f'boj_la01_{k // BOJ_BATCH:02d}_{part}.csv'
                b = fetch(url, raw / fn, manifest, rel(fn))
                if not b:
                    break
                nxt = re.search(rb'NEXTPOSITION,(\d*)', b)
                pos = nxt.group(1).decode() if nxt and nxt.group(1) else None
                part += 1
                if not pos:
                    break
    for d, fn in FSA_PAGES:
        fetch(f'https://www.fsa.go.jp/status/npl/{d}/{fn}', raw / f'fsa_{d}_{fn}', manifest, rel(f'fsa_{d}_{fn}'))
    fetch(ENECHO_XLSX, raw / 'enecho_jikeiretsu.xlsx', manifest, rel('enecho_jikeiretsu.xlsx'),
          headers={'User-Agent': BROWSER_UA, 'Referer': ENECHO_REFERER})
    for code in WB_INDICATORS:
        url = f'https://api.worldbank.org/v2/country/{";".join(WB_COUNTRIES)}/indicator/{code}?format=json&per_page=2000&date=1960:2025'
        fetch(url, raw / 'wb' / f'{code}.json', manifest, rel(f'wb/{code}.json'))


def manifest_urls(manifest: Path) -> dict:
    urls = {}
    with manifest.open(encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh):
            urls[Path(r['file']).relative_to('.local/more-stats/raw').as_posix()] = r['url']
    return urls


def do_build(raw: Path, out: Path, manifest: Path):
    urls = manifest_urls(manifest)
    for d, fn in FSA_PAGES:
        urls[f'fsa_{d}'] = urls[f'fsa_{d}_{fn}']
    write_csv(out / 'employment_turnover.csv', build_koyo(raw, urls))
    write_csv(out / 'job_changers_lfs.csv', build_lfs(raw, urls))
    write_csv(out / 'wages_monthly_labour_survey.csv', parse_mk_csv((raw / MK_CUM[0]).read_bytes().decode('cp932'), urls[MK_CUM[0]]))
    names = dict(boj_select_codes(json.loads((raw / 'boj_la01_metadata.json').read_bytes())))
    boj = []
    for p in sorted(raw.glob('boj_la01_*_*.csv')):
        boj += parse_boj_csv(p.read_bytes().decode('cp932'), names, urls[p.name])
    write_csv(out / 'bank_loans_by_sector_boj.csv', boj)
    write_csv(out / 'npl_fsa_all_banks.csv', build_fsa(raw, urls))
    write_csv(out / 'energy_total_energy_statistics.csv', build_energy(raw, urls))
    wb = []
    for code, (name, unit) in WB_INDICATORS.items():
        p = raw / 'wb' / f'{code}.json'
        if p.exists():
            wb += parse_wb_json(p.read_bytes(), name, unit, urls[f'wb/{code}.json'])
    write_csv(out / 'worldbank_extra.csv', wb)
    for f in sorted(out.glob('*.csv')):
        if f.name != 'manifest.csv':
            print(f.name, sum(1 for _ in f.open(encoding='utf-8')) - 1, '行')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['fetch', 'build'])
    ap.add_argument('--raw', default='.local/more-stats/raw')
    ap.add_argument('--out', default='data/acquired/more-stats')
    ap.add_argument('--manifest', default='data/acquired/more-stats/manifest.csv')
    a = ap.parse_args(argv)
    raw, out, mf = Path(a.raw), Path(a.out), Path(a.manifest)
    if a.cmd == 'fetch':
        do_fetch(raw, mf)
    else:
        do_build(raw, out, mf)


if __name__ == '__main__':
    main()
