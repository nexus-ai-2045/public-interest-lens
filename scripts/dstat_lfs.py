"""労働力調査 長期時系列表5 産業別就業者数(年平均,男女計,万人)。産業分類の改定ごとに別CSV。"""
import csv, os, re, sys, unicodedata
sys.path.insert(0, os.path.dirname(__file__))
from dstat_xl import sheets

D = 'https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId='
SETS = [
    ('lfs_5-1_000001082692.xlsx', '長期05', '000001082692', 'lfs_employed_by_industry_jsic12-14.csv', '第12・13・14回改定日本標準産業分類'),
    ('lfs_5-2_000004703169.xls', '長期05', '000004703169', 'lfs_employed_by_industry_jsic11.csv', '第11回改定日本標準産業分類'),
    ('lfs_5-3_000001082693.xls', '長期05', '000001082693', 'lfs_employed_by_industry_jsic10.csv', '第10回改定日本標準産業分類'),
]
JP = re.compile('[぀-ヿ㐀-鿿]')


def nm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))


os.makedirs('data/acquired/domestic-stats', exist_ok=True)
for fn, sh, sid, out, cls in SETS:
    rows = dict(sheets('.local/domestic-stats/raw/' + fn))[sh]
    labels = {}
    for c in range(2, len(rows[6])):
        for ri in (5, 6, 7):
            v = rows[ri][c] if c < len(rows[ri]) else None
            if v and JP.search(str(v)):
                labels[c] = nm(v)
                break
    # シートは 男女計|男|女 が横に並ぶ。最初のブロック(男女計)だけ使う
    first = list(labels.items())
    cut = next((i for i, (c, l) in enumerate(first) if i > 0 and l == '総数'), len(first))
    labels = dict(first[:cut])
    n = 0
    with open('data/acquired/domestic-stats/' + out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['年', '産業', '値', '単位', '出典URL', '産業分類'])
        for r in rows[9:]:
            y = r[1] if len(r) > 1 else None
            if isinstance(y, (int, float)) and 1900 < y < 2100:
                for c, lab in labels.items():
                    v = r[c] if c < len(r) else None
                    if isinstance(v, (int, float)):
                        v = int(v) if float(v).is_integer() else v
                    else:
                        v = ''
                    w.writerow([int(y), lab, v, '万人', D + sid, cls])
                    n += 1
    print(out, n, len(labels), list(labels.values()))
