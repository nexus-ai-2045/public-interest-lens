#!/usr/bin/env python3
"""首相官邸 歴代内閣ページ（.local/office-holders/raw/cNNN.html）から cabinet.csv を作る。

氏名が文字ではなく外字の画像（<img class="... gaiji ..." src="./img/gaiji/〇〇.png">）で書かれた行がある。
画像の alt は漢字のときと読みだけのときがあるので使わず、画像のファイル名から対応表
data/acquired/office-holders/cabinet-gaiji.csv（画像を目で読んで起こした氏名と、その出典）で氏名を引く。
対応表に無い画像、読みが対応表と合わない行、取得した画像が対応表の sha256 と違うもの、氏名が空の行が1つでもあれば、CSV を書かずに止まる。
"""
import csv
import hashlib
import os
import re
import sys
import unicodedata
from html import unescape
from pathlib import Path

ROOT = os.path.join(str(Path(__file__).resolve().parent), '..')
RAW = os.path.join(ROOT, '.local/office-holders/raw')
OUT = os.path.join(ROOT, 'data/acquired/office-holders/cabinet.csv')
GAIJI_CSV = os.path.join(ROOT, 'data/acquired/office-holders/cabinet-gaiji.csv')
GAIJI_IMG = re.compile(r'<img\b[^>]*\bgaiji\b[^>]*>', re.DOTALL)
ERA = {'昭和': 1925, '平成': 1988, '令和': 2018}
DRE = r'((?:昭和|平成|令和)(?:元|\d+)年\d+月\d+日)'


def nf(s):
    s = unescape(re.sub(r'<[^>]+>', '', s))
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', s).replace('~', '～')).strip()


def load_gaiji(path=GAIJI_CSV):
    """外字画像のファイル名 → {氏名, 読み}。"""
    with open(path, encoding='utf-8', newline='') as fp:
        return {r['画像']: r for r in csv.DictReader(fp)}


def kana_key(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))


GAIJI_DIR = os.path.join(RAW, 'gaiji')
SRC = re.compile(r'''src\s*=\s*["']([^"']*)["']''')


def gaiji_key(img, gaiji, where=''):
    """<img> から対応表の鍵（画像のファイル名）を出す。src が無い・対応表に無い画像は止める。"""
    src = SRC.search(img)
    key = os.path.basename(src.group(1)) if src else ''
    if key not in gaiji:
        raise SystemExit(f'外字画像 {key!r} が cabinet-gaiji.csv に無い（{where}）。画像を読んで氏名と出典を足す。')
    return key


def resolve_gaiji(cell, gaiji, where=''):
    """氏名のセルの外字画像を、対応表の氏名（文字）に置き換える。対応表に無い画像は止める。"""
    return GAIJI_IMG.sub(lambda m: gaiji[gaiji_key(m.group(0), gaiji, where)]['氏名'], cell)


def check_gaiji_kana(cell, kana, gaiji, where=''):
    """外字画像の行は、ページの読みが対応表の読みと同じかを確かめる（同じファイル名で別人の画像に差し替わったら止める）。
    ページに読みが無い行（古い代のページ・「（兼）」の行）は比べようが無いので確かめない。"""
    for m in GAIJI_IMG.finditer(cell):
        key = gaiji_key(m.group(0), gaiji, where)
        if kana and kana_key(kana) != kana_key(gaiji[key]['読み']):
            raise SystemExit(f"外字画像 {key!r} の読みが対応表と違う：ページ {kana!r}、対応表 {gaiji[key]['読み']!r}（{where}）")


def check_gaiji_images(gaiji, folder=GAIJI_DIR):
    """取得した外字画像が、対応表に記録した sha256 と同じかを確かめる（画像が差し替わったら読み直すまで止める）。
    画像を取っていない環境では確かめられないので、確かめた枚数を返す。"""
    checked = 0
    for key, r in gaiji.items():
        path = os.path.join(folder, key)
        if not os.path.exists(path):
            continue
        with open(path, 'rb') as fp:
            digest = hashlib.sha256(fp.read()).hexdigest()
        if digest != r['画像のsha256']:
            raise SystemExit(f'外字画像 {key!r} が対応表の sha256 と違う。画像を読み直して cabinet-gaiji.csv を直す。')
        checked += 1
    return checked


def empty_name_rows(rows, name_col=2):
    """氏名が空の行（1始まりのデータ行番号と行）。1つでもあれば CSV を書かない。"""
    return [(i, r) for i, r in enumerate(rows, 1) if not str(r[name_col]).strip()]


def seireki(s):
    if not s:
        return ''
    m = re.match(r'(昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日', s)
    if not m:
        return ''
    y = ERA[m.group(1)] + (1 if m.group(2) == '元' else int(m.group(2)))
    return '%04d-%02d-%02d' % (y, int(m.group(3)), int(m.group(4)))


def parse_page(n, gaiji):
    f = os.path.join(RAW, 'c%03d.html' % n)
    t = open(f, encoding='utf-8').read()
    url = 'https://www.kantei.go.jp/jp/rekidainaikaku/%03d.html' % n
    m = re.search(r'在職期間</dt>\s*<dd>(.*?)</dd>', t, re.DOTALL)
    period = nf(m.group(1)) if m else ''
    pm_end = ''
    mm = re.search(r'～\s*' + DRE, period)
    if mm:
        pm_end = mm.group(1)
    secs = re.split(r'(?=<section>)', t)
    secs = [s for s in secs if s.startswith('<section>') and '<h2 id="link' in s]
    stages = []
    for s in secs:
        h = nf(re.search(r'<h2[^>]*>(.*?)</h2>', s, re.DOTALL).group(1))
        note = re.search(r'module-text--note">(.*?)</p>', s, re.DOTALL)
        note = nf(note.group(1)) if note else ''
        sm = re.search(DRE, note)
        start = sm.group(1) if sm else ''
        items = re.split(r'(?=<div class="module-accordion__item)', s)[1:]
        tabs = []
        for it in items:
            tab = nf(re.search(r'<button[^>]*>(.*?)<span', it, re.DOTALL).group(1))
            rows = []
            for tr in re.findall(r'<tr>(.*?)</tr>', it, re.DOTALL):
                th = re.search(r'<th scope="row">(.*?)</th>', tr, re.DOTALL)
                td = re.search(r'<td>(.*?)</td>', tr, re.DOTALL)
                if not th or not td:
                    continue
                lis = [nf(x) for x in re.findall(r'<li>(.*?)</li>', th.group(1), re.DOTALL)] or [nf(th.group(1))]
                raw_td = td.group(1)
                rows.append((lis, nf(resolve_gaiji(raw_td, gaiji, url)), raw_td))
            tabs.append((tab, rows))
        stages.append((h, start, note, tabs))
    return url, pm_end, stages


def main():
    out = []
    gaiji = load_gaiji()
    print('外字画像の sha256 を確かめた：', check_gaiji_images(gaiji), '/', len(gaiji))
    for n in range(67, 106):
        url, pm_end, stages = parse_page(n, gaiji)
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
                for lis, name, raw_td in rows:
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
                    check_gaiji_kana(raw_td, kana, gaiji, url)
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
    empty = empty_name_rows(out)
    if empty:
        for i, r in empty:
            print(f'氏名が空：データ行 {i} {r[0]} {r[1]} {r[3]} {r[4]}', file=sys.stderr)
        raise SystemExit(f'氏名が空の行が {len(empty)} 行ある。cabinet.csv は書かない。')
    hdr = ['内閣名', '区分', '氏名', '読み', '役職', '所管', '就任日', '就任日_西暦', '退任日', '退任日_西暦', '備考', '出典URL']
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(hdr)
        w.writerows(out)
    from collections import Counter
    print(len(out), Counter(r[1] for r in out))
    print('no start:', sum(1 for r in out if not r[6]), 'no seireki:', sum(1 for r in out if r[6] and not r[7]))


if __name__ == '__main__':
    main()
