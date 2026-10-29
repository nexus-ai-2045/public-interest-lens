"""議員の支持基盤の表（組織票の表、設計決定0017）。

団体の公表された推薦・支持・支援（data/acquired/support-base/endorsements.csv）と、政治資金の関係団体からの寄附・パーティー対価
（data/derived/political-funds/relations.csv、Git に入れない大きな生成物）を、議員ごと・団体ごとに並べる。団体名は org_names.org_key でそろえ、
審議会での立場・背後の力の帳簿（団体名キー）と同じ鍵で結べるようにする。有権者個人の属性は扱わない。個人の寄附者は入れない。
点数には使わない（配分の重みへの採用は設計決定0017の「採用の条件」を満たすまで行わない）。

使い方: python3 scripts/build_support_base.py [--check]
"""
from __future__ import annotations

import csv
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from org_names import org_key  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENDORSEMENTS = ROOT / 'data/acquired/support-base/endorsements.csv'
RELATIONS = ROOT / 'data/derived/political-funds/relations.csv'
OUT = ROOT / 'data/derived/support-base-v1/member-base.csv'
HEADER = ['人物ID', '団体', '団体名キー', '根拠', '年', '金額', '出典URL', '確度']
BASIS = ('推薦', '支持', '組織内候補', '支援')
VERIFIED = '原本照合済み'


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def build(endorsements: list[dict[str, str]], relations: list[dict[str, str]]) -> list[dict]:
    rows: list[dict] = []
    for r in endorsements:
        key = org_key(r['団体'])
        if not (r['人物ID'] and key and r['関係'] in BASIS and r['出典URL'].startswith('https://') and r['確度'].startswith(VERIFIED)):
            continue
        rows.append({'人物ID': r['人物ID'], '団体': r['団体'], '団体名キー': key, '根拠': r['関係'], '年': r['年'], '金額': '', '出典URL': r['出典URL'], '確度': r['確度']})
    for r in relations:
        if r.get('区分') not in ('受けた寄附', 'パーティー対価') or r.get('相手方種別') == '個人' or not r.get('人物ID') or not r.get('団体名キー'):
            continue
        rows.append({'人物ID': r['人物ID'], '団体': r['相手方'], '団体名キー': r['団体名キー'], '根拠': '寄附' if r['区分'] == '受けた寄附' else 'パーティー対価',
                     '年': r['年分'], '金額': r['金額'], '出典URL': r.get('PDF_URL', ''), '確度': '2系統一致（政治資金収支報告書）'})
    rows.sort(key=lambda r: (r['人物ID'], r['団体名キー'], r['根拠'], r['年']))
    return rows


def render(rows: list[dict]) -> str:
    buf = StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER, lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str]) -> int:
    text = render(build(read(ENDORSEMENTS), read(RELATIONS)))
    if '--check' in argv:
        if not OUT.exists() or OUT.read_text(encoding='utf-8') != text:
            print('作り直すと変わる表: data/derived/support-base-v1/member-base.csv（python3 scripts/build_support_base.py）')
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding='utf-8')
    print(f'支持基盤の行: {text.count(chr(10)) - 1}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
