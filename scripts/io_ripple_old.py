"""産業連関表の古い表（平成7・12・17年、基本分類）を読み、波及比率の検証に足す（task-id io-ripple、R40）。

出典（公的・一次）: 総務省ほか10府省庁「平成7-12-17年接続産業連関表」投入表（基本分類別、名目値と2000年価格の実質値）
  e-Stat 統計表 statInfId=000007517092（.xls、列＝産業、行＝品目の縦持ち形式）
  ※ 産出表（000007517194）は同じ数字の別の並べ方なので使わない。

io_ripple.py の load_sheet と同じ形（secs, Z, D, E, M, X, VA）に直して返す。
  Z : 行＝品目、列＝産業。行は先頭6桁で産業にまとめる（行は7桁で細かい）
  D : 国内需要合計、E : 輸出計、M : 輸入計（正の値にする）、X : 国内生産額、VA : 粗付加価値部門計

使い方（リポジトリのルートで。numpy と xlrd が要る）:
  python3 scripts/io_ripple_old.py fetch   # 無い原本だけ取る（data/acquired/io-tables/raw/）
  python3 scripts/io_ripple_old.py check   # 表の整合（行の合計＝需要合計−輸入、列の合計＝国内生産額）を確かめる
  python3 scripts/io_ripple_old.py backtest  # 1995→2000→2005 の検証を data/derived/io-ripple-v1/backtest_old.json に書く
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import itertools

import io_ripple as base

RAW = base.RAW
FILE = 'h7-12-17_input_basic.xls'  # 取得先（URL）と台帳は io_ripple.SOURCES・manifest.csv にある
# 年 → 金額の列（内生部門・外生部門のシートとも同じ並び）。名目は平成7・12・17年が 5・11・17 列目
NOMINAL_COL = {1995: 5, 2000: 11, 2005: 17}
REAL_COL = {1995: 8, 2000: 14}  # 実質（平成17年価格）は平成7・12年の2列だけ。平成17年は名目のみ
END_ROW_LABELS = {'dom': '921000', 'exp': '922000', 'imp': '942000', 'x': '970000'}
VA_ROW = '9500000'
DIGITS = 4  # 行と列の共通の桁数
ENDOGENOUS_LIMIT = '90'  # 列コードの先頭2桁がこれ未満なら内生部門（909900 内生部門計・900000 分類不明より前）


def fetch() -> Path:
    """無い原本だけ取り、台帳（manifest.csv）と外部資料の登録まで io_ripple.fetch に任せる。"""
    base.fetch()
    return RAW / FILE


def _open(path: Path | None = None):
    import xlrd
    return xlrd.open_workbook(str(path or (RAW / FILE)))


def load_old(year: int, col: int | None = None, path: Path | None = None, digits: int = DIGITS):
    """古い表を (secs, Z, D, E, M, X, VA) で返す。col で金額の列を選ぶ（既定は名目）。
    行（品目、7桁）と列（産業、6桁）は細かさが違い、6桁で行と列が1対1にならない産業がある（例：行は「野菜」1本、列は露地・施設の2本）。
    行・列に共通の先頭4桁（基本分類の部門）でそろえる。"""
    col = NOMINAL_COL[year] if col is None else col
    wb = _open(path)
    s0, s1 = wb.sheet_by_index(0), wb.sheet_by_index(1)
    inner: dict[tuple[str, str], float] = {}
    va: dict[str, float] = {}
    cols: set[str] = set()
    for r in range(4, s0.nrows):
        c, row = str(s0.cell_value(r, 0)), str(s0.cell_value(r, 2))
        v = s0.cell_value(r, col)
        v = float(v) if v != '' else 0.0
        if c[:2] >= ENDOGENOUS_LIMIT:
            continue
        cols.add(c[:digits])
        if row == VA_ROW:
            va[c[:digits]] = va.get(c[:digits], 0.0) + v
        elif row[:2] < ENDOGENOUS_LIMIT:
            inner[(row[:digits], c[:digits])] = inner.get((row[:digits], c[:digits]), 0.0) + v
    ends = {k: {} for k in END_ROW_LABELS}
    rows = set()
    for r in range(4, s1.nrows):
        c, row = str(s1.cell_value(r, 0)), str(s1.cell_value(r, 2))
        if row[:2] >= ENDOGENOUS_LIMIT:
            continue
        for k, code in END_ROW_LABELS.items():
            if c == code:
                v = s1.cell_value(r, col)
                ends[k][row[:digits]] = ends[k].get(row[:digits], 0.0) + (float(v) if v != '' else 0.0)
                rows.add(row[:digits])
    secs = sorted(cols | rows)
    idx = {s: k for k, s in enumerate(secs)}
    n = len(secs)
    Z, D, E, M, X, VA = np.zeros((n, n)), np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    for (i, j), v in inner.items():
        Z[idx[i], idx[j]] += v
    for s, v in ends['dom'].items():
        D[idx[s]] = v
    for s, v in ends['exp'].items():
        E[idx[s]] = v
    for s, v in ends['imp'].items():
        M[idx[s]] = -v  # 控除項目なので負で入っている
    for s, v in ends['x'].items():
        X[idx[s]] = v
    for s, v in va.items():
        VA[idx[s]] = v
    return secs, Z, D, E, M, X, VA


def other_inputs(year: int, secs: list[str], digits: int = DIGITS) -> np.ndarray:
    """産業の列にある、「分類不明」の行（9000000）の投入。収支の確認にだけ使う（波及の計算では中間投入に数えない。0.1% 未満）。家計外消費支出の行（9110xxx）は内生部門計に入らない内訳なので数えない。"""
    s0 = _open().sheet_by_index(0)
    idx = {s: k for k, s in enumerate(secs)}
    out = np.zeros(len(secs))
    for r in range(4, s0.nrows):
        c, row = str(s0.cell_value(r, 0)), str(s0.cell_value(r, 2))
        if c[:2] < ENDOGENOUS_LIMIT and row == '9000000':
            v = s0.cell_value(r, NOMINAL_COL[year])
            out[idx[c[:digits]]] += float(v) if v != '' else 0.0
    return out


def consistency(secs, Z, D, E, M, X, VA, other=None) -> dict:
    """表の収支。行：国内需要合計（中間需要を含む）＋輸出−輸入＝国内生産額（D＋E−M＝X）、列：中間投入＋粗付加価値＝国内生産額。"""
    row = D + E - M - X
    col = Z.sum(axis=0) + VA + (other if other is not None else 0) - X
    big = X > 0
    return {
        '部門数': len(secs),
        '行の収支_最大絶対誤差_百万円': float(np.abs(row).max()),
        '列の収支_最大絶対誤差_百万円': float(np.abs(col[big]).max()) if big.any() else 0.0,
        '国内生産額_合計_百万円': float(X.sum()),
        '粗付加価値_合計_百万円': float(VA.sum()),
    }


# 産業の対応（OECD STAN／ISIC Rev.4 の大分類 → 古い表（平成17年基準の符号）の先頭）。2011年以降の表の対応（io_ripple.ISIC_TO_IO）と同じ中身を、部門名を読んで引き直したもの。
# 古い表は符号体系が違う（例：41 建設は同じだが、51 は古い表では電力・ガス、2011年以降の表では商業）ので、符号をそのまま流用しない。
# 2011年以降の表の対応と同じ割り切り：A は 01（農業）だけで林業・漁業は含めない、M と N は「その他の対事業所サービス」で重なる。
OLD_ISIC_TO_IO = {
    'A': ['01'], 'B': ['06'], 'C': [f'{i:02d}' for i in range(11, 40)],
    'D': ['51'], 'E': ['52'], 'F': ['41'], 'G': ['61'], 'H': ['71', '7311'],
    'I': ['8612', '8613'], 'J': ['7312', '7319', '732', '733', '734', '735'], 'K': ['62'], 'L': ['64'],
    'M': ['822', '8519'], 'N': ['85'], 'O': ['81'], 'P': ['821'], 'Q': ['83'], 'R': ['8611'], 'S': ['8411', '8614', '8619'],
}
# 4桁の部門にまとめた表は、6桁の表より波及比率がわずかに高く出る（内部の取引が部門の中に入るため）。2011・2015・2020年の基本分類の表を4桁にまとめて、その差（対数）を産業ごとに測る。
# 3年のばらつきが大きい産業（D 電力・ガス・熱供給：-0.69〜0.25）は補正が定まらないので古い表を使わない。
OFFSET_SPREAD_LIMIT = 0.15
OLD_YEARS = (1995, 2000, 2005)


def old_tables() -> dict:
    out = {}
    for y in OLD_YEARS:
        secs, Z, D, E, M, X, VA = load_old(y)
        _A, mhat, B = base.leontief(Z, D, M, X)
        v = np.where(X > 0, VA / np.where(X == 0, 1, X), 0)
        out[y] = {'secs': secs, 'Z': Z, 'D': D, 'E': E, 'M': M, 'X': X, 'VA': VA, 'mhat': mhat, 'B': B, 'v': v, 'r': base.ripple_ratio(B, VA, X)}
    return out


def basic_tables(digits: int) -> dict:
    """2011・2015・2020年の基本分類（名目）を先頭 digits 桁にまとめた表。"""
    out = {}
    for label, sheet, year in base.TABLES:
        if label.endswith('名目'):
            secs, Z, D, _E, M, X, VA = base.load_sheet(sheet, key=lambda c: c[:digits])
            _A, _mhat, B = base.leontief(Z, D, M, X)
            out[year] = (secs, B, np.where(X > 0, VA / np.where(X == 0, 1, X), 0), X, VA)
    return out


def aggregation_offset_4digit() -> tuple[dict, dict]:
    """産業(ISIC)ごとの「4桁にまとめた表 − 6桁の表」の波及比率の差（対数）の3年平均と、3年のばらつき（最大−最小）。"""
    b6, b4 = basic_tables(6), basic_tables(4)
    mean, spread = {}, {}
    for ind in base.ISIC_TO_IO:
        d = []
        for y in b6:
            r6 = base.isic_ripple_at(*b6[y], ind, False)
            r4 = base.isic_ripple_at(*b4[y], ind, False)
            if r6 > 0 and r4 > 0:
                d.append(float(np.log(r4 / r6)))
        if d:
            mean[ind], spread[ind] = float(np.mean(d)), float(max(d) - min(d))
    return mean, spread


def old_isic_ripple(t: dict, ind: str) -> float:
    return base.isic_ripple_at(t['secs'], t['B'], t['v'], t['X'], t['VA'], ind, False, mapping=OLD_ISIC_TO_IO)


def old_table_laws_r(offsets: dict, spread: dict) -> dict:
    """(表の年, 産業) → 6桁の表に換算した波及比率。補正が定まらない産業は入れない。"""
    ts = old_tables()
    out = {}
    for y, t in ts.items():
        for ind in OLD_ISIC_TO_IO:
            if ind not in offsets or spread[ind] > OFFSET_SPREAD_LIMIT:
                continue
            r = old_isic_ripple(t, ind)
            if r > 0:
                out[(y, ind)] = r * float(np.exp(-offsets[ind]))
    return out


def backtest() -> None:
    ts = old_tables()
    off, spread = aggregation_offset_4digit()
    usable = [i for i in OLD_ISIC_TO_IO if i in off and spread[i] <= OFFSET_SPREAD_LIMIT]
    res: dict = {'version': 'io-ripple-v1', 'tables': [f'{y}名目' for y in OLD_YEARS], '部門数': len(ts[2005]['secs']),
                 '表の整合': {str(y): consistency(*(ts[y][k] for k in ('secs', 'Z', 'D', 'E', 'M', 'X', 'VA')), other=other_inputs(y, ts[y]['secs'])) for y in OLD_YEARS},
                 '4桁にまとめた差_産業別_平均対数': off, '4桁にまとめた差_3年のばらつき': spread, '補正に使う産業': usable}
    # 1) 同じ符号体系の中での動き：部門ごと、産業(ISIC)ごとの波及比率の5年間の |対数比|
    step_sec, step_ind = {}, {}
    for a, b in itertools.pairwise(OLD_YEARS):
        ra, rb = ts[a]['r'], ts[b]['r']
        ok = np.isfinite(ra) & np.isfinite(rb) & (ra > 0) & (rb > 0) & (ts[a]['X'] > 1e5) & (ts[b]['X'] > 1e5)
        step_sec[f'{a}→{b}'] = np.abs(np.log(rb[ok] / ra[ok]))
        step_ind[f'{a}→{b}'] = {i: abs(float(np.log(old_isic_ripple(ts[b], i) / old_isic_ripple(ts[a], i)))) for i in usable if old_isic_ripple(ts[a], i) > 0 and old_isic_ripple(ts[b], i) > 0}
    res['5年の動き_部門ごと_95分位'] = {k: base._quantile(v, 0.95) for k, v in step_sec.items()}
    res['5年の動き_産業ごと_最大'] = {k: max(v.values()) for k, v in step_ind.items()}
    res['5年の動き_産業ごと'] = {k: {i: round(x, 3) for i, x in v.items()} for k, v in step_ind.items()}
    # 2) 区間の被覆：片方の移行の 95分位を半幅にして、もう片方の移行に当てる（部門ごと）
    keys = list(step_sec)
    res['被覆率_部門ごと'] = {f'{keys[1 - h]}で作った区間を{keys[h]}に当てる': float(np.mean(step_sec[keys[h]] <= base._quantile(step_sec[keys[1 - h]], 0.95))) for h in (0, 1)}
    res['被覆率_現行の半幅0.40_産業ごと'] = {k: float(np.mean([x <= 0.40 for x in v.values()])) for k, v in step_ind.items()}
    # 3) 表の改訂をまたぐ動き：平成17年基準の符号の2005年（4桁→6桁に換算）と、2011年以降の基本分類の2011年
    b6 = basic_tables(6)
    cross = {}
    for ind in usable:
        r05 = old_isic_ripple(ts[2005], ind) * float(np.exp(-off[ind]))
        r11 = base.isic_ripple_at(*b6[2011], ind, False)
        if r05 > 0 and r11 > 0:
            cross[ind] = abs(float(np.log(r11 / r05)))
    res['改訂をまたぐ_2005→2011_産業ごと'] = {i: round(x, 3) for i, x in cross.items()}
    res['改訂をまたぐ_2005→2011_最大'] = max(cross.values())
    res['改訂をまたぐ_2005→2011_0.50以内の割合'] = float(np.mean([x <= 0.50 for x in cross.values()]))
    # 4) 産出の予測：t の逆行列と t+1 の最終需要から t+1 の国内生産額を当てる（1995→2000 は平成17年価格の実質、2000→2005 は名目）
    pred = {}
    for (a, b), (ca, cb) in {(1995, 2000): (REAL_COL[1995], REAL_COL[2000]), (2000, 2005): (NOMINAL_COL[2000], NOMINAL_COL[2005])}.items():
        pa, pb = load_old(a, ca), load_old(b, cb)
        _A, mh_a, Ba = base.leontief(pa[1], pa[2], pa[4], pa[5])
        Fd = pb[2] - pb[1].sum(axis=1)
        direct = (1 - mh_a) * Fd + pb[3]
        xio = Ba @ direct
        big = pb[5] > np.quantile(pb[5][pb[5] > 0], 0.25)
        def med_err(x, big=big, xb=pb[5]):
            return float(np.median(np.abs(np.log(np.maximum(x[big], 1) / xb[big]))))
        pred[f'{a}→{b}'] = {'部門数': int(big.sum()), '産業連関の予測_中央値誤差_対数': med_err(xio), '直接効果だけの予測_中央値誤差_対数': med_err(direct),
                           '前期の生産額をそのまま使う_中央値誤差_対数': med_err(pa[5]), '産業連関の予測_誤差10%以内の部門の割合': float(np.mean(np.abs(np.log(np.maximum(xio[big], 1) / pb[5][big])) <= 0.0953))}
    res['output_prediction'] = pred
    # 5) 産業の対応の照合（2系統目）：統合中分類（2011年以降の符号）の同じ年の付加価値の合計と、産業ごとに比べる
    mt = base.build_mid()
    cmp_: dict = {}
    for y in (2000, 2005):
        t, m = ts[y], mt[y]
        drift = float(np.log(t['VA'].sum() / m['VA'].sum()))
        row = {}
        for ind in OLD_ISIC_TO_IO:
            vo = t['VA'][[i for i, s in enumerate(t['secs']) if any(s.startswith(p) for p in OLD_ISIC_TO_IO[ind])]].sum()
            pre = [p[:3] for p in base.ISIC_TO_IO[ind]]
            vm = m['VA'][[i for i, c in enumerate(m['secs']) if any(c.startswith(p) for p in pre)]].sum()
            row[ind] = round(float(np.log(vo / vm)) - drift, 3)
        cmp_[str(y)] = {'全体の差': round(drift, 3), '産業ごとの差（全体の差を引いた後）': row}
    res['対応の照合_付加価値の合計_統合中分類との差'] = cmp_
    (base.OUT / 'backtest_old.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in res.items() if k not in ('5年の動き_産業ごと', '改訂をまたぐ_2005→2011_産業ごと', '表の整合')}, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'check', 'backtest'])
    a = ap.parse_args()
    if a.cmd == 'fetch':
        print(fetch())
        return 0
    if a.cmd == 'check':
        bad = 0
        for y in NOMINAL_COL:
            t = load_old(y)
            c = consistency(*t, other=other_inputs(y, t[0]))
            print(y, json.dumps(c, ensure_ascii=False))
            bad += c['行の収支_最大絶対誤差_百万円'] > 5 or c['列の収支_最大絶対誤差_百万円'] > 5
        return 1 if bad else 0
    backtest()
    return 0


if __name__ == '__main__':
    sys.exit(main())
