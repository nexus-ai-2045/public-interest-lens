"""自動の関与（involvements-auto.csv）の法律に、審議での質疑の行を足すための表を作る（質疑の立場、allocation-v1）。

自動の関与は人の判断の要らない行動（提出・参議院本会議の賛成）だけで作っているので、質疑が入っていなかった。
会議録を読み直して決めた立場（非公開の stance-final.csv、2系統の一致か、割れた組は上位の読み手が C・D のどちらかと一致したとき）を、
関与の一覧と同じ決まり（scripts/apply_resolved_stance.py の apply）で質疑の行にして、
data/derived/allocation-v1/questions-auto.csv に書く。build_auto_involvements.py がこの表を読んで自動の関与に足す。
入力の実名入りの作業データは非公開の共有フォルダにあるので、毎朝の作り直しには入れず、読み直しの結果が変わったときに手で回す。
出力に入るのは国会議員（公人）の、会議録にある発言の記録だけ。

使い方（リポジトリのルートで）:
  python3 scripts/build_auto_questions.py --resolved /mnt/project-files/private-m2/causal-chain/stance-final.csv \
    --aliases /mnt/project-files/private-m2/allocation/aliases.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import apply_resolved_stance as ars  # noqa: E402
from allocation_involvements import HEADER  # noqa: E402

AUTO = ROOT / 'data/derived/allocation-v1/involvements-auto.csv'
OUT = ROOT / 'data/derived/allocation-v1/questions-auto.csv'


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--resolved', required=True, type=Path)
    p.add_argument('--aliases', required=True, type=Path)
    p.add_argument('--votes-dir', type=Path, default=ROOT / 'data/acquired/sangiin-votes')
    p.add_argument('--cabinet', type=Path, default=ROOT / 'data/acquired/office-holders/cabinet.csv')
    p.add_argument('--enacted', type=Path, default=ROOT / 'data/acquired/bill-census-full/enacted.csv')
    p.add_argument('--persons', type=Path, default=ROOT / 'data/derived/person-ids/persons.csv')
    a = p.parse_args(argv)
    inv = [r for r in ars.read_csv(AUTO) if r['行動'] != 'question']
    aliases = ars.load_aliases(a.aliases)
    norm = lambda x: aliases.get(ars.normalize_name(x), ars.normalize_name(x))
    cab = ars.read_csv(a.cabinet)
    speeches = a.resolved.parent / 'speeches'
    legis = ars.legislators(inv, ars.read_csv(a.votes_dir / 'members.csv'), cab, speeches, norm)
    names = Counter(ars.canonical(r['氏名']) for r in ars.read_csv(a.persons))
    out, c = ars.apply(inv, ars.read_csv(a.resolved), a.votes_dir, aliases, legis, ars.Cabinet(cab, norm),
                       ars.bill_checker(speeches, ars.read_csv(a.enacted)), split={n for n, k in names.items() if k > 1})
    rows = sorted((r for r in out if r['行動'] == 'question'), key=lambda r: (r['法律ID'], r['氏名']))
    bad = [r for r in rows if r['算入'] == 'はい' and not r['証拠URL'].startswith('https://kokkai.ndl.go.jp/')]
    if bad:
        raise SystemExit(f'算入する質疑に会議録の URL が無い行があります: {len(bad)}')
    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HEADER, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(dict(sorted(c.items())), f'質疑 {len(rows)} 行（算入 {sum(r["算入"] == "はい" for r in rows)}）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
