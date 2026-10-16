#!/usr/bin/env python3
"""衆議院「衆議院の動き」(平成11〜15年、第143〜158回国会) の委員会ページを取得する。
1.1秒以上あけ、manifest.csv に記録する。原本は .local/office-holders/raw/shugiin/ に保存。"""
from pathlib import Path
import os, re, time, hashlib, subprocess, datetime, csv

ROOT = os.path.join(str(Path(__file__).resolve().parent), '..')
R = os.path.join(ROOT, '.local/office-holders')
RAW = os.path.join(R, 'raw/shugiin')
os.makedirs(RAW, exist_ok=True)
B = 'https://www.shugiin.go.jp/internet/itdb_annai.nsf/html/statics/ugoki'
YEAR = {}
for y, a, b in [(11, 143, 145), (12, 146, 149), (13, 150, 152), (14, 153, 155), (15, 156, 158)]:
    for n in range(a, b + 1):
        YEAR[n] = y


def get(url, fname):
    p = os.path.join(RAW, fname)
    r = subprocess.run(['curl', '-sSL', '-A', 'public-interest-lens', '-m', '40', '-o', p, '-w', '%{http_code}', url],
                       capture_output=True, text=True)
    code = r.stdout.strip()
    h = hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else ''
    with open(os.path.join(R, 'manifest.csv'), 'a', newline='') as fp:
        csv.writer(fp).writerow([url, 'shugiin/' + fname, h, code, datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')])
    time.sleep(1.2)
    return code, p


for n in sorted(YEAR):
    y = YEAR[n]
    base = '%s/h%dugoki/%d' % (B, y, n)
    code, p = get('%s/mokuj%d.htm' % (base, n), 'mokuj%d.htm' % n)
    if code != '200':
        continue
    t = open(p, 'rb').read().decode('cp932', errors='replace')
    for h, x in re.findall(r'href="([^"#]*\.htm)"[^>]*>(.*?)</a>', t, re.S):
        x = re.sub(r'<[^>]+>', '', x).strip()
        if x.endswith('委員会') and '特別' not in x and h.startswith(str(n)):
            get('%s/%s' % (base, h), h)
open(os.path.join(R, 'shugiin.done'), 'w').write('done')
