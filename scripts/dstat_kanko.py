"""観光庁 宿泊旅行統計調査 推移表(旧1-1,旧2-1,旧3-1 年計, 全国)をCSVにする。"""
import csv, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from dstat_xl import sheets

URL = 'https://www.mlit.go.jp/kankocho/content/002026697.xlsx'
S = dict(sheets('.local/domestic-stats/raw/kanko_suiihyo_002026697.xlsx'))
IND = [('旧1-1', '延べ宿泊者数'), ('旧2-1', '日本人延べ宿泊者数'), ('旧3-1', '外国人延べ宿泊者数')]


def year(s):
    s = s.replace('　', '').replace(' ', '')
    m = re.match(r'(平成|令和)(元|\d+)年', s)
    n = 1 if m.group(2) == '元' else int(m.group(2))
    return (1988 if m.group(1) == '平成' else 2018) + n


os.makedirs('data/acquired/domestic-stats', exist_ok=True)
n = 0
with open('data/acquired/domestic-stats/kanko_lodging_annual.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['年', '指標', '値', '単位', '出典URL'])
    for sh, name in IND:
        rows = S[sh]
        hdr = rows[2]
        nat = next(r for r in rows if r[0] and r[0].replace('　', '') == '全国')
        for c in range(1, len(hdr)):
            if hdr[c] and re.match(r'(平成|令和)', str(hdr[c])):
                v = nat[c]
                w.writerow([year(hdr[c]), name, '' if v is None else int(v), '人泊', URL + '#' + sh])
                n += 1
print(n)
