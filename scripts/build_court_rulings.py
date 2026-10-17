"""規制をめぐる判決・行政訴訟を、2系統で別々に集めた JSON から突き合わせて表にする（task-id court-rulings）。

設計決定0007 §4 の2系統一致に従う。系統A・Bが同じ事件について別々に裁判所の判例ページを読み、
判決日・事件番号・規制への判断が一致したものだけを「一致」として rulings.csv に載せる。
食い違い・片系統だけ・どちらかが未確認のものは disputed.csv に理由つきで残し、推測で直さない。

入力: --in のフォルダにある <分野>.A.json と <分野>.B.json（同じ id で対応づける）。
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
DISPUTED_COLUMNS = ['id', '通称', '理由', '系統A', '系統B']


def normalize(text: str) -> str:
    """全角・半角、空白、括弧の違いだけを吸収する。文字の中身は変えない。"""
    text = unicodedata.normalize('NFKC', text or '')
    return re.sub(r'\s+', '', text)


def ruling_kind(text: str) -> str:
    """規制への判断を、規制が退けられたか維持されたかの大分類にそろえる。"""
    t = normalize(text)
    if not t or t == UNCONFIRMED:
        return ''
    if re.search(r'合憲|適法|規制維持|侵害認定|有罪', t) and not re.search(r'違憲|違法|無効|取消|差止認容|無罪', t):
        return '規制維持'
    if re.search(r'違憲|違法|無効|取消|差止認容|無罪', t):
        return '規制否定'
    return t


def match_value(column: str, value: str) -> str:
    if column == '規制への判断':
        return ruling_kind(value)
    v = normalize(value)
    return '' if v == UNCONFIRMED else v


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


def compare(a: dict[str, dict], b: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    agreed: list[dict] = []
    disputed: list[dict] = []
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        if ra is None or rb is None:
            only = ra or rb
            disputed.append({'id': key, '通称': only.get('通称', ''), '理由': '片系統のみ',
                             '系統A': 'あり' if ra else 'なし', '系統B': 'あり' if rb else 'なし'})
            continue
        reasons = []
        for col in MATCH_COLUMNS:
            va, vb = match_value(col, ra.get(col, '')), match_value(col, rb.get(col, ''))
            if not va or not vb:
                reasons.append(f'{col}が未確認')
            elif va != vb:
                reasons.append(f'{col}が不一致')
        if reasons:
            disputed.append({'id': key, '通称': ra.get('通称', ''), '理由': '・'.join(reasons),
                             '系統A': ' / '.join(str(ra.get(c, '')) for c in MATCH_COLUMNS),
                             '系統B': ' / '.join(str(rb.get(c, '')) for c in MATCH_COLUMNS)})
            continue
        row = flatten(ra)
        if not normalize(row['判例URL']).startswith('https://www.courts.go.jp'):
            row['判例URL'] = rb.get('判例URL', '') or row['判例URL']
        row['確認状況'] = '2系統一致（判決日・事件番号・規制への判断）'
        agreed.append(row)
    return agreed, disputed


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
    args = ap.parse_args()
    agreed, disputed = compare(load(args.src, 'A'), load(args.src, 'B'))
    agreed.sort(key=lambda r: r['判決日'])
    write(args.out / 'rulings.csv', COLUMNS, agreed)
    write(args.out / 'disputed.csv', DISPUTED_COLUMNS, disputed)
    print(f'一致 {len(agreed)} 件、保留 {len(disputed)} 件')


if __name__ == '__main__':
    main()
