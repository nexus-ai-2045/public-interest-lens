"""産業連関表から、川上への波及の比率を計算し、過去の表で検証する（task-id io-ripple、io-ripple-v1）。

出典（公的・一次）: 総務省ほか10府省庁「産業連関表」
- 平成23-27-令和2年接続産業連関表（参考：マトリックス形式の取引基本表。基本分類、生産者価格、2011・2015年の名目と実質（2015年価格）、2020年名目）
- 令和2年（2020年）産業連関表 統合大分類（37部門）の取引基本表と逆行列係数表（公式の計算シート。検算にだけ使う）

計算（method-spec の io-ripple-v1）:
  A = Z / X（列ごと）、M = 輸入計 / 国内需要合計（部門ごと、競争輸入型）
  B = (I - (I - M̂) A)^-1、v = 粗付加価値 / 国内生産額
  波及比率 r_k = Σ_{i≠k} v_i B_ik / (v_k B_kk)
  つまり、産業 k の付加価値が D 円減ったとき、仕入れ先など他産業の付加価値の減は D × r_k 円（川上だけ。川下は数えない）。

使い方（リポジトリのルートで。numpy と openpyxl が要る）:
  python3 scripts/io_ripple.py fetch      # 無い原本だけ取る（data/acquired/io-tables/raw/）
  python3 scripts/io_ripple.py build      # 原本から表と検証を作る（通信しない）
  python3 scripts/io_ripple.py check      # 公式の逆行列係数表と突き合わせる（誤差が許容を超えたら失敗）
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from register_external_material import register_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/acquired/io-tables/raw'
ACQ = ROOT / 'data/acquired/io-tables'
OUT = ROOT / 'data/derived/io-ripple-v1'
TASK_ID = 'io-ripple'  # 外部資料の保管庫 <root>/.local/external-materials/io-ripple/（AGENTS.md）
UA = 'public-interest-lens io-ripple (research; GitHub nexus-ai-2045/public-interest-lens)'

SOURCES = {
    'link20.xlsx': ('https://www.soumu.go.jp/main_content/001019115.xlsx', '平成23-27-令和2年接続産業連関表（参考）マトリックス形式の取引基本表'),
    'rensetsu_H12-17-23_105.xlsx': ('https://www.e-stat.go.jp/stat-search/file-download?statInfId=000031413705&fileKind=0', '平成12-17-23年接続産業連関表 生産者価格評価表（統合中分類、105部門）'),
    'rensetsu_H17-23-27_105.xlsx': ('https://www.e-stat.go.jp/stat-search/file-download?statInfId=000031974825&fileKind=0', '平成17-23-27年接続産業連関表 生産者価格評価表（統合中分類、105部門）'),
    'official2020_large.xlsx': ('https://www.soumu.go.jp/main_content/000954326.xlsx', '令和2年産業連関表 計算シートその１（統合大分類）'),
}
# (表の名前, シート名, 年)。実質は2015年価格。
# 統合中分類（105部門）の接続表。基本分類より粗いが、2000・2005年がある。(名前, ファイル, シート, 年)
MID_TABLES = [('2000名目', 'rensetsu_H12-17-23_105.xlsx', '統合中分類平成12年 名目', 2000), ('2005名目', 'rensetsu_H12-17-23_105.xlsx', '統合中分類平成17年 名目', 2005),
              ('2011名目', 'rensetsu_H12-17-23_105.xlsx', '統合中分類平成23年 名目', 2011), ('2015名目', 'rensetsu_H17-23-27_105.xlsx', '統合中分類平成27年 名目', 2015)]
TABLES = [('2011名目', 'H23名目', 2011), ('2011実質', 'H23実質', 2011), ('2015名目', 'H27名目', 2015), ('2015実質', 'H27実質', 2015), ('2020名目', 'R02名目', 2020)]

SPEC_VERSION = 'io-ripple-v1'


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (url, title) in SOURCES.items():
        p = RAW / name
        if not p.exists():
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            p.write_bytes(urllib.request.urlopen(req, timeout=120).read())
        # 原本は外部資料として登録する（AGENTS.md。中身の確かさは unverified から。同じ日・URL・中身は登録し直さない）
        register_once(input_path=p, source_url=url, task_id=TASK_ID, title=f'産業連関表の原本（{name}）', purpose=title,
                      storage_root=ROOT / '.local' / 'external-materials', observed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        rows.append({'file': name, 'url': url, 'title': title, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                     'bytes': p.stat().st_size, 'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')})
    with open(ACQ / 'manifest.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _large(code: str) -> str:
    """基本分類の先頭2桁で部門をまとめる（39部門）。公式の統合大分類（37部門）とは 19 印刷・23 なめし革などの扱いが違うので、公式との突き合わせは公式の大分類の表そのもので行う。"""
    return code[:2]


def _col(names, label):
    return [i for i, n in enumerate(names) if n == label][0]


def load_sheet(sheet, key=None, path='link20.xlsx'):
    """基本分類の表を2桁の部門（統合大分類）にまとめて返す。"""
    wb = openpyxl.load_workbook(RAW / path, read_only=True, data_only=True)
    rows = [list(r) for r in wb[sheet].iter_rows(values_only=True)]
    codes, names = rows[1], rows[2]
    end_inner = _col(names, '内生部門計')
    ic = list(range(2, end_inner))
    c_dom, c_exp, c_imp, c_x = (_col(names, k) for k in ('国内需要合計', '輸出計', '（控除）輸入計', '国内生産額'))
    body = [r for r in rows[3:] if r[0] is not None]
    inner_rows = [r for r in body if str(r[0]).isdigit() and str(r[0])[0] < '7']
    va_row = [r for r in body if r[1] == '粗付加価値部門計'][0]
    key = key or _large
    sec_of_col = [key(str(codes[j])) for j in ic]
    secs = sorted(set(sec_of_col) | {key(str(r[0])) for r in inner_rows})
    idx = {s: k for k, s in enumerate(secs)}
    n = len(secs)
    Z, D, E, M, X, VA = np.zeros((n, n)), np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    sec_name = {}
    for r in inner_rows:
        i = idx[key(str(r[0]))]
        for j, c in zip(ic, sec_of_col):
            Z[i, idx[c]] += r[j] or 0
        D[i] += r[c_dom] or 0
        E[i] += r[c_exp] or 0
        M[i] += -(r[c_imp] or 0)
        X[i] += r[c_x] or 0
    for j, c in zip(ic, sec_of_col):
        VA[idx[c]] += va_row[j] or 0
    return secs, Z, D, E, M, X, VA


def leontief(Z, D, M, X):
    A = Z / np.where(X == 0, 1, X)[None, :]
    mhat = np.where(D == 0, 0, M / np.where(D == 0, 1, D))
    n = len(X)
    B = np.linalg.inv(np.eye(n) - (1 - mhat)[:, None] * A)
    return A, mhat, B


def ripple_ratio(B, VA, X):
    v = VA / np.where(X == 0, 1, X)
    n = len(X)
    r = np.zeros(n)
    for k in range(n):
        if v[k] <= 0:
            r[k] = np.nan
            continue
        others = sum(v[i] * B[i, k] for i in range(n) if i != k)
        r[k] = others / (v[k] * B[k, k])
    return r


def sector_names():
    wb = openpyxl.load_workbook(RAW / 'official2020_large.xlsx', read_only=True, data_only=True)
    rows = list(wb['X'].iter_rows(values_only=True))
    return {str(r[0]): r[1] for r in rows[3:] if r[0] is not None and str(r[0]).isdigit() and len(str(r[0])) == 2}


def official_B():
    wb = openpyxl.load_workbook(RAW / 'official2020_large.xlsx', read_only=True, data_only=True)
    rows = list(wb['B'].iter_rows(values_only=True))
    codes = [str(c) for c in rows[1][2:] if c is not None]
    body = [r for r in rows[3:] if r[0] is not None and str(r[0]).isdigit() and len(str(r[0])) == 2]
    return codes, np.array([[r[2 + j] for j in range(len(codes))] for r in body], dtype=float), [str(r[0]) for r in body]


def build_all():
    tabs = {}
    for label, sheet, year in TABLES:
        secs, Z, D, E, M, X, VA = load_sheet(sheet)
        A, mhat, B = leontief(Z, D, M, X)
        tabs[label] = dict(year=year, secs=secs, Z=Z, D=D, E=E, M=M, X=X, VA=VA, A=A, mhat=mhat, B=B, r=ripple_ratio(B, VA, X))
    return tabs


def load_official_large():
    """公式の統合大分類（37部門）の取引基本表を読む。計算の検算用。"""
    wb = openpyxl.load_workbook(RAW / 'official2020_large.xlsx', read_only=True, data_only=True)
    rows = list(wb['X'].iter_rows(values_only=True))
    names = rows[2]
    body = [r for r in rows[3:40]]
    n = len(body)
    c = {k: names.index(k) for k in ('国内需要合計', '（控除）輸入計', '国内生産額')}
    Z = np.array([[r[2 + j] for j in range(n)] for r in body], float)
    D = np.array([r[c['国内需要合計']] for r in body], float)
    M = -np.array([r[c['（控除）輸入計']] for r in body], float)
    X = np.array([r[c['国内生産額']] for r in body], float)
    va = [r for r in rows[3:] if r[0] is not None and str(r[0]) == '96'][0]
    VA = np.array([va[2 + j] for j in range(n)], float)
    return [str(r[0]) for r in body], Z, D, M, X, VA


def check():
    """同じ式を公式の大分類の表に当て、公式の逆行列係数表 B と比べる。"""
    secs, Z, D, M, X, VA = load_official_large()
    _, _, B = leontief(Z, D, M, X)
    ocodes, OB, orows = official_B()
    assert secs == orows == ocodes
    return float(np.abs(B - OB).max()), len(secs)


EXTRA_NAMES = {'19': '印刷・製版・製本', '23': 'なめし革・革製品'}


def _quantile(a, q):
    return float(np.quantile(np.asarray(a, float), q))


def build() -> None:
    tabs = build_all()
    names = {**sector_names(), **EXTRA_NAMES}
    OUT.mkdir(parents=True, exist_ok=True)
    secs = tabs['2020名目']['secs']
    # 1) 年ごとの波及比率
    with open(OUT / 'ripple.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['表', '年', '部門コード', '部門名', '国内生産額_百万円', '付加価値率', '自部門逆行列係数', '波及比率r'])
        for label, t in tabs.items():
            v = t['VA'] / t['X']
            for k, sc in enumerate(t['secs']):
                w.writerow([label, t['year'], sc, names.get(sc, sc), int(t['X'][k]), f'{v[k]:.6f}', f"{t['B'][k, k]:.6f}", f"{t['r'][k]:.6f}"])
    # 2) 係数の安定性：名目の表で 2011→2015、2015→2020 の r の対数比
    nom = ['2011名目', '2015名目', '2020名目']
    steps = [(nom[0], nom[1]), (nom[1], nom[2])]
    logs = []
    for a_, b_ in steps:
        ra, rb = tabs[a_]['r'], tabs[b_]['r']
        ok = np.isfinite(ra) & np.isfinite(rb) & (ra > 0) & (rb > 0)
        logs.append(np.log(rb[ok] / ra[ok]))
    # 区間の半幅 w：もう一方の移行の |対数比| の 95% 分位。保持した移行での被覆率で検証する
    cover = []
    for held in (0, 1):
        wdt = _quantile(np.abs(logs[1 - held]), 0.95)
        cover.append(float(np.mean(np.abs(logs[held]) <= wdt)))
    wfull = _quantile(np.abs(np.concatenate(logs)), 0.95)
    # 3) 産出の予測：t の逆行列と t+1 の最終需要から t+1 の国内生産額を当てる
    pred = {}
    for a_, b_ in [('2011実質', '2015実質'), ('2015名目', '2020名目')]:
        ta, tb = tabs[a_], tabs[b_]
        Fd = tb['D'] - tb['Z'].sum(axis=1)
        direct = (1 - ta['mhat']) * Fd + tb['E']
        xio = ta['B'] @ direct
        big = tb['X'] > np.quantile(tb['X'], 0.25)
        def med_err(x):
            return float(np.median(np.abs(np.log(x[big] / tb['X'][big]))))
        pred[f'{a_}→{b_}'] = {
            '部門数': int(big.sum()),
            '産業連関の予測_中央値誤差_対数': med_err(xio),
            '直接効果だけの予測_中央値誤差_対数': med_err(direct),
            '前期の生産額をそのまま使う_中央値誤差_対数': med_err(ta['X']),
            '産業連関の予測_誤差10%以内の部門の割合': float(np.mean(np.abs(np.log(xio[big] / tb['X'][big])) <= 0.0953)),
            '直接効果だけ_誤差10%以内の部門の割合': float(np.mean(np.abs(np.log(direct[big] / tb['X'][big])) <= 0.0953)),
        }
    res = {
        'version': SPEC_VERSION,
        'tables': [l for l, _, _ in TABLES],
        'stability_step_log_ratio_p95': [_quantile(np.abs(l), 0.95) for l in logs],
        'stability_half_width_log': wfull,
        'holdout_coverage': {'2011→2015で作った区間を2015→2020に当てる': cover[1], '2015→2020で作った区間を2011→2015に当てる': cover[0]},
        'output_prediction': pred,
        'official_check_max_abs_diff': check()[0],
    }
    (OUT / 'backtest.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    # 3) 2020年表での最終版（区間つき）
    t = tabs['2020名目']
    with open(OUT / 'ripple_latest.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['部門コード', '部門名', '波及比率r', '区間下限', '区間上限', '付加価値率', '国内生産額_百万円'])
        v = t['VA'] / t['X']
        for k, sc in enumerate(t['secs']):
            r = t['r'][k]
            w.writerow([sc, names.get(sc, sc), f'{r:.4f}', f'{r * np.exp(-0.40):.4f}', f'{r * np.exp(0.40):.4f}', f'{v[k]:.4f}', int(t['X'][k])])
    print(json.dumps(res, ensure_ascii=False, indent=2))


# 産業の対応（OECD STAN／ISIC Rev.4 の大分類 → 基本分類コードの先頭）。判断による対応で、設計書の2系統照合の対象。
ISIC_TO_IO = {
    'A': ['01'], 'B': ['06'],
    'C': ['11', '15', '16', '19', '20', '21', '22', '23', '25', '26', '27', '28', '29', '30', '31', '32', '33', '34', '35', '39'],
    'D': ['46'], 'E': ['47', '48'], 'F': ['41'], 'G': ['51'], 'H': ['57'], 'I': ['6711', '6721'],
    'J': ['59'], 'K': ['53'], 'L': ['55'], 'M': ['632', '6699'], 'N': ['66'],
    'O': ['61'], 'P': ['631'], 'Q': ['64'], 'R': ['6741'], 'S': ['65', '6731', '6751', '6799'],
}
TABLE_YEARS = {'2011': '2011名目', '2015': '2015名目', '2020': '2020名目'}


def set_ripple(Bm, v, X, VA, members):
    """部門の集合 S の付加価値が合計 D 減ったとき、S の外の付加価値が何倍減るか。S 内の比率は VA で按分、S の外だけを数える。"""
    S = np.array(sorted(members))
    out = np.array([i for i in range(len(X)) if i not in set(S)])
    w = VA[S] / VA[S].sum()
    # S 内の付加価値の減少がちょうど D=1（部門ごとに w_k）になるよう、S への最終需要の減 f を B[S,S] f = w/v で解く。S 内の部門間の波及も分母に含まれる。
    f = np.linalg.solve(Bm[np.ix_(S, S)], w / v[S])
    return float(sum(v[i] * (Bm[i, S] @ f) for i in out))


def half_width(gap: int, kind: str = 'basic'):
    """区間の半幅（対数）。基本分類の表：5年以内 0.40、10年以内 0.50。統合中分類の表（2000・2005年）：5年以内 0.80、それより遠いものは保留。"""
    if kind == 'mid':
        return 0.80 if gap <= 5 else None
    if gap <= 5:
        return 0.40
    if gap <= 10:
        return 0.50
    return None


def build_mid():
    out = {}
    for label, path, sheet, year in MID_TABLES:
        secs, Z, D, E, M, X, VA = load_sheet(sheet, key=lambda c: c[:3], path=path)
        A, mhat, Bm = leontief(Z, D, M, X)
        v = np.where(X > 0, VA / np.where(X == 0, 1, X), 0)
        out[year] = dict(secs=secs, Bm=Bm, v=v, X=X, VA=VA, mhat=mhat, Z=Z, D=D, E=E, M=M, r=ripple_ratio(Bm, VA, X))
    return out


def isic_ripple_at(level_secs, Bm, v, X, VA, ind, mid):
    pre = [p[:3] if mid else p for p in ISIC_TO_IO[ind]]
    members = [i for i, c in enumerate(level_secs) if any(c.startswith(p) for p in pre) and v[i] > 0 and X[i] > 0]
    return set_ripple(Bm, v, X, VA, members)


def mid_stability():
    """105部門で 2000→2005→2011→2015 の波及比率の動きと、基本分類との集計差（2011・2015）。"""
    mt = build_mid()
    yrs = [2000, 2005, 2011, 2015]
    steps = []
    for a_, b_ in zip(yrs, yrs[1:]):
        ra, rb = mt[a_]['r'], mt[b_]['r']
        ok = np.isfinite(ra) & np.isfinite(rb) & (ra > 0) & (rb > 0) & (mt[a_]['X'] > 1e5)
        steps.append(np.log(rb[ok] / ra[ok]))
    # 産業(ISIC)単位での動き
    isic_steps = []
    for a_, b_ in zip(yrs, yrs[1:]):
        d = []
        for ind in ISIC_TO_IO:
            if ind in ('D', 'E'):
                continue
            ra = isic_ripple_at(mt[a_]['secs'], mt[a_]['Bm'], mt[a_]['v'], mt[a_]['X'], mt[a_]['VA'], ind, True)
            rb = isic_ripple_at(mt[b_]['secs'], mt[b_]['Bm'], mt[b_]['v'], mt[b_]['X'], mt[b_]['VA'], ind, True)
            if ra > 0 and rb > 0:
                d.append(np.log(rb / ra))
        isic_steps.append(np.array(d))
    return mt, yrs, steps, isic_steps


def aggregation_offset(mt, basic):
    """統合中分類で計算した波及比率は、基本分類より高めに出る。2011・2015年の両方を持つ産業ごとに、その差（対数）の平均を求めて 2000・2005年の値から引く。"""
    off = {}
    for ind in ISIC_TO_IO:
        d = []
        for y in (2011, 2015):
            rb = isic_ripple_at(*basic[y], ind, False)
            rm = isic_ripple_at(mt[y]['secs'], mt[y]['Bm'], mt[y]['v'], mt[y]['X'], mt[y]['VA'], ind, True)
            if rb > 0 and rm > 0:
                d.append(np.log(rm / rb))
        if d:
            off[ind] = float(np.mean(d))
    return off


def apply_laws() -> None:
    """macro-v1 の額に波及を別欄で付ける。波及は川上だけ、額には足さず別欄に出す。額は符号つき（正は損失、負は便益）なので、「上限」ではなく
    波及を含む額の端点を絶対値の小さい側と大きい側で出す（負の額に比率を掛けると絶対値が大きい側は下限になるため）。"""
    basic = {}
    for label, sheet, year in TABLES:
        if label.endswith('名目'):
            secs, Z, D, E, M, X, VA = load_sheet(sheet, key=lambda c: c[:6])
            A, mhat, Bm = leontief(Z, D, M, X)
            basic[year] = (secs, Bm, np.where(X > 0, VA / np.where(X == 0, 1, X), 0), X, VA)
    mt = build_mid()
    off = aggregation_offset(mt, basic)
    cand = {2000: 'mid', 2005: 'mid', 2011: 'basic', 2015: 'basic', 2020: 'basic'}
    rows = list(csv.DictReader(open(ROOT / 'data/derived/macro-v1/macro.csv', encoding='utf-8')))
    cache = {}
    out = []
    for r in rows:
        if r['結果'] != '額':
            continue
        y = int(r['施行日'][:4])
        near = min(cand, key=lambda t: (abs(t - y), cand[t] != 'basic'))
        kind = cand[near]
        gap = abs(near - y)
        ind = r['産業']
        hw = half_width(gap, kind)
        rr = None
        reason = ''
        if ind == '_T':
            reason = '全産業の額に波及を足すと二重に数える（全産業は川上も含む）'
        elif ind not in ISIC_TO_IO:
            reason = '産業の対応が未定義'
        elif hw is None:
            reason = f'施行年と最も近い表（{near}年）の差が{gap}年で、係数の安定性を確かめた範囲を超える。古い表を足すまで保留'
        else:
            kk = (near, ind)
            if kk not in cache:
                if kind == 'basic':
                    cache[kk] = isic_ripple_at(*basic[near], ind, False)
                else:
                    t = mt[near]
                    cache[kk] = isic_ripple_at(t['secs'], t['Bm'], t['v'], t['X'], t['VA'], ind, True) * float(np.exp(-off.get(ind, 0.0)))
            rr = cache[kk]
        med = float(r['中央値'])
        out.append({
            'id': r['id'], '題名': r['題名'], '産業': ind, '施行年': y, '使った表': near if rr is not None else '',
            '表の粒度': ('基本分類' if kind == 'basic' else '統合中分類（集計差を補正）') if rr is not None else '',
            '額_中央値_円': int(med),
            '波及比率r': f'{rr:.4f}' if rr is not None else '',
            '波及比率_下限': f'{rr * np.exp(-hw):.4f}' if rr is not None else '',
            '波及比率_上限': f'{rr * np.exp(hw):.4f}' if rr is not None else '',
            '波及の額_中央値_円': int(med * rr) if rr is not None else '',
            '波及を含む額_絶対値が小さい側_円': int(med * (1 + rr * np.exp(-hw))) if rr is not None else '',
            '波及を含む額_絶対値が大きい側_円': int(med * (1 + rr * np.exp(hw))) if rr is not None else '',
            '理由': reason,
        })
    with open(OUT / 'laws_ripple.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    with open(OUT / 'isic_ripple.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['表の年', '産業(ISIC)', '波及比率r', '粒度'])
        for (near, ind), rr in sorted(cache.items()):
            w.writerow([near, ind, f'{rr:.4f}', cand[near]])
    n_ok = sum(1 for o in out if o['波及比率r'])
    print(f'額のある{len(out)}本のうち波及を付けた{n_ok}本')
    # 統合中分類の検証をまとめて backtest.json に足す
    mt2, yrs, steps, isteps = mid_stability()
    bt = json.loads((OUT / 'backtest.json').read_text(encoding='utf-8'))
    bt['mid_level'] = {
        '表': ['2000名目', '2005名目', '2011名目', '2015名目'],
        '部門ごとの波及比率_5-6年の|対数比|_95分位': [float(np.quantile(np.abs(x), 0.95)) for x in steps],
        '産業(ISIC)ごとの波及比率_5-6年の|対数比|_最大': [float(np.abs(x).max()) for x in isteps],
        '基本分類との集計差_産業別_平均対数': off,
        '集計差の補正後に残る差_最大': max(abs(np.log(isic_ripple_at(mt[y]['secs'], mt[y]['Bm'], mt[y]['v'], mt[y]['X'], mt[y]['VA'], ind, True) / isic_ripple_at(*basic[y], ind, False)) - off[ind]) for y in (2011, 2015) for ind in off if isic_ripple_at(*basic[y], ind, False) > 0),
    }
    bt['half_width_rule'] = {'基本分類_5年以内': 0.40, '基本分類_10年以内': 0.50, '統合中分類_5年以内': 0.80}
    (OUT / 'backtest.json').write_text(json.dumps(bt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(bt['mid_level'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'build', 'check', 'laws'])
    a = ap.parse_args()
    if a.cmd == 'fetch':
        fetch()
    elif a.cmd == 'check':
        mx, n = check()
        print(f'公式の逆行列係数表との最大絶対誤差 {mx:.2e}（{n}部門）')
        sys.exit(0 if mx < 1e-3 else 1)
    elif a.cmd == 'laws':
        apply_laws()
    else:
        build()
