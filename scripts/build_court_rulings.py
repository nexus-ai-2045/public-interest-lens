"""規制をめぐる判決・行政訴訟を、2系統で別々に集めた JSON から突き合わせて表にする（task-id court-rulings）。

設計決定0007 §4 の2系統一致に従う。系統A・Bが同じ事件について別々に裁判所の判例ページを読み、
判決日・事件番号・規制への判断がそろったものだけを「一致」として rulings.csv に載せる。
食い違い・片系統だけ・どちらかが未確認のものは disputed.csv に理由つきで残し、推測で直さない。

入力: --in のフォルダにある <分野>.A.json・<分野>.B.json・<分野>.C.json（同じ id で対応づける）。
      系統Cは、A・Bが別の判決を選んだり未確認を残したりした事件を、判例ページで改めて読んだもの。
      どれか2系統の照合列がそろえば一致とする。
      各要素の列は COLUMNS と同じ名前（関連URL はリスト）。
出力: --out に rulings.csv（一致）、disputed.csv（保留）。

使い方（リポジトリのルートで）:
  python3 scripts/build_court_rulings.py --in <JSON のフォルダ> --out data/acquired/court-rulings
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

COLUMNS = [
    'id', '通称', '規制', '所管', '分野', '争点', '裁判所', '判決日', '事件番号', '裁判種別', '結果',
    '規制への判断', '判断の要旨', 'その後の変化', '判例URL', '関連URL', '確認状況', '備考',
]
# 2系統で一致を求める列。値の言い回しが違うだけの列（要旨・備考など）は系統Aを採る。
MATCH_COLUMNS = ['判決日', '事件番号', '規制への判断']
UNCONFIRMED = '未確認'
DISPUTED_COLUMNS = ['id', '通称', '理由', '各系統']


def normalize(text: str) -> str:
    """全角・半角、空白、括弧の違いだけを吸収する。文字の中身は変えない。"""
    text = unicodedata.normalize('NFKC', text or '')
    return re.sub(r'\s+', '', text)


def ruling_kind(text: str) -> str:
    """規制への判断を、規制が退けられたか維持されたかの大分類にそろえる。"""
    t = normalize(text)
    if not t or t.startswith(UNCONFIRMED):
        return ''
    if t.startswith('その他'):
        return 'その他'
    if re.search(r'合憲|適法|規制維持|侵害認定|有罪', t) and not re.search(r'違憲|違法|無効|取消|差止認容|無罪', t):
        return '規制維持'
    if re.search(r'違憲|違法|無効|取消|差止認容|無罪', t):
        return '規制否定'
    return t


def match_value(column: str, value: str) -> str:
    if column == '規制への判断':
        return ruling_kind(value)
    v = normalize(value)
    if v.startswith(UNCONFIRMED):
        return ''
    if column == '事件番号':
        # 「令和2年(行ヒ)第68号」と「令和2(行ヒ)68」を同じに扱う。
        v = re.sub(r'^(明治|大正|昭和|平成|令和)(\d+|元)年', r'\1\2', v)
        v = v.replace('第', '').replace('号', '').replace('元(', '1(')
    return v


def load(folder: Path, line: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(folder.glob(f'*.{line}.json')):
        for item in json.loads(path.read_text(encoding='utf-8')):
            rows[item['id']] = item
    return rows


def flatten(item: dict) -> dict:
    row = {c: item.get(c, '') for c in COLUMNS}
    if isinstance(row['関連URL'], list):
        row['関連URL'] = ' '.join(row['関連URL'])
    return {k: (v if isinstance(v, str) else str(v)) for k, v in row.items()}


def page_id(url: str) -> str:
    """判例ページ・判決PDFのURLから、裁判所の判例番号だけを取り出す。"""
    m = re.search(r'/hanrei/(\d+)/|[?&]id=(\d+)|hanrei-pdf-(\d+)|/0*(\d+)_hanrei\.pdf', url or '')
    return next((g.lstrip('0') for g in m.groups() if g), '') if m else ''


def signature(item: dict) -> tuple[tuple[str, ...], list[str]]:
    values, missing = [], []
    for col in MATCH_COLUMNS:
        v = match_value(col, str(item.get(col, '')))
        values.append(v)
        if not v:
            missing.append(col)
    return tuple(values), missing


def compare(*lines: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """2系統以上が同じ事件を別々に読み、照合列がそろった2系統があれば一致とする。"""
    names = 'ABCDEFG'
    agreed: list[dict] = []
    disputed: list[dict] = []
    for key in sorted(set().union(*lines)):
        present = [(names[i], rows[key]) for i, rows in enumerate(lines) if key in rows]
        found = None
        for i, (na, ra) in enumerate(present):
            sa, ma = signature(ra)
            if ma:
                continue
            for nb, rb in present[i + 1:]:
                sb, mb = signature(rb)
                if not mb and sa == sb:
                    found = (na, ra, nb, rb)
                    break
            if found:
                break
        if found:
            na, ra, nb, rb = found
            row = flatten(ra)
            if not normalize(row['判例URL']).startswith('https://www.courts.go.jp'):
                row['判例URL'] = rb.get('判例URL', '') or row['判例URL']
            row['確認状況'] = f'2系統一致（系統{na}・{nb}。判決日・事件番号・規制への判断）'
            ids = {n: page_id(str(r.get('判例URL', ''))) for n, r in present}
            if len({v for v in ids.values() if v}) > 1:
                note = '判例ページの番号が系統で食い違う（' + '、'.join(f'{n}: {v}' for n, v in ids.items() if v) + '）。URLは要再確認'
                row['備考'] = f"{row['備考']} {note}".strip()
            agreed.append(row)
            continue
        first = present[0][1]
        if len(present) == 1:
            reason = '片系統のみ'
        else:
            reasons = []
            sigs = [signature(r) for _, r in present]
            for j, col in enumerate(MATCH_COLUMNS):
                vals = [sg[j] for sg, _ in sigs]
                if any(not v for v in vals):
                    reasons.append(f'{col}が未確認')
                elif len(set(vals)) > 1:
                    reasons.append(f'{col}が不一致')
            reason = '・'.join(reasons) or '不一致'
        disputed.append({'id': key, '通称': first.get('通称', ''), '理由': reason,
                         '各系統': ' | '.join(f'{n}: ' + ' / '.join(str(r.get(c, '')) for c in MATCH_COLUMNS)
                                             for n, r in present)})
    return agreed, disputed


def flag_shared_pages(agreed: list[dict], lines: list[dict[str, dict]]) -> None:
    """同じ判例番号のページを、どこかの系統が別の判決（判決日・事件番号）として読んでいたら備考に書く。"""
    seen: dict[str, set[tuple[str, str]]] = {}
    for rows in lines:
        for item in rows.values():
            pid = page_id(str(item.get('判例URL', '')))
            date = match_value('判決日', str(item.get('判決日', '')))
            number = match_value('事件番号', str(item.get('事件番号', '')))
            if pid and date and number:
                seen.setdefault(pid, set()).add((date, number))
    for row in agreed:
        number = match_value('事件番号', row['事件番号'])
        others = {(d, n) for d, n in seen.get(page_id(row['判例URL']), set())
                  if not n.startswith(number)}
        if others:
            note = '同じ判例ページを別の判決として読んだ系統がある（' + '、'.join(f'{d} {n}' for d, n in sorted(others)) + '）。URLは要再確認'
            row['備考'] = f"{row['備考']} {note}".strip()


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--in', dest='src', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--lines', default='ABC', help='読む系統の名前（既定 ABC）')
    args = ap.parse_args()
    lines = [load(args.src, line) for line in args.lines]
    agreed, disputed = compare(*lines)
    flag_shared_pages(agreed, lines)
    agreed.sort(key=lambda r: r['判決日'])
    write(args.out / 'rulings.csv', COLUMNS, agreed)
    write(args.out / 'disputed.csv', DISPUTED_COLUMNS, disputed)
    print(f'一致 {len(agreed)} 件、保留 {len(disputed)} 件')


if __name__ == '__main__':
    main()
