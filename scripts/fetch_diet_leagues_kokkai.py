#!/usr/bin/env python3
"""国会会議録の発言から、議員連盟の役員を本人が名乗った発言だけ拾う（diet-leagues の候補作り）。

本人が「私は◯◯議員連盟の会長（事務局長・幹事長・副会長）を務めて／しており」と述べた発言だけを採る。
他人の紹介や「会長の◯◯先生」は採らない（推測で埋めない）。分野（所管省庁）は議連名のキーワード表で決め、
当たらないものは空のまま（空の行は build_zoku が読まない）。
使い方: python3 scripts/fetch_diet_leagues_kokkai.py [--out data/acquired/diet-leagues/kokkai-candidates.csv]
"""
import argparse, csv, json, re, time, urllib.parse, urllib.request
from datetime import date

API = 'https://kokkai.ndl.go.jp/api/speech'
ROLE = r'(会長代行|会長代理|副会長|事務局長|事務局次長|幹事長|会長)'
SELF = re.compile(r'(?:私|わたくし|私ども)[^。]{0,40}?([一-龥ぁ-んァ-ヶー・A-Za-z0-9]{2,30}議員連盟)の?' + ROLE + r'(?:を|も)?(?:務め|しており|させて|やって|いたして|をしている)')
FIELD = [('たばこ', '財務省'), ('受動喫煙', '厚生労働省'), ('禁煙', '厚生労働省'), ('遊技', '警察庁'), ('パチンコ', '警察庁'), ('観光', '国土交通省'),
         ('半導体', '経済産業省'), ('水素', '経済産業省'), ('原子力', '経済産業省'), ('電力', '経済産業省'), ('再生可能', '経済産業省'), ('エネルギー', '経済産業省'),
         ('自動車', '経済産業省'), ('ギャンブル', '内閣府'), ('IR', '国土交通省'), ('農', '農林水産省'), ('漁', '農林水産省'), ('林', '農林水産省'),
         ('医', '厚生労働省'), ('介護', '厚生労働省'), ('建設', '国土交通省'), ('道路', '国土交通省'), ('住宅', '国土交通省'), ('デジタル', 'デジタル庁'), ('金融', '金融庁')]


def get(params):
    url = API + '?' + urllib.parse.urlencode(dict(params, recordPacking='json', maximumRecords=100))
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            err = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'{url}: {err}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='data/acquired/diet-leagues/kokkai-candidates.csv')
    a = ap.parse_args()
    seen, rows, pos = set(), [], 1
    while True:
        d = get({'any': '議員連盟', 'startRecord': pos})
        for s in d.get('speechRecord', []):
            for m in SELF.finditer(s['speech'].replace('　', '')):
                key = (m.group(1), s['speaker'], m.group(2))
                if key in seen:
                    continue
                seen.add(key)
                f = next((v for k, v in FIELD if k in m.group(1)), '')
                rows.append([m.group(1), s['speaker'], m.group(2), f, '会議録', s['speechURL'], s['date']])
        nxt = d.get('nextRecordPosition')
        if not nxt:
            break
        pos = nxt
        time.sleep(1.0)
    rows.sort()
    with open(a.out, 'w', newline='', encoding='utf-8') as fp:
        w = csv.writer(fp, lineterminator='\n')
        w.writerow(['議連名', '氏名', '役職', '分野', '出典種別', '出典URL', '発言日'])
        w.writerows(rows)
    print(len(rows), 'rows;', sum(1 for r in rows if r[3]), 'with field')


if __name__ == '__main__':
    main()
