"""消費者物価指数 品目別価格指数(年平均,全国,総務省統計局→e-Stat)を基準年ごとのCSVにする。
含める品目: 類(符号<1000)の全部 + 名前が KEY に当たる品目。2005基準は符号が無いので見出しの階層が浅いもの + KEY。"""
import csv, re, os, glob, unicodedata

RAW = '.local/domestic-stats/raw/'
OUT = 'data/acquired/domestic-stats/'
DL = 'https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId='
KEY = re.compile('通信|電話|電気|宿泊|インターネット|ガス代|ホテル|放送|郵便')
SETS = [
    ('2025基準', ['cpi2025_annual_items_000040482831.csv']),
    ('2020基準', ['cpi2020_annual_items_000032103938.csv']),
    ('2015基準', ['cpi2015_annual_items_000031431772.csv']),
    ('2010基準', ['cpi2010_annual_items_0000112885%d.csv' % i for i in (49, 50, 51, 52)]),
    ('2005基準', ['cpi2005_annual_items_0000021030%d.csv' % i for i in (90, 91, 92, 93)]),
]


def nm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))


def num(s):
    try:
        return float(s)
    except ValueError:
        return None


def read(path):
    raw = open(path, 'rb').read()
    try:
        t = raw.decode('utf-8')
    except UnicodeDecodeError:
        t = raw.decode('cp932')
    return list(csv.reader(t.splitlines()))


def main():
    for base, files in SETS:
        out = OUT + 'cpi_items_annual_%s.csv' % base.replace('基準', 'base')
        n = 0
        with open(out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['基準年', '品目', '年', '値', '出典URL', '品目符号'])
            for fn in files:
                rows = read(RAW + fn)
                url = DL + re.search(r'_(\d{12})\.csv', fn).group(1)
                # データ行 = 先頭が4桁の年
                di = [i for i, r in enumerate(rows) if re.fullmatch(r'\d{4}', nm(r[0]))]
                first = di[0]
                coderow = next((r for r in rows[:first] if r[0].startswith(('類・品目符号', '類符号'))), None)
                itemrow = next((r for r in rows[:first] if r[0].startswith('品目符号')), None)
                gi = next((i for i, r in enumerate(rows[:first]) if r[0].startswith('Group')), first)
                ncol = len(rows[0])
                for c in range(1, ncol):
                    heads = [(i, rows[i][c]) for i in range(gi) if c < len(rows[i]) and rows[i][c].strip()
                             and not re.match(r'[A-Za-z]', rows[i][c].strip())]
                    if not heads:
                        continue
                    depth, name = heads[-1]
                    name = nm(name)
                    code = nm(coderow[c]) if coderow and c < len(coderow) else ''
                    icode = nm(itemrow[c]) if itemrow and c < len(itemrow) else ''
                    if rows[0][0].startswith('類・品目') and coderow and coderow[0].startswith('類・品目符号'):
                        keep = code.isdigit() and int(code) < 1000
                    else:
                        keep = bool(code) and not icode
                        code = code or icode
                    if not (keep or KEY.search(name)):
                        continue
                    for i in di:
                        v = num(rows[i][c]) if c < len(rows[i]) else None
                        w.writerow([base, name, nm(rows[i][0]), '' if v is None else rows[i][c].strip(), url, code])
                        n += 1
        print(out, n)


main()
