#!/usr/bin/env python3
"""首相官邸 歴代内閣ページ（.local/office-holders/raw/cNNN.html）から cabinet.csv を作る。"""
from pathlib import Path
import re, csv, sys, unicodedata, os
from html import unescape

ROOT = os.path.join(str(Path(__file__).resolve().parent), '..')
RAW = os.path.join(ROOT, '.local/office-holders/raw')
OUT = os.path.join(ROOT, 'data/acquired/office-holders/cabinet.csv')
ERA = {'昭和': 1925, '平成': 1988, '令和': 2018}
DRE = r'((?:昭和|平成|令和)(?:元|\d+)年\d+月\d+日)'


def nf(s):
    s = unescape(re.sub(r'<[^>]+>', '', s))
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', s).replace('~', '～')).strip()


def seireki(s):
    if not s:
        return ''
    m = re.match(r'(昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日', s)
    if not m:
        return ''
    y = ERA[m.group(1)] + (1 if m.group(2) == '元' else int(m.group(2)))
    return '%04d-%02d-%02d' % (y, int(m.group(3)), int(m.group(4)))


def parse_page(n):
    f = os.path.join(RAW, 'c%03d.html' % n)
    t = open(f, encoding='utf-8').read()
    url = 'https://www.kantei.go.jp/jp/rekidainaikaku/%03d.html' % n
    m = re.search(r'在職期間</dt>\s*<dd>(.*?)</dd>', t, re.S)
    period = nf(m.group(1)) if m else ''
    pm_end = ''
    mm = re.search(r'～\s*' + DRE, period)
    if mm:
        pm_end = mm.group(1)
    secs = re.split(r'(?=<section>)', t)
    secs = [s for s in secs if s.startswith('<section>') and '<h2 id="link' in s]
    stages = []
    for s in secs:
        h = nf(re.search(r'<h2[^>]*>(.*?)</h2>', s, re.S).group(1))
        note = re.search(r'module-text--note">(.*?)</p>', s, re.S)
        note = nf(note.group(1)) if note else ''
        sm = re.search(DRE, note)
        start = sm.group(1) if sm else ''
        items = re.split(r'(?=<div class="module-accordion__item)', s)[1:]
        tabs = []
        for it in items:
            tab = nf(re.search(r'<button[^>]*>(.*?)<span', it, re.S).group(1))
            rows = []
            for tr in re.findall(r'<tr>(.*?)</tr>', it, re.S):
                th = re.search(r'<th scope="row">(.*?)</th>', tr, re.S)
                td = re.search(r'<td>(.*?)</td>', tr, re.S)
                if not th or not td:
                    continue
                lis = [nf(x) for x in re.findall(r'<li>(.*?)</li>', th.group(1), re.S)] or [nf(th.group(1))]
                rows.append((lis, nf(td.group(1))))
            tabs.append((tab, rows))
        stages.append((h, start, note, tabs))
    return url, pm_end, stages


def main():
    out = []
    for n in range(67, 106):
        url, pm_end, stages = parse_page(n)
        for si, (h, start, note, tabs) in enumerate(stages):
            if si + 1 < len(stages):
                end_stage = stages[si + 1][1]
            else:
                end_stage = pm_end
            for tab, rows in tabs:
                kind = '閣僚'
                if '副大臣' in tab:
                    kind = '副大臣'
                elif '政務官' in tab:
                    kind = '大臣政務官'
                elif '補佐官' in tab:
                    continue
                recs = []
                for lis, name in rows:
                    dates = [x for x in lis if re.search(DRE, x)]
                    others = [x for x in lis if x not in dates]
                    s0, e0, explicit = start, '', False
                    if dates:
                        ds = re.findall(DRE, dates[0])
                        if dates[0].strip().startswith('～'):
                            e0 = ds[0]
                        else:
                            s0 = ds[0]
                            explicit = True
                            if len(ds) > 1:
                                e0 = ds[1]
                    kana = ''
                    mk = re.match(r'(.*?)\s*[(（](.+?)[)）]$', name)
                    if mk and '兼' not in mk.group(2):
                        name, kana = mk.group(1).strip(), mk.group(2)
                    note2 = ''
                    if re.search(r'[(（]兼[)）]', name):
                        name = re.sub(r'\s*[(（]兼[)）]', '', name)
                        note2 = '兼務'
                    recs.append(dict(role=others[0] if others else '', area=' / '.join(others[1:]),
                                     name=name, kana=kana, s=s0, e=e0, explicit=explicit, note=note2))
                for i, r in enumerate(recs):
                    if r['explicit'] and not r['e']:
                        for j in range(i - 1, -1, -1):
                            p = recs[j]
                            if p['role'] == r['role'] and not p['e'] and p['name'] != r['name']:
                                p['e'] = r['s']
                                break
                # 「A～B」の行（前任）と同じ役職で日付の無い行は後任とみなし、就任日を B とする（備考に明記）
                for r in recs:
                    if r['e'] and r['explicit']:
                        cand = [q for q in recs if q is not r and q['role'] == r['role'] and q['area'] == r['area']
                                and not q['explicit'] and not q['e'] and q['s'] == start and q['name'] != r['name']
                                and not q['note']]
                        same_end = [q for q in recs if q['role'] == r['role'] and q['area'] == r['area']
                                    and q['e'] and q['explicit']]
                        undated_same = [q for q in recs if q['role'] == r['role'] and q['area'] == r['area']
                                        and not q['explicit']]
                        if len(cand) == 1 and len(same_end) == 1 and len(undated_same) == 1:
                            cand[0]['s'] = r['e']
                            cand[0]['note'] = '就任日は同役職の前任行の退任日（原表では日付なし）'
                for r in recs:
                    e = r['e'] or end_stage
                    out.append([h, kind, r['name'], r['kana'], r['role'], r['area'],
                                r['s'], seireki(r['s']), e, seireki(e), r['note'], url])
    hdr = ['内閣名', '区分', '氏名', '読み', '役職', '所管', '就任日', '就任日_西暦', '退任日', '退任日_西暦', '備考', '出典URL']
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(hdr)
        w.writerows(out)
    from collections import Counter
    print(len(out), Counter(r[1] for r in out))
    print('no start:', sum(1 for r in out if not r[6]), 'no seireki:', sum(1 for r in out if r[6] and not r[7]))


main()
