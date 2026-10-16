"""2系統で別々に取った CSV を突き合わせ、一致した行だけを残す（設計決定0007 §4 の2系統一致）。

使い方:
  python scripts/compare_double_fetch.py --a <系統Aのフォルダ> --b <系統Bのフォルダ> \
      --key 掲載回次,種別,提出回次,番号 --value 議案件名,審議状況 --out <出力フォルダ>

- 各フォルダの *.csv をすべて読み、キーの列で行を対応づける。
- 値の列が両方で同じ行だけを agreed.csv に書く。片方にしか無い行、値が食い違う行は disputed.csv に理由つきで書く。
- 一致しない行は推測で直さない。保留のまま残し、原本（Mac で取得する分）で確かめる。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from pathlib import Path


def normalize(text: str) -> str:
    """全角・半角と前後の空白の違いだけを吸収する。文字の中身は変えない。"""
    return unicodedata.normalize('NFKC', text or '').strip()


def load(folder: Path, key: list[str], value: list[str]) -> tuple[dict[tuple, dict], list[str]]:
    rows: dict[tuple, dict] = {}
    duplicates: list[str] = []
    for path in sorted(folder.glob('*.csv')):
        with path.open(encoding='utf-8', newline='') as fh:
            for row in csv.DictReader(fh):
                missing = [c for c in key + value if c not in row]
                if missing:
                    raise SystemExit(f'{path}: 列 {missing} がありません')
                k = tuple(normalize(row[c]) for c in key)
                if k in rows and any(normalize(rows[k][c]) != normalize(row[c]) for c in value):
                    duplicates.append('|'.join(k))
                rows[k] = row
    return rows, duplicates


def compare(a: Path, b: Path, key: list[str], value: list[str], out: Path) -> dict:
    ra, da = load(a, key, value)
    rb, db = load(b, key, value)
    out.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key + value + ['出典URL']))
    agreed, disputed = [], []
    for k in sorted(set(ra) | set(rb)):
        x, y = ra.get(k), rb.get(k)
        if x is None or y is None:
            disputed.append({**dict(zip(key, k)), '理由': '系統Aのみ' if y is None else '系統Bのみ'})
            continue
        diff = [c for c in value if normalize(x[c]) != normalize(y[c])]
        if diff:
            disputed.append({**dict(zip(key, k)), '理由': '値が食い違う: ' + ', '.join(f'{c}（A={x[c]} / B={y[c]}）' for c in diff)})
        else:
            agreed.append({c: x.get(c, '') for c in fields})
    with (out / 'agreed.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(agreed)
    with (out / 'disputed.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=key + ['理由'])
        w.writeheader()
        w.writerows(disputed)
    summary = {'系統Aの行数': len(ra), '系統Bの行数': len(rb), '一致': len(agreed), '保留': len(disputed),
               '同じ系統内で食い違う重複': len(da) + len(db)}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--a', type=Path, required=True)
    p.add_argument('--b', type=Path, required=True)
    p.add_argument('--key', required=True)
    p.add_argument('--value', required=True)
    p.add_argument('--out', type=Path, required=True)
    ns = p.parse_args(argv)
    summary = compare(ns.a, ns.b, ns.key.split(','), ns.value.split(','), ns.out)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
