"""背後の力の帳簿を、議員の因果の鎖につなぐ（ロードマップ R29、設計決定0017）。

議員の因果の鎖は「行動 → 結果 → 損失」で、結び目は法律。背後の力（省庁の抵抗・審議会での団体の立場・政治資金の関係団体）は
別の帳簿に件数だけある。この結び付けは、帳簿の記録が名指しした法令名と、成立した法律の題名を、決まった規則で突き合わせる。
議員の点数（純額・順位）には足さない。結び付けは「その法律の背後にこういう記録がある」という参考の表示で、原因の断定ではない。

結び方（規則 backing-forces-v1）
- 所管：閣法の所管の省庁（data/derived/ministry-v1/cabinet-bills.csv、会議録の肩書）の、省庁全体の抵抗の件数。弱い結び付け。
  既存の2つの表の結合だけなので、この表には持たず画面側（app/src/members-build.ts）で結ぶ（正本を二重に持たない）。
- 法令名：記録の「該当法令・関連法令」の欄に書かれた法令名が、成立した法律の題名の頭（〇〇法の一部を改正する法律の〇〇法）と一致するとき。
  略称は law-aliases.csv の表で正式名に直す（表に無い略称は結ばず、unlinked.csv に理由を残す）。
  時期は順序だけで決め、年数のしきい値は使わない：記録の日付より後で最初に公布された同名の法律（次の改正の前に記録）と、
  記録の日付より前で最後に公布された同名の法律（直前の改正の後に記録）。
- 個人は名指ししない（既存の団体の帳簿の決まりを引き継ぐ）。出自・国籍・家族の属性は扱わない。

使い方（リポジトリのルートで）: python3 scripts/build_backing_forces.py [--check]
  --check: 配布している表がいまの入力から作り直したものと一致するかだけ見る（書かない）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_org_ledger  # noqa: E402
from org_names import org_key  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENACTED = ROOT / 'data/acquired/bill-census-full/enacted.csv'
ALIASES = ROOT / 'data/derived/backing-forces-v1/law-aliases.csv'
OUT_DIR = ROOT / 'data/derived/backing-forces-v1'
OUT_LINKS = OUT_DIR / 'law-links.csv'
OUT_UNLINKED = OUT_DIR / 'unlinked.csv'
OUT_CONTACTS = OUT_DIR / 'member-contacts.csv'
OUT_MANIFEST = OUT_DIR / 'manifest.json'
# 政治資金の関係（scripts/political_funds.py link が作る。大きいので Git に入れない）。無ければ「入力なし」と manifest に書く。
RELATIONS = ROOT / 'data/derived/political-funds/relations.csv'
VERSION = 'backing-forces-v1'

LINK_HEADER = ['法律ID', '帳簿', '結び方', '主体', '時期', '件数', '内訳', '関連技術', '出典URL']
UNLINKED_HEADER = ['帳簿', '法令の記載', '理由', '件数']
CONTACT_HEADER = ['人物ID', '団体', '寄附の年分', '金額の合計', '審議会での立場', '関連技術', '関連法律ID', '出典URL']
BEFORE, AFTER = '次の改正の前に記録', '直前の改正の後に記録'
WAREKI = re.compile(r'(昭和|平成|令和)\s*(元|\d+)年\s*(\d+)月\s*(\d+)日')
ISO = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
ERA_BASE = {'昭和': 1925, '平成': 1988, '令和': 2018}
ZEN_PAREN = re.compile(r'[（(][^）)]*[）)]')
# 直前の名前ごと、原資料が確定でないと留保している言及（例：医師法（議事録上の明示なし）、住宅宿泊事業法（想定））
UNSURE = re.compile(r'[^、,・;；\s（(）)]*[（(][^）)]*(?:明示なし|想定|推定|未確認|不明|記載なし)[^）)]*[）)]')
NAME_END = ('法', '法律')
CHILD_RULE = re.compile(r'(施行|規則|細則|省令|政令|令)')


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def iso_date(text: str) -> str:
    """和暦・西暦の日付を YYYY-MM-DD にする。読めなければ空。「（推定）」の注は無視する。"""
    text = unicodedata.normalize('NFKC', text or '')
    m = ISO.search(text)
    if m:
        return '-'.join(m.groups())
    m = WAREKI.search(text)
    if not m:
        return ''
    era, y, mo, d = m.groups()
    year = ERA_BASE[era] + (1 if y == '元' else int(y))
    return f'{year:04d}-{int(mo):02d}-{int(d):02d}'


UNSURE_DATE = re.compile(r'推定|想定|頃|ごろ|約|不明')


def recorded_on(text: str) -> str:
    """記録の日付。原資料が推定・概数と留保した日付は確定した日付に数えない（前後を決めないため空にする）。"""
    return '' if UNSURE_DATE.search(unicodedata.normalize('NFKC', text or '')) else iso_date(text)


def law_heads(title: str) -> list[str]:
    """成立した法律の題名から、改正（制定）の対象の法令名を取る。

    「〇〇法の一部を改正する法律案」の〇〇法、「〇〇法等の一部を…」の〇〇法、「〇〇法及び△△法の一部を…」の2本。
    新しい法律（「〇〇法案」）は〇〇法。「…の施行に伴う関係法律の整備に関する法律」は対象が多すぎるので結ばない。
    """
    t = unicodedata.normalize('NFKC', title).strip()
    t = re.sub(r'案$', '', t)
    if '整備' in t and ('施行に伴う' in t or '関係法律' in t):
        return []
    head = t.split('の一部を改正する法律')[0] if '一部を改正する法律' in t else t
    if head.endswith('の一部を改正する'):
        return []
    out: list[str] = []
    for p in [p for p in re.split(r'及び|並びに|、', head) if p] + [head]:
        p = p[:-1] if p.endswith('等') else p
        if p.endswith(NAME_END) and p not in out:
            out.append(p)  # 「社会福祉士及び介護福祉士法」のように名前に「及び」を含む法令は、分けない形も候補に残す
    return out


def load_laws() -> list[dict]:
    laws = []
    for r in read_csv(ENACTED):
        law_id = f"{r['種別']}-{r['提出回次']}-{r['番号']}"
        laws.append({'id': law_id, 'title': r['題名'], 'date': iso_date(r['公布日']), 'heads': law_heads(r['題名'])})
    return laws


def load_aliases(path: Path = ALIASES) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in read_csv(path):
        out[unicodedata.normalize('NFKC', r['略称'])] = [unicodedata.normalize('NFKC', n) for n in r['正式名'].split('；') if n]
    return out


def mentioned_names(text: str, known: set[str], aliases: dict[str, list[str]]) -> tuple[list[list[str]], str]:
    """記録の欄から、法令名を取り出す（1つの言及ごとに、同じ法令を指す名前の組。略称は改称前後の正式名の組に広がる）（長い名前を先に取り、取った所は重ねて数えない）。

    直前が漢字・かなのときは別の名前の一部とみなして取らない（例：歯科医師法の中の医師法）。取れなければ理由を返す。
    """
    t = unicodedata.normalize('NFKC', text or '')
    t, unsure = UNSURE.subn('', t)  # 留保つきの言及は確定した一致に数えない
    t = ZEN_PAREN.sub('', t).strip()
    if not t or t in ('記載なし', '議事録上の記載なし'):
        return [], '原資料に法令名の明示なし・想定（確定した法令名ではない）' if unsure else '法令名の記載なし'
    candidates = sorted(known | set(aliases), key=len, reverse=True)
    taken = [False] * len(t)
    names: list[list[str]] = []
    for cand in candidates:
        start = 0
        while True:
            i = t.find(cand, start)
            if i < 0:
                break
            start = i + 1
            if any(taken[i:i + len(cand)]):
                continue
            if i > 0 and re.match(r'[぀-ヿ一-鿿]', t[i - 1]):
                continue
            if CHILD_RULE.match(t[i + len(cand):]):
                continue  # 施行令・施行規則・省令は親の法律とは別の法令（国会の法律改正に結ばない）
            for k in range(i, i + len(cand)):
                taken[k] = True
            group = aliases.get(cand, [cand])
            if group not in names:
                names.append(group)
    if names:
        return names, ''
    if not re.search(r'法|令|条例', t):
        return [], '法令名ではない（要綱・通知・ガイドライン・制度名など）'
    return [], '成立した法律の題名に無い法令名（未改正の法令・施行令・略称が表に無い）'


def candidate_laws(name: str | list[str], laws_by_head: dict[str, list[dict]], date: str) -> list[tuple[str, dict]]:
    """法令名 name の成立した法律のうち、記録の日付に対する (時期, 法律) を返す（順序だけで決める）。

    name が複数（改称前後の正式名など、同じ法令を指す名前の組）のときは、候補をまとめてから前後を選ぶ。
    """
    names = [name] if isinstance(name, str) else name
    group = list({g['id']: g for n in names for g in laws_by_head.get(n, [])}.values())
    if not group:
        return []
    if not date:
        return [('不明', g) for g in group]
    after = [g for g in group if g['date'] and g['date'] >= date]
    before = [g for g in group if g['date'] and g['date'] < date]
    out = []
    if after:
        out.append((BEFORE, min(after, key=lambda g: (g['date'], g['id']))))
    if before:
        out.append((AFTER, max(before, key=lambda g: (g['date'], g['id']))))
    return out


def build_links(laws: list[dict], recs: list[dict], aliases: dict[str, list[str]]) -> dict:
    laws_by_head: dict[str, list[dict]] = defaultdict(list)
    for law in laws:
        for h in law['heads']:
            laws_by_head[h].append(law)
    known = set(laws_by_head)
    acc: dict[tuple, dict] = {}
    unlinked: dict[tuple, int] = defaultdict(int)
    stats = defaultdict(int)
    for rec in recs:
        is_min = rec['帳簿'] == '省庁'
        if is_min and rec['種類'] == '回答':
            continue  # 回答の分母。抵抗の件数には入らない。
        stats['記録'] += 1
        ledger = '省庁の抵抗' if is_min else '団体の立場'
        who = rec['省庁'] if is_min else rec['団体']
        names, reason = mentioned_names(rec['法令'], known, aliases)
        date = recorded_on(rec['日付'])
        if names and not date and UNSURE_DATE.search(unicodedata.normalize('NFKC', rec['日付'] or '')):
            names, reason = [], '記録の日付が推定（前後の改正を決められない）'
        hits = [h for group in names for h in candidate_laws(group, laws_by_head, date)]
        if not hits:
            unlinked[(ledger, unicodedata.normalize('NFKC', rec['法令']).strip(), reason or '名指しした法令名に、記録の前後の成立した法律が無い')] += 1
            stats['結べない'] += 1
            continue
        stats['結べた'] += 1
        seen = set()
        for period, law in hits:
            if (law['id'], period) in seen:
                continue
            seen.add((law['id'], period))
            key = (law['id'], ledger, who, period)
            a = acc.setdefault(key, {'detail': defaultdict(int), 'tech': set(), 'urls': set()})
            a['detail'][rec['種類'] if is_min else rec['立場']] += 1
            if rec['技術']:
                a['tech'].add(rec['技術'])
            a['urls'].add(rec['出典URL'])
    rows = []
    for (law_id, ledger, who, period), a in acc.items():
        n = sum(a['detail'].values())
        rows.append({'法律ID': law_id, '帳簿': ledger, '結び方': '法令名', '主体': who, '時期': period, '件数': n,
                     '内訳': '・'.join(f'{k}{v}' for k, v in sorted(a['detail'].items())), '関連技術': '、'.join(sorted(a['tech'])),
                     '出典URL': ' '.join(sorted(a['urls']))})
    rows.sort(key=lambda r: (r['法律ID'], r['帳簿'], r['結び方'], r['主体'], r['時期']))
    unlinked_rows = [{'帳簿': k[0], '法令の記載': k[1], '理由': k[2], '件数': v} for k, v in sorted(unlinked.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {'links': rows, 'unlinked': unlinked_rows, 'stats': dict(stats)}


def build_contacts(relations: list[dict[str, str]], recs: list[dict], laws: list[dict], aliases: dict[str, list[str]]) -> list[dict]:
    """政治資金の関係団体（寄附した団体）が、審議会で立場を示した団体と同じ名前のとき、議員との接点を残す。

    団体名キー（org_names.org_key）が一致するときだけ。略称の展開や支部の統合はしない。個人の寄附者は入らない（相手方種別が個人の行は除く）。
    「接点の記録だけ」で、因果は示さない。関連法律は、その団体が審議会で名指しした法令の、記録の次の改正（結べたものだけ）。
    """
    laws_by_head: dict[str, list[dict]] = defaultdict(list)
    for law in laws:
        for h in law['heads']:
            laws_by_head[h].append(law)
    known = set(laws_by_head)
    org: dict[str, dict] = {}
    for rec in recs:
        if rec['帳簿'] != '団体' or rec['団体'].startswith('（'):
            continue
        key = org_key(rec['団体'])
        if not key:
            continue
        o = org.setdefault(key, {'name': rec['団体'], 'stance': defaultdict(int), 'tech': set(), 'laws': set(), 'urls': set()})
        o['stance'][rec['立場']] += 1
        if rec['技術']:
            o['tech'].add(rec['技術'])
        names, _ = mentioned_names(rec['法令'], known, aliases)
        for group in names:
            for period, law in candidate_laws(group, laws_by_head, recorded_on(rec['日付'])):
                if period == BEFORE:
                    o['laws'].add(law['id'])
        o['urls'].add(rec['出典URL'])
    acc: dict[tuple[str, str], dict] = {}
    for r in relations:
        if r.get('区分') not in ('受けた寄附', 'パーティー対価') or r.get('相手方種別') == '個人' or not r.get('人物ID') or not r.get('団体名キー'):
            continue
        o = org.get(r['団体名キー'])
        if not o:
            continue
        a = acc.setdefault((r['人物ID'], r['団体名キー']), {'years': set(), 'amount': 0, 'urls': set()})
        a['years'].add(r['年分'])
        a['amount'] += int(r['金額'] or 0)
        if r.get('PDF_URL'):
            a['urls'].add(r['PDF_URL'])
    rows = []
    for (pid, key), a in acc.items():
        o = org[key]
        rows.append({'人物ID': pid, '団体': o['name'], '寄附の年分': '・'.join(sorted(a['years'])), '金額の合計': a['amount'],
                     '審議会での立場': '・'.join(f'{k}{v}' for k, v in sorted(o['stance'].items())), '関連技術': '、'.join(sorted(o['tech'])),
                     '関連法律ID': ' '.join(sorted(o['laws'])), '出典URL': ' '.join(sorted(a['urls'] | o['urls']))})
    rows.sort(key=lambda r: (r['人物ID'], r['団体']))
    return rows


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''


def compute() -> dict:
    laws = load_laws()
    recs = build_org_ledger.records()
    aliases = load_aliases()
    built = build_links(laws, recs, aliases)
    relations = read_csv(RELATIONS) if RELATIONS.exists() else None
    contacts = build_contacts(relations, recs, laws, aliases) if relations is not None else []
    named = [r for r in recs if not (r['帳簿'] == '省庁' and r['種類'] == '回答')]
    linked_laws = {r['法律ID'] for r in built['links'] if r['結び方'] == '法令名'}
    manifest = {
        'version': VERSION,
        'rule': 'record names a law → amendments/enactments of that law ordered by promulgation date; points are not changed',
        'inputs': {p.relative_to(ROOT).as_posix(): sha256(p) for p in (ENACTED, ALIASES)},
        'ledgers': {
            '省庁の抵抗': {'status': '接続済み', 'link': '法令名（記録ごと。この表）・所管（省庁全体。画面側で既存の2表を結ぶ）', 'records': sum(1 for r in named if r['帳簿'] == '省庁')},
            '団体の立場': {'status': '接続済み', 'link': '法令名（記録ごと）', 'records': sum(1 for r in named if r['帳簿'] == '団体')},
            '政治資金の関係団体': {'status': '接続済み' if relations is not None else '入力なし（relations.csv は Git に入れない大きな生成物）',
                           'link': '団体名キーで審議会の団体と結ぶ（接点の記録だけ）', 'rows': len(contacts)},
            '内閣': {'status': '既存の役職の帳簿（点数外）', 'link': '閣法の提出者の組。決定1・9'},
            '裁判所': {'status': '未接続', 'reason': '判決24件は法律への帰属の規則が未決。立場の記録ではなく結果の記録で、別の設計が要る'},
            '教育界': {'status': '未接続', 'reason': '一次資料の取得が未着手。入ったら団体の立場と同じ規則で結ぶ'},
        },
        'counts': {**built['stats'], '結んだ法律': len(linked_laws), '結び付けの行': len(built['links']), '結べなかった記載': len(built['unlinked'])},
    }
    return {'links': built['links'], 'unlinked': built['unlinked'], 'contacts': contacts, 'manifest': manifest, 'relations': relations is not None}


def render(path_rows: list[tuple[Path, list[str], list[dict]]], manifest: dict) -> dict[Path, str]:
    out = {}
    for path, header, rows in path_rows:
        from io import StringIO
        buf = StringIO()
        w = csv.DictWriter(buf, fieldnames=header, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
        out[path] = buf.getvalue()
    out[OUT_MANIFEST] = json.dumps(manifest, ensure_ascii=False, indent=1) + '\n'
    return out


def main(argv: list[str]) -> int:
    result = compute()
    files = [(OUT_LINKS, LINK_HEADER, result['links']), (OUT_UNLINKED, UNLINKED_HEADER, result['unlinked'])]
    if result['relations'] or OUT_CONTACTS.exists():
        files.append((OUT_CONTACTS, CONTACT_HEADER, result['contacts']))
    rendered = render(files, result['manifest'])
    if '--check' in argv:
        stale = [p.relative_to(ROOT).as_posix() for p, text in rendered.items() if not p.exists() or p.read_text(encoding='utf-8') != text]
        if stale:
            print('作り直すと変わる表:', ', '.join(stale), '（python3 scripts/build_backing_forces.py で作り直す）')
            return 1
        print('背後の力の結び付け: 配布の表は入力と一致')
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p, text in rendered.items():
        p.write_text(text, encoding='utf-8')
    print(json.dumps(result['manifest']['counts'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
