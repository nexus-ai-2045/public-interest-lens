"""財務省・総務省・内閣府の財政と国策の資料を取得して整える（task-id fiscal）。

対象（公式の出典のみ）:
- 為替介入: 財務省 外国為替平衡操作の実施状況（1991年4月以降、実施日ごとの額と売買通貨）
- 一般会計の予算: 財務省 財政統計 第19表（昭和24年度以降の主要経費別 当初予算・補正予算）
- 一般会計の決算（歳出）: 財務省 財政統計 第20表（昭和42年度以降の主要経費別 予算現額・決算額）
- 一般会計の決算（歳入）: 財務省 財政統計 第4表（昭和57年度以降の主要科目別。公債金＝その年度に国債で賄った額）
- 地方財政: 総務省 地方財政白書 第11表（歳入決算額の状況 その1 総括。地方税・地方交付税・国庫支出金・地方債など）
- 国策: 内閣府 経済財政運営と改革の基本方針（骨太の方針）。閣議決定の日を PDF の1頁目から読む

原本は --raw の下に保存し、URL・sha256・取得時刻を manifest.csv に残す（原本は Git に入れない）。
原本は .local/external-materials/fiscal/ にも外部資料として登録する（record.json、中身の確かさの初期状態は unverified）。
原本が手元に無い資料（新しい作業環境・取得の失敗）は、前に書いた表の同じ出典の行を残す。
整えた表は --out の下に書く。欠けた値は書かない（0や推定で埋めない）。表の「-」（該当なし）も書かない。

使い方（リポジトリのルートで。xlsx を読むため openpyxl、PDF を読むため pypdf が要る）:
  python3 scripts/fetch_fiscal.py fetch               # 無い原本だけ取る
  python3 scripts/fetch_fiscal.py build               # 原本から表を作る（通信しない）
  python3 scripts/fetch_fiscal.py update --monthly    # 毎朝の自動更新用。前回から28日たっていれば原本を取り直し、表を作る
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_more_stats as common  # noqa: E402  取得・manifest・和暦の読み方を共有する
from register_external_material import register_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = 'fiscal'  # 外部資料の保管庫 <root>/.local/external-materials/fiscal/（AGENTS.md）

common.UA = 'public-interest-lens fiscal (research; GitHub nexus-ai-2045/public-interest-lens)'

MOF_STAT = 'https://www.mof.go.jp/policy/budget/reference/statistics/'
FEIO_CSV = 'https://www.mof.go.jp/policy/international_policy/reference/feio/foreign_exchange_intervention_operations.csv'
BUDGET_FILES = [('mof/19a.xlsx', MOF_STAT + '19a.xlsx'), ('mof/19b.xlsx', MOF_STAT + '19b.xlsx')]
SETTLE_FILE = ('mof/20.xlsx', MOF_STAT + '20.xlsx')
REVENUE_FILE = ('mof/04.xlsx', MOF_STAT + '04.xlsx')
SOUMU = 'https://www.soumu.go.jp/menu_seisaku/hakusyo/chihou/'
# 地方財政白書の CSV（白書の年 → 置き場所）。表の番号は版で変わる（令和6年版までは第10表）。
# 令和2年版より前はこの置き方では取れない（無い URL にも 200 で HTML の案内が返る）。
HAKUSYO = [('r03', '2021data', 's-010-1.csv'), ('r04', '2022data', 's-010-1.csv'), ('r05', '2023data', 's-010-1.csv'), ('r06', '2024data', 's-010-1.csv'),
           ('r07', '2025data', 's-011-1.csv'), ('r08', '2026data', 's-011-1.csv')]
HONEBUTO = 'https://www5.cao.go.jp/keizai-shimon/kaigi/cabinet/honebuto/{y}/{y}_basicpolicies_ja.pdf'
HONEBUTO_YEARS = range(2015, date.today().year + 1)  # 2014年以前はこの URL の形では 404（置き場所が違う）。まだ無い年は取れないだけ
MONTHLY_DAYS = 28
LAST_FETCH = Path('.local/fiscal/last-fetch.txt')

SKIPPED: Counter[str] = Counter()  # 読まなかった値の数（build の最後に表示する）

FX_HEADER = ['実施日', '金額', '単位', '売買通貨', '出典URL']
FLOW_HEADER = ['年度', '会計', '段階', '区分', '項目', '金額', '単位', '出典URL', '備考']
POLICY_HEADER = ['id', '題名', '閣議決定日', '出典URL']


def do_fetch(raw: Path, manifest: Path, refresh: bool = False) -> None:
    """refresh のときは手元の原本を取り直す（為替介入や新しい年度の表が足されるため）。取れなかったものは前の原本を残す。"""
    targets = [('mof/feio.csv', FEIO_CSV), *BUDGET_FILES, SETTLE_FILE, REVENUE_FILE]
    targets += [(f'soumu/{h}_{name}', f'{SOUMU}{h}data/{d}/csv/{name}') for h, d, name in HAKUSYO]
    targets += [(f'cao/honebuto_{y}.pdf', HONEBUTO.format(y=y)) for y in HONEBUTO_YEARS]
    for rel, url in targets:
        dest = raw / rel
        old = dest.read_bytes() if refresh and dest.exists() else None
        if old is not None:
            dest.unlink()
        if common.fetch(url, dest, manifest, f'.local/fiscal/raw/{rel}') is None and old is not None:
            dest.write_bytes(old)
        if dest.exists():
            register(dest, url, fetched_at(manifest, rel))


def fetched_at(manifest: Path, rel: str) -> str | None:
    """manifest に残る、この原本のいちばん新しい取得時刻。"""
    if not manifest.exists():
        return None
    with manifest.open(encoding='utf-8') as fh:
        times = [r['fetched_at'] for r in csv.DictReader(fh) if r['file'] == f'.local/fiscal/raw/{rel}']
    return times[-1] if times else None


def register(dest: Path, url: str, observed_at: str | None) -> str:
    """原本を外部資料として .local/external-materials/fiscal/ に登録する（AGENTS.md。中身の確かさは unverified から）。
    同じ日・同じ URL・同じ中身は登録し直さない。"""
    return register_once(input_path=dest, source_url=url, task_id=TASK_ID, title=f'財政・国策の原本（{dest.name}）',
                         purpose='データベースの決定・財政の流れの表に入れる', storage_root=ROOT / '.local' / 'external-materials',
                         observed_at=observed_at)


def urls_from_manifest(manifest: Path) -> dict[str, str]:
    if not manifest.exists():
        return {}
    with manifest.open(encoding='utf-8') as fh:
        return {r['file'].replace('.local/fiscal/raw/', ''): r['url'] for r in csv.DictReader(fh)}


def clean(s) -> str:
    return common.clean(s)


def amount(x):
    """数値セル（"59,185" や 123.0）を float に。「-」「－」や空は None。"""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    t = clean(x).replace(',', '').replace('△', '-')
    try:
        return float(t)
    except ValueError:
        return None


def fiscal_year_of(label: str) -> int | None:
    """「令和８年度」「Ｈ元」「昭和42」「R6」→ 西暦の年度。"""
    t = clean(label)
    short = {'S': '昭和', 'H': '平成', 'R': '令和'}
    m = re.match(r'([SHR])(元|\d+)$', t)
    if m:
        t = short[m.group(1)] + m.group(2) + '年'
    t = re.sub(r'(昭和|平成|令和)(元|\d+)$', r'\1\2年', t)
    y, _ = common.era_year_label(t, None)
    return y


# ---------------------------------------------------------------- 為替介入

def parse_feio(body: bytes, url: str) -> list[list]:
    """実施日ごとの行。年・月は上の行から持ち越す（英語の Year・Month 列を使う）。四半期の合計の行は読まない。"""
    months = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
    out, year, month = [], None, None
    for r in csv.reader(io.StringIO(body.decode('cp932'))):
        if len(r) < 8 or '期計' in r[0]:
            continue
        if r[3].strip().isdigit():
            year = int(r[3])
        if r[4].strip() in months:
            month = months[r[4].strip()]
        if not r[5].strip().isdigit() or year is None or month is None:
            continue
        v = amount(r[6])
        if v is None:
            continue
        out.append([f'{year}-{month:02d}-{int(r[5]):02d}', common.fmt(v), '億円', clean(r[7]), url])
    return out


# ---------------------------------------------------------------- 主要経費別（第19表・第20表）

def row_name(r) -> str:
    """項目名。番号つき（「1.」の次の列）と番号なし（2列目、古い表では3列目）がある。"""
    cells = [clean(c) for c in r[:3]] + [''] * 3
    if re.fullmatch(r'\d+\.', cells[1]):
        return cells[2]
    return cells[1] or cells[2]


def is_indented(r) -> bool:
    """第19表の内訳の行（「1.」の番号つき、または3列目に名前）。"""
    cells = [clean(c) for c in r[:3]] + [''] * 3
    return bool(re.fullmatch(r'\d+\.', cells[1])) or (cells[1] == '' and cells[2] != '')


TOTALS = ('計', '合計', '小計', '主要経費計', '重要経費計', '総合計')


def expense_rows(rows, value_cols: dict[str, int], bracket_parents: bool):
    """主要経費別の表を (項目, 親の経費, {列名: 値}, 合計の後か) にする。

    親の経費（社会保障関係費など）は、値のない見出し行（第20表は（）つき）から始まり「計」で閉じる。
    閉じたときに親の「計」を親の経費の値として出す。「小計」は読まない（親の「計」と二重になる）。
    第19表は内訳が字下げ（番号つき）なので、字下げのない行が来たら親を閉じる。「計」のない親（内訳が1つ）は内訳を親と同じ段に戻す。
    名前のない行の扱いは表で2通りある。
    - 古い年：名前の行に括弧書きの別の額（他の経費の一部を含めた額。第20表は負の数として読める）、次の名前のない行に重ならない本来の額。
      次の行の額を使う（次の行が空の欄は名前の行と同じ額）。
    - 令和元・2年度の第19表：名前のない行が名前の行の前にあり、臨時・特別の措置を除いた額とみられる。読まない（名前の行が公表の額）。
    「合計」の後の行（前々年度の決算不足補てん繰戻など）は「総合計」にだけ入り、「合計」には入らないので、合計の後かの印を付ける。
    """
    numeric = lambda r: any(c < len(r) and amount(r[c]) is not None for c in value_cols.values())  # noqa: E731
    first_nameless = next((i for i, r in enumerate(rows) if not row_name(r) and numeric(r)), None)
    nameless_before = first_nameless is not None and first_nameless + 1 < len(rows) and row_name(rows[first_nameless + 1]) != '' \
        and (first_nameless == 0 or not numeric(rows[first_nameless - 1]))
    out, parent, children, after_total = [], None, [], False

    def close(with_total):
        nonlocal parent, children
        if parent and with_total is not None:
            out.append((parent, None, with_total, after_total))
        elif parent:  # 「計」のない親：内訳を親と同じ段に戻す
            for k in children:
                out[k] = (out[k][0], None, out[k][2], out[k][3])
        parent, children = None, []

    for i, r in enumerate(rows):
        name = row_name(r)
        if not name or name.startswith('（注）'):
            continue
        if re.fullmatch(r'\(\d+\)', name):  # 昭和20・30年代の公共事業費の(1)(2)…：上の行の内訳の内訳（名前は4列目）。上の行の額に含まれる
            SKIPPED['公共事業費の内訳の内訳（(1)など）'] += 1
            continue
        vals = {k: amount(r[c]) if c < len(r) else None for k, c in value_cols.items()}
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if not nameless_before and nxt is not None and not row_name(nxt) and numeric(nxt):
            alt = {k: amount(nxt[c]) if c < len(nxt) else None for k, c in value_cols.items()}
            # 次の行が負（括弧書き）で名前の行が正なら、次の行は下の「計」の括弧書き（昭和42年度の失業対策費の次の行）。使わない。
            if not (any(v is not None and v < 0 for v in alt.values()) and not any(v is not None and v < 0 for v in vals.values())):
                vals = {k: alt[k] if alt[k] is not None else vals[k] for k in vals}
        if re.fullmatch(r'\(小計.*\)', name):  # 昭和30年代の第19表：「(小計1～6)」が括弧の親を閉じる
            name = '計'
        bracket = re.fullmatch(r'\((.+)\)', name)  # clean() で全角の括弧は半角になる
        blank = all(c >= len(r) or r[c] is None or clean(r[c]) == '' for c in value_cols.values())  # 「－」は該当なしの値で、見出しではない
        if bracket or (blank and name not in TOTALS):
            close(None)
            parent = bracket.group(1) if bracket else name
            continue
        if name == '小計' or all(v is None for v in vals.values()):
            continue
        if name == '計':
            close(vals)
            continue
        if parent and (name in TOTALS or (not bracket_parents and not is_indented(r))):
            close(None)
        if parent:
            children.append(len(out))
        out.append((name, parent, vals, after_total and name not in TOTALS))
        if name == '合計':
            after_total = True
    close(None)
    return out


def sheet_title_year(rows) -> int | None:
    """表の上の方の「令　和　８　年　度」を読む（シート名より確か）。"""
    for r in rows[:6]:
        for c in r:
            if c is None:
                continue
            t = clean(c)
            m = re.fullmatch(r'(昭和|平成|令和)(元|\d+)年度', t)
            if m:
                return fiscal_year_of(m.group(0).replace('年度', ''))
    return None


def header_cols(rows, labels: dict[str, str]) -> tuple[int, dict[str, int]] | None:
    """見出しの行（当初予算・補正予算 など）を探し、列の位置を返す。"""
    for i, r in enumerate(rows[:16]):
        cells = [clean(c) for c in r]
        found = {k: cells.index(lab) for k, lab in labels.items() if lab in cells}
        if len(found) == len(labels):
            return i, found
    return None


def parse_budget(path: Path, url: str) -> list[list]:
    out = []
    for title, rows in common.read_sheets(path):
        year = sheet_title_year(rows) or fiscal_year_of(title)
        hit = header_cols(rows, {'当初': '当初予算', '補正': '補正予算'})
        if not year or not hit:
            continue
        start, cols = hit
        cols['計'] = cols['補正'] + 1
        for name, parent, vals, outside in expense_rows(rows[start + 1:], cols, bracket_parents=False):
            first, supp, total = vals['当初'], vals['補正'], vals['計']
            # 昭和24年度の表に、補正が「△93,486」なのに行の計が当初と同じ行がある。表の合計は補正を含めて合うので、補正の額はそのまま使う。
            odd = supp is not None and first is not None and total is not None and abs(first + supp - total) > 1
            for stage in ('当初', '補正'):
                if vals[stage] is None:
                    continue
                out.append(flow_row(year, stage, name, parent, outside, vals[stage] * 1000, url, ('補正は年度内のすべての補正予算の合計（純額）' + ('。この行の計の欄は当初と同じ額（表のまま）' if odd else '')) if stage == '補正' else ''))
    return out


def parse_settlement(path: Path, url: str) -> list[list]:
    out = []
    for title, rows in common.read_sheets(path):
        year = sheet_title_year(rows) or fiscal_year_of(title)
        hit = header_cols(rows, {'決算': '決算額'})
        if not year or not hit:
            continue
        start, cols = hit
        for name, parent, vals, outside in expense_rows(rows[start + 1:], cols, bracket_parents=True):
            if vals['決算'] is not None:
                out.append(flow_row(year, '決算', name, parent, outside, vals['決算'] * 1000, url, ''))
    return out


def flow_row(year, stage, name, parent, outside, yen, url, note):
    item = f'{parent}／{name}' if parent else name
    # 足し上げて「合計」になるのは「主要経費別」だけ。「合計の外」は「合計」に入らず「総合計」に入る
    kind = '主要経費別（内訳）' if parent else '主要経費別（合計）' if name in TOTALS else '主要経費別（合計の外）' if outside else '主要経費別'
    return [year, '一般会計', stage, kind, item, common.fmt(yen), '円', url, note]


REVENUE_ITEMS = {'租税及印紙収入': '租税及印紙収入', '公債金': '公債金', '合計': '歳入合計'}


def parse_revenue(path: Path, url: str) -> list[list]:
    """第4表。年度は左の3列（元号・数・「年度」）で、元号は上の行から持ち越す。"""
    (_, rows), = common.read_sheets(path)[:1]
    head = [clean(c) for c in rows[3]]
    sub = [clean(c) for c in rows[4]]
    cols = {}
    for c, h in enumerate(head):
        if h in ('公債金', '合計'):
            cols[REVENUE_ITEMS[h]] = c
        if h == '租税及印紙収入':
            cols['租税及印紙収入'] = next(d for d in range(c, len(sub)) if sub[d] == '計')
    out, era = [], None
    for r in rows[5:]:
        if r[0] is not None and clean(r[0]) in common.ERA:
            era = clean(r[0])
        n = clean(r[1]) if r[1] is not None else ''
        if not era or not re.fullmatch(r'元|\d+', n):
            continue
        year = common.ERA[era] + (1 if n == '元' else int(n))
        for item, c in cols.items():
            v = amount(r[c])
            if v is not None:
                note = 'その年度に国債（建設公債・特例公債など）の発行で賄った歳入' if item == '公債金' else ''
                out.append([year, '一般会計', '決算', '歳入（主要科目別）', item, common.fmt(v * 1_000_000), '円', url, note])
    return out


# ---------------------------------------------------------------- 地方財政

LOCAL_ITEMS = ['地方税', '地方譲与税', '地方特例交付金等', '地方交付税', '国庫支出金', '地方債', '歳入合計']


def parse_local(body: bytes, url: str) -> list[list]:
    """第11表 その1。純計額（都道府県と市町村の重なりを除いた額、百万円）を、今年度と前年度の2年分読む。"""
    rows = list(csv.reader(io.StringIO(body.decode('cp932', errors='replace'))))
    if not rows or '歳入決算額の状況' not in clean(rows[0][0]) or '総括' not in clean(rows[1][0] if len(rows) > 1 else ''):
        SKIPPED['地方財政白書の表が「歳入決算額の状況 その1 総括」でない'] += 1
        return []
    head = next((r for r in rows if r and clean(r[0]) == '区分'), None)
    if head is None:
        return []
    this_year = fiscal_year_of(re.sub('年度', '', clean(head[1])))
    prev_col = next(i for i, c in enumerate(head) if '純計額' in clean(c))
    prev_year = fiscal_year_of(re.sub('年度.*', '', clean(head[prev_col])))
    out = []
    for r in rows:
        if not r or clean(r[0]) not in LOCAL_ITEMS:
            continue
        for year, col in ((this_year, 5), (prev_year, prev_col)):
            v = amount(r[col])
            if year and v is not None:
                out.append([year, '地方（純計）', '決算', '地方財政（歳入）', clean(r[0]), common.fmt(v * 1_000_000), '円', url, '都道府県と市町村の純計額'])
    return out


# ---------------------------------------------------------------- 骨太の方針

def pdf_first_page(path: Path) -> str:
    import logging
    from pypdf import PdfReader
    logging.getLogger('pypdf').setLevel(logging.CRITICAL)  # 古い文字コード表（90msp-RKSJ-H）の未対応の知らせ。日付の数字は読める
    return PdfReader(str(path)).pages[0].extract_text() or ''


def cabinet_date(text: str) -> str | None:
    t = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))
    m = re.search(r'(平成|令和)(元|\d+)年(\d+)月(\d+)日', t)
    if not m:
        return None
    y = common.ERA[m.group(1)] + (1 if m.group(2) == '元' else int(m.group(2)))
    return f'{y}-{int(m.group(3)):02d}-{int(m.group(4)):02d}'


# ---------------------------------------------------------------- まとめ

def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(header)
        w.writerows(rows)
    print(path.name, len(rows), '行')


def previous_rows(path: Path) -> dict[str, list[list]]:
    """前に書いた表の行を出典URL ごとに。原本が手元に無い資料は、この行を残す（新しい作業環境では原本が Git の外で無い）。"""
    if not path.exists():
        return {}
    with path.open(encoding='utf-8', newline='') as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return {}
    col = rows[0].index('出典URL')
    kept: dict[str, list[list]] = {}
    for r in rows[1:]:
        kept.setdefault(r[col], []).append([int(c) if k == 0 and c.isdigit() else c for k, c in enumerate(r)])
    return kept


def do_build(raw: Path, out: Path, manifest: Path) -> None:
    urls = urls_from_manifest(manifest)
    missing: list[str] = []

    def rows_from(rel: str, url: str, parse, prev: dict[str, list[list]], usable=lambda p: True) -> list[list]:
        """原本があれば読み、無ければ（使えなければ）前の表の同じ出典の行を残す。"""
        p = raw / rel
        if p.exists() and usable(p):
            return parse(p, urls.get(rel, url))
        missing.append(rel)
        return prev.get(urls.get(rel, url), [])

    prev = previous_rows(out / 'fx_interventions.csv')
    write_csv(out / 'fx_interventions.csv', FX_HEADER,
              rows_from('mof/feio.csv', FEIO_CSV, lambda p, u: parse_feio(p.read_bytes(), u), prev))
    prev = previous_rows(out / 'fiscal_flows.csv')
    flows = []
    for rel, url in BUDGET_FILES:
        flows += rows_from(rel, url, parse_budget, prev)
    flows += rows_from(*SETTLE_FILE, parse_settlement, prev)
    flows += rows_from(*REVENUE_FILE, parse_revenue, prev)
    local: dict[tuple, list] = {}
    for h, d, name in HAKUSYO:  # 古い白書から読み、同じ年度・項目は新しい白書の値で上書きする（決算の確定値の見直しを取り込む）
        for row in rows_from(f'soumu/{h}_{name}', f'{SOUMU}{h}data/{d}/csv/{name}', lambda p, u: parse_local(p.read_bytes(), u), prev):
            local[(row[0], row[4])] = row
    flows += [local[k] for k in sorted(local)]
    flows.sort(key=lambda r: (r[1], r[0], r[2], r[3]))
    write_csv(out / 'fiscal_flows.csv', FLOW_HEADER, flows)
    prev = previous_rows(out / 'policies.csv')
    policies = []
    for y in HONEBUTO_YEARS:
        policies += rows_from(f'cao/honebuto_{y}.pdf', HONEBUTO.format(y=y),
                              lambda p, u, y=y: [[f'honebuto-{y}', f'経済財政運営と改革の基本方針{y}（骨太の方針）', cabinet_date(pdf_first_page(p)) or '', u]],
                              prev, usable=lambda p: p.read_bytes().startswith(b'%PDF'))
    write_csv(out / 'policies.csv', POLICY_HEADER, policies)
    if missing:
        print('原本が無く、前の表の行を残した:', '、'.join(missing))
    for reason, n in sorted(SKIPPED.items()):
        print('読まなかった値:', reason, n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['fetch', 'build', 'update'])
    ap.add_argument('--monthly', action='store_true', help='update で、前回の取得から28日たっていなければ取得を飛ばして表だけ作る')
    ap.add_argument('--raw', default='.local/fiscal/raw')
    ap.add_argument('--out', default='data/acquired/fiscal')
    ap.add_argument('--manifest', default='data/acquired/fiscal/manifest.csv')
    a = ap.parse_args(argv)
    raw, out, mf = Path(a.raw), Path(a.out), Path(a.manifest)
    if a.cmd == 'fetch':
        do_fetch(raw, mf)
    elif a.cmd == 'build':
        do_build(raw, out, mf)
    else:
        last = date.fromisoformat(LAST_FETCH.read_text(encoding='utf-8').strip()) if LAST_FETCH.exists() else None
        if a.monthly and last and (date.today() - last).days < MONTHLY_DAYS:
            print(f'前回の取得（{last}）から{MONTHLY_DAYS}日たっていないので、取得は飛ばして表だけ作る')
        else:
            do_fetch(raw, mf, refresh=True)
            LAST_FETCH.parent.mkdir(parents=True, exist_ok=True)
            LAST_FETCH.write_text(date.today().isoformat() + '\n', encoding='utf-8')
        do_build(raw, out, mf)


if __name__ == '__main__':
    main()
