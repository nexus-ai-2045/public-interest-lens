"""教育界の影響の帳簿（education-ledger-v1、R32）を作る。

入力: data/acquired/education/education-stats.csv（scripts/fetch_education_stats.py）、
      data/derived/education-ledger-v1/actions.csv（手で書いた行動の台帳。法律ID は全法律の一覧にあるもの）、
      data/derived/all-laws-v1/outcomes.csv、data/derived/allocation-v1/（議員の関与）。
出力: data/derived/education-ledger-v1/ の comparators.csv・indicator-gaps.csv・chains.csv・law-links.csv。

方法（docs/design/教育界の影響の測り方_2026-10-29.md）:
- 比べる相手は OECD 加盟国の中央値。2000年の就業者1人当たり GDP が日本の8割未満の国とアイルランドは除く。
  年ごとの比較国が3か国未満なら比較しない。
- 指標ごとに「日本 − 中央値」の差を年ごとに出し、施行年 t0 の前3年（t0-3〜t0-1）と後2年（t0+1〜t0+2）の平均の差を比べる（差の差）。
  開始前5年の趨勢を後の年へ延ばして引いた値も並べる。後2年が最新年を超える行為は「暫定」（窓が満ちていない）。
- 額は付けない。額は「機構 × 根拠値（台帳 data/evidence/）× 規模」で出す決まりで、教育領域の根拠値が台帳で採用されるまで未測定。
  規模は指標の差（GDP 比のポイント）までを出す。

使い方（リポジトリのルートで）: python3 scripts/build_education_ledger.py
"""
from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / 'data/acquired/education/education-stats.csv'
LEDGER = ROOT / 'data/derived/education-ledger-v1'
ACTIONS = LEDGER / 'actions.csv'
OUTCOMES = ROOT / 'data/derived/all-laws-v1/outcomes.csv'
ALLOC = ROOT / 'data/derived/allocation-v1'
CATCH_UP_RATIO = 0.8
MIN_COUNTRIES = 3
PRE, POST, TREND = 3, 2, 5
VERSION = 'education-ledger-v1'
NEEDS = {  # 機構 -> 額の計算に要る根拠値（台帳 data/evidence/ の量。採用されるまで額は出さない）
    '研究への公的投入': '公的研究開発費の生産性への収益率（R&D 収益率・波及のメタ分析）',
    '研究への公的投入・大学の自律': '公的研究開発費の収益率／大学の数・規模と成長（大学の経済効果の推計）',
    '研究への公的投入・人材': '研究者数と生産性の弾性値／博士人材の賃金プレミアム',
    '産学連携': '大学研究の波及（R&D 波及のメタ分析）',
    '人的資本の量': '就学1年当たりの収益率（ミンサー式のメタ分析）と成長への寄与',
    '人的資本の質': '認知スキルと成長・賃金（PISA・PIAAC の推計）',
    '大学の自律': '大学の制度と研究成果（日本の法人化の差の差の研究）',
    '大学の自律・人的資本の量': '大学の制度と研究成果／就学1年当たりの収益率',
    '行政組織': '（効果を測る指標がない）',
}


def read(path: Path) -> list[dict]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def load_stats(rows: list[dict]) -> dict[str, dict[str, dict[int, float]]]:
    out: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        try:
            out[r['系列']][r['国']][int(r['年'])] = float(r['値'])
        except ValueError:
            continue
    return out


def comparators(stats) -> tuple[list[str], list[dict]]:
    """比べる国。2000年の就業者1人当たり GDP（購買力平価）が日本の8割以上の国。"""
    gdp, emp = stats['GDP（購買力平価）'], stats['就業者数']

    def per_worker(c):
        if 2000 in gdp.get(c, {}) and 2000 in emp.get(c, {}):
            return gdp[c][2000] * 1e6 / (emp[c][2000] * 1e3)
        return None

    jp = per_worker('JPN')
    used, report = [], []
    for c in sorted(set(gdp) | set(emp)):
        if c == 'JPN':
            continue
        v = per_worker(c)
        if c == 'IRL':
            used_, why = False, '多国籍企業の計上でゆがむため除く'
        elif v is None:
            used_, why = False, '2000年の GDP か就業者数がなく、基準を確かめられない'
        elif v < jp * CATCH_UP_RATIO:
            used_, why = False, '追い上げの段階（2000年の就業者1人当たり GDP が日本の8割未満）'
        else:
            used_, why = True, ''
        if used_:
            used.append(c)
        report.append({'国': c, '2000年の就業者1人当たりGDP対日本': '' if v is None else f'{v / jp:.3f}', '採用': 'はい' if used_ else 'いいえ', '理由': why})
    return used, report


def gaps(stats, series: str, used: list[str]) -> dict[int, dict]:
    jp = stats[series].get('JPN', {})
    out = {}
    for y, v in sorted(jp.items()):
        vals = [stats[series][c][y] for c in used if y in stats[series].get(c, {})]
        if len(vals) >= MIN_COUNTRIES:
            m = statistics.median(vals)
            out[y] = {'日本': v, '中央値': m, '差': v - m, '比較国数': len(vals)}
    return out


def ols_predict(points: list[tuple[int, float]], x: float) -> float:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    slope = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sxx
    return my + slope * (x - mx)


def did(g: dict[int, dict], t0: int) -> dict:
    """施行年 t0 の差の差。前3年・後2年が揃わなければ状態に理由を書く。"""
    pre = [g[y]['差'] for y in range(t0 - PRE, t0) if y in g]
    post = [g[y]['差'] for y in range(t0 + 1, t0 + POST + 1) if y in g]
    if len(pre) < 2:
        return {'状態': '測定不能', '理由': f'施行前{PRE}年のうち比較できる年が2年未満'}
    pre_m = statistics.fmean(pre)
    if not post:
        return {'状態': '暫定', '理由': '施行後の年のデータがまだない（窓が満ちていない）', '前の差': pre_m}
    post_m = statistics.fmean(post)
    res = {'前の差': pre_m, '後の差': post_m, '差の差': post_m - pre_m}
    if len(post) < POST:
        res.update(状態='暫定', 理由=f'施行後{POST}年のうち{len(post)}年だけ（窓が満ちていない）')
    else:
        res.update(状態='確定', 理由='')
    trend_pts = [(y, g[y]['差']) for y in range(t0 - TREND, t0) if y in g]
    if len(trend_pts) >= 4:
        pred = statistics.fmean(ols_predict(trend_pts, y) for y in range(t0 + 1, t0 + 1 + len(post)))
        res['趨勢除去後の差の差'] = post_m - pred
    return res


def fmt(x) -> str:
    return '' if x is None or x == '' else f'{x:.4f}'


def main() -> int:
    stats = load_stats(read(STATS))
    used, comp_rows = comparators(stats)
    write(LEDGER / 'comparators.csv', ['国', '2000年の就業者1人当たりGDP対日本', '採用', '理由'], comp_rows)
    actions = read(ACTIONS)
    outcomes = {r['id']: r for r in read(OUTCOMES)}
    series_all = sorted({s for a in actions for s in a['指標'].split(';') if s})
    gap_rows, gap_by = [], {}
    for s in series_all:
        g = gaps(stats, s, used)
        gap_by[s] = g
        for y, d in g.items():
            gap_rows.append({'指標': s, '年': y, '日本': fmt(d['日本']), '比較国の中央値': fmt(d['中央値']), '差（日本−中央値）': fmt(d['差']),
                             '比較国数': d['比較国数']})
    write(LEDGER / 'indicator-gaps.csv', ['指標', '年', '日本', '比較国の中央値', '差（日本−中央値）', '比較国数'], gap_rows)

    # 議員の関与：配分の入力（allocation-v1）に載っている法律だけ人数を出す。載っていない法律は「未取得」とし、0人とは書かない。
    inv = defaultdict(set)
    for name in ('involvements.csv', 'involvements-auto.csv'):
        for r in read(ALLOC / name):
            if r.get('算入') == 'はい' and r['人物ID']:
                inv[r['法律ID']].add(r['人物ID'])
    registered = {r['法律ID'] for name in ('involvements.csv', 'involvements-auto.csv') for r in read(ALLOC / name)}
    chain_rows, law_rows = [], []
    shared = defaultdict(int)
    for a in actions:
        for lid in a['法律ID'].split(';'):
            o = outcomes[lid]
            t0 = int(o['施行日'][:4]) if o['施行日'] else None
            for s in (a['指標'].split(';') if a['指標'] else []):
                if t0:
                    shared[(s, t0)] += 1
    for a in actions:
        for lid in a['法律ID'].split(';'):
            o = outcomes[lid]
            t0 = int(o['施行日'][:4]) if o['施行日'] else None
            law_rows.append({'行動ID': a['行動ID'], '法律ID': lid, '題名': o['題名'], '施行日': o['施行日'], '既存の結果': o['結果'],
                             '既存の額': o['損失または便益の額'],
                             '議員の関与': '登録あり' if lid in registered else '未取得（配分の入力に未登録）',
                             '関与した議員数（算入）': len(inv[lid]) if lid in registered else ''})
            inds = a['指標'].split(';') if a['指標'] else []
            need = NEEDS.get(a['機構'], '')
            if not inds:
                chain_rows.append({'行動ID': a['行動ID'], '法律ID': lid, '施行年': t0 or '', '指標': '', '状態': '指標なし',
                                   '理由': '効果を測る OECD・世界銀行の指標をまだ取得していない（量は人数・就学率、質は PISA・PIAAC が要る）',
                                   '前の差': '', '後の差': '', '差の差': '', '趨勢除去後の差の差': '', '比較国数': '', '同じ観測を共有する本数': '',
                                   '機構': a['機構'], '額に要る根拠値': need, '額': '未測定', '額の理由': '台帳に教育領域の採用値がない／指標がない'})
                continue
            for s in inds:
                base = {'行動ID': a['行動ID'], '法律ID': lid, '施行年': t0 or '', '指標': s, '機構': a['機構'], '額に要る根拠値': need,
                        '額': '未測定', '額の理由': '台帳に教育領域の採用値がない（根拠が先・計算は後）'}
                if not t0:
                    chain_rows.append({**base, '状態': '測定不能', '理由': '施行日が不明', '前の差': '', '後の差': '', '差の差': '',
                                       '趨勢除去後の差の差': '', '比較国数': '', '同じ観測を共有する本数': ''})
                    continue
                d = did(gap_by[s], t0)
                n = gap_by[s].get(t0, {}).get('比較国数', '')
                chain_rows.append({**base, '状態': d['状態'], '理由': d.get('理由', ''), '前の差': fmt(d.get('前の差')), '後の差': fmt(d.get('後の差')),
                                   '差の差': fmt(d.get('差の差')), '趨勢除去後の差の差': fmt(d.get('趨勢除去後の差の差')), '比較国数': n,
                                   '同じ観測を共有する本数': shared[(s, t0)]})
    cc = ['行動ID', '法律ID', '施行年', '指標', '状態', '理由', '前の差', '後の差', '差の差', '趨勢除去後の差の差', '比較国数', '同じ観測を共有する本数',
          '機構', '額に要る根拠値', '額', '額の理由']
    write(LEDGER / 'chains.csv', cc, chain_rows)
    write(LEDGER / 'law-links.csv', ['行動ID', '法律ID', '題名', '施行日', '既存の結果', '既存の額', '議員の関与', '関与した議員数（算入）'], law_rows)
    print(f'{VERSION}: 比較国{len(used)}・指標{len(series_all)}・鎖{len(chain_rows)}・法律{len(law_rows)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
