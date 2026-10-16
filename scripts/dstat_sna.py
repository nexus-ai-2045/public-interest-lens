"""内閣府 国民経済計算 経済活動別GDP(暦年) を基準年ごとのCSVにする。使い方: python -I scripts/dstat_sna.py"""
import csv, re, unicodedata, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from dstat_xl import sheets

RAW = '.local/domestic-stats/raw/'
OUT = 'data/acquired/domestic-stats/'
BASE = 'https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/'
# (基準年ラベル, 名目ファイル, 名目URL, 実質ファイル, 実質URL)
SETS = [
    ('2020基準', 'sna2020_gdp_nominal_2024s2n.xlsx', BASE + '2024/tables/2024s2n_jp.xlsx', 'sna2020_gdp_real_2024s2rn.xlsx', BASE + '2024/tables/2024s2rn_jp.xlsx'),
    ('2015基準', 'sna2015_gdp_nominal_2019s2n.xlsx', BASE + '2019/tables/2019s2n_jp.xlsx', 'sna2015_gdp_real_2019s2rn.xlsx', BASE + '2019/tables/2019s2rn_jp.xlsx'),
    ('2011基準', 'sna2011_gdp_nominal_30s2n.xlsx', BASE + 'h30/tables/30s2n_jp.xlsx', 'sna2011_gdp_real_30s2rn.xlsx', BASE + 'h30/tables/30s2rn_jp.xlsx'),
    ('2005基準', 'sna2005_gdp_nominal_26s2n.xls', BASE + 'h26/tables/26s2n_jp.xls', 'sna2005_gdp_real_26s2rn.xls', BASE + 'h26/tables/26s2rn_jp.xls'),
    ('2000基準', 'sna2000_gdp_nominal_21s2n.xls', BASE + 'h21/tables/21s2n_jp.xls', 'sna2000_gdp_real_21s2rn.xls', BASE + 'h21/tables/21s2rn_jp.xls'),
]


def norm(s):
    s = unicodedata.normalize('NFKC', str(s))
    return re.sub(r'\s+', '', s)


def year_of(s):
    m = re.search(r'[(（](\d{4})[)）]', str(s))
    return int(m.group(1)) if m else None


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def nominal(path):
    res = []
    for name, rows in sheets(path):
        y = year_of(rows[3][1])
        col = next(i for i, c in enumerate(rows[4]) if c and norm(c) == '国内総生産')
        for r in rows[7:]:
            if r[0] is None or not norm(r[0]):
                continue
            v = num(r[col]) if len(r) > col else None
            if v is None and not any(num(x) is not None for x in r[1:]):
                continue
            res.append((norm(r[0]), y, v))
    return res, '10億円'


def real(path):
    (name, rows), = sheets(path)
    unit = '指数(' + norm(rows[3][0]).strip('（）()') + ',連鎖方式)'
    ycol = {}
    cur = None
    for i, c in enumerate(rows[4]):
        if c:
            cur = year_of(c)
        ycol[i] = cur
    gcols = [i for i, c in enumerate(rows[5]) if c and norm(c) == '国内総生産']
    res = []
    for r in rows[8:]:
        if r[0] is None or not norm(r[0]):
            continue
        if not any(num(x) is not None for x in r[1:]):
            continue
        for g in gcols:
            res.append((norm(r[0]), ycol[g], num(r[g]) if len(r) > g else None))
    return res, unit


def main():
    os.makedirs(OUT, exist_ok=True)
    for base, nf, nu, rf, ru in SETS:
        fn = OUT + 'sna_gdp_by_industry_%s.csv' % base.replace('基準', 'base')
        n = 0
        with open(fn, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['基準年', '価格', '経済活動', '年', '値', '単位', '出典URL'])
            for kind, fx, url, fnc in (('名目', nf, nu, nominal), ('実質(連鎖方式)', rf, ru, real)):
                data, unit = fnc(RAW + fx)
                for lab, y, v in data:
                    w.writerow([base, kind, lab, y, '' if v is None else v, unit, url])
                    n += 1
        print(fn, n)


main()
