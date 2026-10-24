"""税の帳簿（金融政策・税の1本目）：消費税率を変えた法律の額を、政府のマクロモデルの乗数で出す。

案はプロジェクトの共有フォルダ analysis/税の帳簿_案_2026-10-24.md。議員の点数にも、法律の額（allocation-v1）にも足さない別の帳簿。
- 乗数：内閣府 経済社会総合研究所「短期日本経済マクロ計量モデル（2018年版）」表2-5（消費税率を1%ポイント引上げ、実質GDP の乖離率）。
- 物差し：実質GDP（2020年基準・連鎖、暦年）。名目の2020年の合計×実質の指数÷100 で2020年の円にする。
- 引上げ：損失 ＝ Σ（k=1〜3）実質GDP（1年目+k−1）× 乗数_k × 上げ幅。1年目は、施行から12か月のうち多くを含む暦年。
- 延期：便益 ＝ 前の予定で上げていた場合に、延期した期間（前の予定の1年目から新しい予定の1年目の前年まで、最大3年）に生じた減少。
  延期の後に実際に上げた分の減少は、上げた法律（閣法-180-72）に数える。
確かさは「低」。印は「定説（政府モデル）」「需要の短期効果だけ（税収の使い道の効果を含まない）」。

使い方（リポジトリのルートで）: python3 scripts/build_tax_ledger.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENACTED = ROOT / 'data/acquired/bill-census-full/enacted.csv'
SNA = ROOT / 'data/acquired/domestic-stats/sna_gdp_by_industry_2020base.csv'
OUT = ROOT / 'data/derived/tax-v1/consumption-tax.csv'
ESRI = 'https://www.esri.cao.go.jp/jp/esri/archive/e_rnote/e_rnote050/e_rnote041.pdf'
MULTIPLIER = {1: -0.0028, 2: -0.0019, 3: -0.0020}  # 表2-5 実質GDP（%）の1〜3年目

# 消費税率（国・地方の合計、標準税率）を変えた法律。日付は法律の本文（附則）の施行日。
CHANGES = [
    {'法律ID': '閣法-180-72', '種類': '引上げ', '内容': '5%→8%', '上げ幅': 3, '施行日': '2014-04-01',
     '出典URL': 'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/keika/359E.htm', '注': ''},
    {'法律ID': '閣法-180-72', '種類': '引上げ', '内容': '8%→10%（2度の延期の後、実際の施行日）', '上げ幅': 2, '施行日': '2019-10-01',
     '出典URL': 'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/keika/359E.htm',
     '注': '軽減税率（飲食料品などは8%のまま）があり、標準税率の2ポイントで測ると効果を大きめに見積もる。1年目以降はコロナ期と重なる'},
    {'法律ID': '閣法-189-3', '種類': '延期', '内容': '10%への引上げを2015-10-01から2017-04-01へ', '上げ幅': 2, '施行日': '2015-10-01', '新しい施行日': '2017-04-01',
     '出典URL': 'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/keika/47F6.htm', '注': ''},
    {'法律ID': '閣法-192-3', '種類': '延期', '内容': '10%への引上げを2017-04-01から2019-10-01へ', '上げ幅': 2, '施行日': '2017-04-01', '新しい施行日': '2019-10-01',
     '出典URL': 'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/keika/1DC180A.htm', '注': ''},
]


def first_year(day: str) -> int:
    """施行から12か月のうち多くを含む暦年（4月施行はその年、10月施行は翌年）。"""
    y, m = int(day[:4]), int(day[5:7])
    return y if m <= 6 else y + 1


def real_gdp() -> dict[int, float]:
    """暦年の実質GDP（2020年の円）。"""
    with SNA.open(encoding='utf-8', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['経済活動'] == '合計']
    base = next(float(r['値']) for r in rows if r['価格'] == '名目' and r['年'] == '2020') * 1e9
    return {int(r['年']): base * float(r['値']) / 100 for r in rows if r['価格'].startswith('実質')}


HEADER = ['法律ID', '題名', '種類', '内容', '年', '何年目', '上げ幅', '乗数', '実質GDP_円', '額_円', '向き', '確かさ', '印', '出典URL', '乗数の出典', 'GDPの出典', '注']


def build() -> dict[str, int]:
    gdp = real_gdp()
    with ENACTED.open(encoding='utf-8', newline='') as f:
        titles = {f"{r['種別']}-{r['提出回次']}-{r['番号']}": r['題名'] for r in csv.DictReader(f)}
    rows = []
    for c in CHANGES:
        start = first_year(c['施行日'])
        years = range(start, start + 3) if c['種類'] == '引上げ' else range(start, min(start + 3, first_year(c['新しい施行日'])))
        for y in years:
            k = y - start + 1
            if y not in gdp:
                continue  # まだ統計が無い年は数えない
            amount = gdp[y] * MULTIPLIER[k] * c['上げ幅']
            if c['種類'] == '延期':
                amount = -amount  # 避けた減少は便益
            rows.append({'法律ID': c['法律ID'], '題名': titles[c['法律ID']], '種類': c['種類'], '内容': c['内容'], '年': y, '何年目': k, '上げ幅': c['上げ幅'], '乗数': MULTIPLIER[k],
                         '実質GDP_円': round(gdp[y]), '額_円': round(amount), '向き': '損失' if amount < 0 else '便益', '確かさ': '低',
                         '印': '定説（政府モデル）／需要の短期効果だけ（税収の使い道の効果を含まない）', '出典URL': c['出典URL'], '乗数の出典': ESRI,
                         'GDPの出典': 'data/acquired/domestic-stats/sna_gdp_by_industry_2020base.csv', '注': c['注']})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    totals: dict[str, int] = {}
    for r in rows:
        totals[r['法律ID']] = totals.get(r['法律ID'], 0) + r['額_円']
    return totals


if __name__ == '__main__':
    print(json.dumps({k: f'{v / 1e12:+.2f}兆円' for k, v in build().items()}, ensure_ascii=False))
    sys.exit(0)
