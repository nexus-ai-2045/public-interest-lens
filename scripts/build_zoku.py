#!/usr/bin/env python3
"""族議員と利権団体の機械判定（設計決定0017）。

材料はすべて一次資料から作った追跡済みの表。人の判断は入れず、ADR の閾値だけで「関係がある」の印を付ける。
- 委員長：data/acquired/office-holders/committee-chairs.csv（委員会 → 分野の対応は COMMITTEE_FIELD に固定）。
- 法案への行動：data/derived/allocation-v1/involvements(.csv|-auto.csv)（提出・決定・修正・委員長・支持の質疑。賛成票は判定に使わず賛否の欄にだけ出す）。
- 分野：閣法の所管省庁（data/derived/ministry-v1/cabinet-bills.csv の所管_今）。衆法・参法は所管が決まらないので分野に入れない。
- 議員連盟：data/acquired/diet-leagues/memberships.csv（公表名簿・政治資金収支報告書・会議録から作る。空でも動く）。
- 運動団体の立場：data/acquired/pressure-groups/positions.csv（公表された声明・要望だけ。空でも動く）。
- 政治資金の関係団体：--relations（data/derived/political-funds/relations.csv。Git に無いときは付けずに動き、その旨を summary に残す）。

印は「分野との継続的な関わり」「議員連盟の名簿に載っている」「同じ分野の団体と金銭の関係が記録されている」の事実だけ。不正とは書かない。
属性（出自・国籍・信仰・家族）には点も印も付けない。

使い方（リポジトリのルートで）: python3 scripts/build_zoku.py [--relations PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.allocation_involvements import normalize_name  # noqa: E402
from scripts.org_names import org_key  # noqa: E402

OUT = ROOT / 'data/derived/zoku-v1'
CHAIRS = ROOT / 'data/acquired/office-holders/committee-chairs.csv'
INVOLVEMENTS = [ROOT / 'data/derived/allocation-v1/involvements.csv', ROOT / 'data/derived/allocation-v1/involvements-auto.csv']
OPPOSING = ROOT / 'data/derived/allocation-v1/opposing.csv'
PERSONS = ROOT / 'data/derived/person-ids/persons.csv'
ENFORCEMENT = ROOT / 'data/acquired/enforcement-dates/enforcement.csv'
BILLS = ROOT / 'data/derived/ministry-v1/cabinet-bills.csv'
LEAGUES = ROOT / 'data/acquired/diet-leagues/memberships.csv'
POSITIONS = ROOT / 'data/acquired/pressure-groups/positions.csv'
SHINGIKAI = ROOT / 'data/acquired/blocking-actors/2_shingikai'

# ADR 0018 の閾値（結果を見て動かさない。動かすときは ADR を先に改める）
MIN_CHAIR_SESSIONS = 2
MIN_BILLS = 5
MIN_YEARS = 3
MIN_MONEY_YEN = 1_000_000
PUSH_ACTIONS = ('decide', 'question', 'amend', 'chair')

# 委員会名（衆参・歴代の名称）→ 分野（今の所管省庁）。手続の委員会（予算・決算・議運・懲罰・国家基本政策）は分野を持たない。
COMMITTEE_FIELD = {
    '内閣委員会': ['内閣府'], '総務委員会': ['総務省'], '地方行政委員会': ['総務省'], '逓信委員会': ['総務省'],
    '法務委員会': ['法務省'], '外務委員会': ['外務省'], '外交防衛委員会': ['外務省', '防衛省'], '安全保障委員会': ['防衛省'],
    '財務金融委員会': ['財務省', '金融庁'], '財政金融委員会': ['財務省', '金融庁'], '大蔵委員会': ['財務省', '金融庁'],
    '文部科学委員会': ['文部科学省'], '文教科学委員会': ['文部科学省'], '文教委員会': ['文部科学省'], '科学技術委員会': ['文部科学省'],
    '厚生労働委員会': ['厚生労働省'], '厚生委員会': ['厚生労働省'], '労働委員会': ['厚生労働省'],
    '農林水産委員会': ['農林水産省'], '経済産業委員会': ['経済産業省'], '商工委員会': ['経済産業省'],
    '国土交通委員会': ['国土交通省'], '建設委員会': ['国土交通省'], '運輸委員会': ['国土交通省'], '環境委員会': ['環境省'],
}
# ロビー活動として数える行動（公表資料に残るものだけ）。報道・番組の論調、私人の言論は数えない（ADR 0014）。
LOBBY_ACTIONS = ('声明', '要望', '陳情', 'ヒアリング出席', '審議会委員', '意見公募への意見', '署名運動')
GROUP_KINDS = ('業界団体', '運動団体', 'メディア', '議員連盟', '自治体', '労働団体', 'その他')
HEADER = ['氏名', '人物ID', '分野', '委員長の回次数', '委員長の根拠URL', '推す行動の本数', '推す行動の年数', '推す行動の例（法律ID）',
          '参院本会議で賛成した本数', '参院本会議で反対した本数', '議員連盟', '同じ分野の団体との金銭の関係', '金銭の関係の根拠URL', '分野との継続的な関わり', '印']


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8', newline='') as f:
        return [r for r in csv.DictReader(f)]


def has_url(*urls: str) -> bool:
    return any(u.strip().startswith(('http://', 'https://')) for u in urls)


def field_of_ids(bills):
    return [b['法律ID'] for b in bills]


def build(chairs, involvements, opposing, bills, leagues, positions, org_fields, relations, enacted=None, ambiguous=frozenset()) -> tuple[list[dict], list[dict], dict]:
    # 成立の判定は分野（所管）の有無と分けて、公布された法律の台帳で行う
    enacted = set(field_of_ids(bills)) if enacted is None else enacted
    field_of = {b['法律ID']: b['所管_今'] for b in bills if b.get('所管_今')}
    ties: dict[tuple[str, str], dict] = defaultdict(lambda: {
        'sessions': set(), 'chair_urls': [], 'bills': set(), 'years': set(), 'yes': set(), 'no': set(),
        'leagues': [], 'money': defaultdict(int), 'money_urls': set(), 'pid': ''})
    names: dict[str, str] = {}

    def who(name: str, pid: str = '') -> str | None:
        """集計キー。同姓同名（名簿で複数の人物IDを持つ氏名）は、人物IDのある行だけ結ぶ（推測で合算しない）。"""
        n = normalize_name(name)
        if n not in ambiguous:
            return n
        key = pid if pid and pid != n else None
        if key:
            names.setdefault(key, n)
        return key

    for r in chairs:
        if not has_url(r.get('出典URL', '')):
            continue
        key = who(r['氏名'])
        if key is None:
            continue
        for field in COMMITTEE_FIELD.get(r['委員会'], []):
            t = ties[(key, field)]
            t['sessions'].add(r['国会回次'])
            if r['出典URL'] not in t['chair_urls']:
                t['chair_urls'].append(r['出典URL'])
        names.setdefault(key, r['氏名'].replace(' ', ''))

    for r in involvements:
        if r['算入'] != 'はい' or not has_url(r['証拠URL']):
            continue
        field = field_of.get(r['法律ID'])
        if not field:
            continue
        key = who(r['氏名'], r.get('人物ID', ''))
        if key is None:
            continue
        t = ties[(key, field)]
        names.setdefault(key, key)
        if r.get('人物ID'):
            t['pid'] = r['人物ID']
        if r['行動'] in PUSH_ACTIONS:
            t['bills'].add(r['法律ID'])
            t['years'].add(r['日付'][:4])
        elif r['行動'] == 'vote':
            t['yes'].add(r['法律ID'])
    for r in opposing:
        if r['算入'] != 'はい' or not has_url(r['証拠URL']):
            continue
        field = field_of.get(r['法律ID'])
        key = who(r['氏名'], r.get('人物ID', ''))
        if field and key is not None:
            ties[(key, field)]['no'].add(r['法律ID'])

    # 議員連盟：名簿に載っている事実だけ。分野の空の行は載せない（何を推進するかが決まらない）
    league_rows = []
    for r in leagues:
        if not r.get('分野') or not has_url(r.get('出典URL', '')):
            continue
        key = who(r['氏名'])
        if key is None:
            continue
        ties[(key, r['分野'])]['leagues'].append(f"{r['議連名']}（{r.get('役職') or '会員'}）{r['出典URL']}")
        names.setdefault(key, key)

    # 同じ分野の団体との金銭：受けた寄附・パーティー対価。団体の分野は審議会の発言記録で決まったものだけ。
    for r in relations:
        if r.get('区分') not in ('受けた寄附', 'パーティー対価') or not r.get('人物ID') or not has_url(r.get('PDF_URL', '')):
            continue
        key = who(r['関係議員名'], r['人物ID'])
        if key is None:
            continue
        org = r['団体名キー'] or org_key(r['相手方'])
        for field in org_fields.get(org, ()):
            t = ties[(key, field)]
            t['pid'] = t['pid'] or r['人物ID']
            t['money'][org] += int(float(r.get('金額') or 0))
            t['money_urls'].add(r['PDF_URL'])
            names.setdefault(key, key)

    rows = []
    for (key, field), t in sorted(ties.items()):
        by_chair = len(t['sessions']) >= MIN_CHAIR_SESSIONS
        by_bills = len(t['bills']) >= MIN_BILLS and len(t['years']) >= MIN_YEARS
        money = [f'{o}（{v:,}円）' for o, v in sorted(t['money'].items()) if v >= MIN_MONEY_YEN]
        if not (by_chair or by_bills or t['leagues'] or money):
            continue
        marks = []
        if by_chair or by_bills:
            marks.append('分野との継続的な関わり（族議員の機械判定）')
        if t['leagues']:
            marks.append('議員連盟の名簿に載っている')
        if money:
            marks.append('同じ分野の団体と金銭の関係が記録されている')
        rows.append({
            '氏名': names.get(key, key), '人物ID': t['pid'], '分野': field,
            '委員長の回次数': len(t['sessions']), '委員長の根拠URL': ' '.join(t['chair_urls'][:3]),
            '推す行動の本数': len(t['bills']), '推す行動の年数': len(t['years']), '推す行動の例（法律ID）': ' '.join(sorted(t['bills'])[:3]),
            '参院本会議で賛成した本数': len(t['yes']), '参院本会議で反対した本数': len(t['no']),
            '議員連盟': ' / '.join(t['leagues']), '同じ分野の団体との金銭の関係': ' / '.join(money), '金銭の関係の根拠URL': ' '.join(sorted(t['money_urls'])) if money else '',
            '分野との継続的な関わり': 'はい' if (by_chair or by_bills) else 'いいえ', '印': '、'.join(marks)})

    # 運動団体：声明・要望の事実を、法案の結果（台帳にある＝成立）に結ぶ。属性・思想では書かない。
    group_rows = []
    skipped = 0
    unverified = 0
    for r in positions:
        if r.get('立場') not in ('推進', '反対') or not has_url(r.get('出典URL', '')):
            continue
        if not r.get('確度', '').startswith('原本照合済み'):
            unverified += 1
            continue
        if r.get('行動種別') not in LOBBY_ACTIONS or r.get('団体区分') not in GROUP_KINDS:
            skipped += 1
            continue
        group_rows.append({
            '団体名': r['団体名'], '団体区分': r['団体区分'], '分野': r.get('分野') or field_of.get(r.get('法律ID', ''), ''), '法律ID': r.get('法律ID', ''),
            '立場': r['立場'], '行動種別': r.get('行動種別', ''), '法案の結果': '成立' if r.get('法律ID') in enacted else '台帳に無い（不成立または所管不明）',
            '要旨': r.get('要旨', ''), '出典URL': r['出典URL'], '確度': r['確度']})

    summary = {
        '版': 'zoku-v1', '閾値': {'委員長の回次数': MIN_CHAIR_SESSIONS, '推す行動の本数': MIN_BILLS, '推す行動の年数': MIN_YEARS, '金銭（円）': MIN_MONEY_YEN},
        '議員×分野の行': len(rows), '継続的な関わり': sum(r['分野との継続的な関わり'] == 'はい' for r in rows),
        '議員': len({r['氏名'] for r in rows}), '議連の名簿行': sum(1 for r in leagues if r.get('分野')),
        '運動団体の立場行': len(group_rows), '行動種別・団体区分が決まりに合わず除いた行': skipped, '原本照合済みでなく除いた行': unverified,
        '入力が空の表': [n for n, v in (('議員連盟', leagues), ('運動団体の立場', positions), ('政治資金の関係団体', relations)) if not v],
        '限界': ['衆法・参法は所管が決まらず分野に入らない', '委員長の記録は国会回次ごとの在任者のみ（理事・委員は無い）',
                 '議員連盟の名簿・運動団体の声明は、一次資料から足した行だけ（空のときは判定に入らない）'],
    }
    return rows, group_rows, summary


def ambiguous_names() -> set[str]:
    """名簿で2人以上に当たる氏名（鬼木誠など）。"""
    seen: dict[str, int] = defaultdict(int)
    for r in read_csv(PERSONS):
        seen[normalize_name(r['氏名'])] += 1
    return {n for n, c in seen.items() if c > 1}


def enacted_ids() -> set[str]:
    """公布日と法令番号が台帳にある法律（衆法・参法・所管不明の閣法を含む）。"""
    return {r['id'] for r in read_csv(ENFORCEMENT) if r.get('法令番号') and r.get('公布日')}


def org_fields_from_shingikai() -> dict[str, set[str]]:
    """審議会・検討会で名前のある団体が発言した会議の所管省庁（原本照合済みの行だけ）。"""
    out: dict[str, set[str]] = defaultdict(set)
    for f in sorted(SHINGIKAI.glob('*.csv')):
        for r in read_csv(f):
            if not r.get('確度', '').startswith('原本照合済み') or r.get('発言者の区分') != '業界団体':
                continue
            org = org_key(re.split(r'[\s　（(]', r['発言者の所属・肩書'].strip())[0])
            for m in re.split(r'[・、,]', re.sub(r'（[^）]*）', '', r['所管省庁'])):
                if m:
                    out[org].add(m)
    return out


def write(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, header, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--relations', type=Path, help='政治資金の関係団体 relations.csv（無ければ金銭の欄は空）')
    args = ap.parse_args(argv)
    inv = [r for p in INVOLVEMENTS for r in read_csv(p)]
    relations = read_csv(args.relations) if args.relations else []
    rows, groups, summary = build(read_csv(CHAIRS), inv, read_csv(OPPOSING), read_csv(BILLS), read_csv(LEAGUES), read_csv(POSITIONS),
                                  org_fields_from_shingikai(), relations, enacted_ids(), ambiguous_names())
    write(OUT / 'member-field-ties.csv', HEADER, rows)
    write(OUT / 'pressure-group-positions.csv', ['団体名', '団体区分', '分野', '法律ID', '立場', '行動種別', '法案の結果', '要旨', '出典URL', '確度'], groups)
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
