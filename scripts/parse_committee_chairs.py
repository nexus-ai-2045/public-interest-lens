#!/usr/bin/env python3
"""参議院・衆議院の常任委員長を原本から committee-chairs.csv にする。"""
from pathlib import Path
import re, csv, os, glob, unicodedata
from html import unescape

ROOT = os.path.join(str(Path(__file__).resolve().parent), '..')
RAW = os.path.join(ROOT, '.local/office-holders/raw')
OUT = os.path.join(ROOT, 'data/acquired/office-holders/committee-chairs.csv')
ERA = {'昭和': 1925, '平成': 1988, '令和': 2018}


def tx(s):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', s))).strip()


def seireki(s):
    m = re.search(r'(昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日', unicodedata.normalize('NFKC', s))
    if not m:
        return ''
    y = ERA[m.group(1)] + (1 if m.group(2) == '元' else int(m.group(2)))
    return '%04d-%02d-%02d' % (y, int(m.group(3)), int(m.group(4)))


def dec(path):
    b = open(path, 'rb').read()
    for e in ('utf-8', 'cp932'):
        try:
            return b.decode(e)
        except Exception:
            pass
    return b.decode('utf-8', 'replace')


rows = []
HDR = ['院', '国会回次', '委員会', '氏名', '会派', '就任日', '退任日', '時点_原表記', '時点_西暦', '備考', '出典URL']

# 参議院
for f in sorted(glob.glob(RAW + '/sangiin/yakuin_*.htm')):
    n = int(re.search(r'yakuin_(\d+)', f).group(1))
    t = dec(f)
    url = 'https://www.sangiin.go.jp/japanese/joho1/kousei/giin/%d/yakuin.htm' % n
    s = tx(t)
    asof = re.search(r'(令和\d+年\d+月\d+日|平成\d+年\d+月\d+日)\s*現在', unicodedata.normalize('NFKC', s))
    asof = asof.group(1) + '現在' if asof else ''
    sess = re.search(r'第\d+回国会（[^）]*）(?:（[^）]*）)?', s)
    sess = sess.group(0) if sess else ''
    i = t.find('常任委員長')
    j = t.find('特別委員長', i + 10)
    seg = t[i:j if j > 0 else None]
    for m in re.finditer(r'<th[^>]*class="col02"[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>', seg, re.S):
        com, name, party = tx(m.group(1)), tx(m.group(2)), tx(m.group(3))
        com = com.replace('＜正字＞', '').strip()
        name = re.sub(r'\s+', ' ', name.replace('　', ' ')).strip()
        name = name.replace('＜正字＞', '').strip()
        if not com.endswith('委員長'):
            continue
        rows.append(['参議院', str(n), com[:-3] + '委員会', name, party.replace('\xa0', '').strip(), '', '', asof, seireki(asof),
                     '原表は国会回次ごとの在任者のみで就任日・退任日の記載なし。' + sess + ('。委員長が空欄の委員会は原表でも空欄（未選任）' if not name else ''),
                     url])

# 衆議院「衆議院の動き」(平成11-15年) の各委員会ページ
for f in sorted(glob.glob(RAW + '/shugiin/1[45]?*.htm')):
    b = os.path.basename(f)
    if b.startswith('mokuj'):
        continue
    n = int(b[:3])
    t = dec(f)
    s = tx(t)
    sn = unicodedata.normalize('NFKC', s).replace('\u3000', ' ')
    mt = re.match(r'\s*(\S+?委員会)【第(\d+)回国会】', sn)
    ms = re.search(r'第\d+回国会\(([^)]*)\)', sn)
    if mt:
        com = mt.group(1)
    else:
        mo = re.search(r'○\s*(\S+?委員会)\s*1\s*委員名簿', sn)
        if not mo:
            print('NOTITLE', b)
            continue
        com = mo.group(1)
    mm = re.search(r'委員名簿\s*\(\d+\)\s*委員長\s*(.+?)君\s*(自民|民主|公明|自由|共産|社民|保守新|保守|明改|無会|和|無所属|改革|二十一|[^\s理]{0,3})', sn)
    if not mm:
        print('NOCHAIR', b)
        continue
    class _M:
        def group(self, i):
            return {2: ms.group(1) if ms else ''}[i]
    m = _M()
    y = {143: 11, 144: 11, 145: 11}.get(n)
    if y is None:
        y = 12 if n <= 149 else 13 if n <= 152 else 14 if n <= 155 else 15
    url = 'https://www.shugiin.go.jp/internet/itdb_annai.nsf/html/statics/ugoki/h%dugoki/%d/%s' % (y, n, b)
    rows.append(['衆議院', str(n), com, mm.group(1).strip(), mm.group(2), '', '', '', '',
                 '原表は国会回次ごとの委員名簿（委員長）のみで就任日・退任日の記載なし。第%d回国会（%s）' % (n, m.group(2)), url])

rows.sort(key=lambda r: (r[0], -int(r[1]), r[2]))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8', newline='') as fp:
    w = csv.writer(fp)
    w.writerow(HDR)
    w.writerows(rows)
from collections import Counter
print(len(rows), Counter(r[0] for r in rows))
