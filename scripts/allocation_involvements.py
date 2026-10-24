#!/usr/bin/env python3
"""配分（allocation-v1）の入力となる関与の一覧（involvements.csv）を作る。

入力はすべて引数で渡す。人物名を含む入力・出力は非公開の作業フォルダに置き、リポジトリには入れない。
- 収集（--collect-dir）：法律ごとの JSON。involvements に 氏名・院・行動・当時の肩書・日付・証拠URL。
- 立場（--stance-dir）：<法律ID>.lineA.json と <法律ID>.lineB.json。質疑は2系統とも「支持」のときだけ数える（ADR 0007）。
- 参議院の個人別の賛否（--votes-dir）：votes_index.csv・members.csv・ballots/ballots_<回次>.csv。賛成（Y）を採決の関与として、出典URLを証拠にする。
  衆議院には個人別の記録が無いので、採決の関与は作らない（党籍から推定しない）。
- 当時の役職（--cabinet）：cabinet.csv。日付で 内閣総理大臣／閣僚／副大臣・大臣政務官 を引く。役職は確認できた行動の重みを補正するだけで、行動を作らない。

数える条件（設計 §2-4、loss-rule の allocateLoss と同じ前提）：
- 法案を前に進めた行動（提出・決定、修正案の提出、採決を主宰した委員長、支持の質疑、参議院本会議での賛成）だけを数える。
- 参議院本会議で反対（N）した人は、その法律では反対者として何も数えない。
- 証拠URLが http(s) で始まらない行動は数えない。
- 名寄せは空白（半角・全角）と敬称を除き、同一人物の字体ゆれ（髙→高 など。scripts/person_ids.py の表）だけを寄せた文字列の一致で行い、一致しない・複数に一致するものは推測せず一覧に残す。
  表記ゆれは --aliases <csv>（列：別名,正名）で明示した対応だけを、正規化の後に正名へ置き換える（推測はしない）。表そのものは人名を含むので非公開に置く。
- 人物ID（列の末尾）：名簿（--roster）で同姓同名を分けた名前は、一次資料で所属が決まる行だけ人物IDに結ぶ。
  行の院は発言した会議の院で議員の所属院ではないので使わない。結べるのは data/derived/person-ids/overrides.csv に載った行と、参議院の投票記録から作った vote 行だけで、
  それ以外は算入=いいえ・除外理由「同姓同名で人物を決められない」にする。
  分けた名前には内閣名簿の役職を付けない（内閣名簿は院を持たず、どちらの人か決められない）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HONORIFICS = ('君', '議員', '先生', 'さん', '氏', '殿', '様')
STANCE_SUPPORT = '支持'
HEADER = ['法律ID', '題名', '氏名', '氏名_原表記', '院', '行動', '当時の肩書', '立場区分', '立場の根拠', '日付', '証拠URL',
          '系統A', '系統B', '参院本会議の賛否', '算入', '除外理由', '人物ID']


def normalize_name(name: str) -> str:
    """空白（半角・全角・その他の空白）を除き、末尾の敬称を除く。字体の置き換え（濱→浜 など）はしない。"""
    s = unicodedata.normalize('NFKC', name or '')
    s = re.sub(r'\s+', '', s)
    changed = True
    while changed:
        changed = False
        for h in HONORIFICS:
            if len(s) > len(h) + 1 and s.endswith(h):
                s, changed = s[: -len(h)], True
    return s


def load_aliases(path: Path | None) -> dict[str, str]:
    """別名,正名 の表を読み、正規化した別名 → 正規化した正名 の辞書にする。同じ別名に違う正名があれば誤りとして止める。"""
    if path is None:
        return {}
    out: dict[str, str] = {}
    for r in read_csv(path):
        a, c = normalize_name(r['別名']), normalize_name(r['正名'])
        if not a or not c or a == c:
            continue
        if out.setdefault(a, c) != c:
            raise ValueError(f'別名に複数の正名があります：{a}')
    if any(c in out for c in out.values()):
        raise ValueError('別名の連鎖があります（正名がさらに別名になっている）')
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def strip_agenda(title: str) -> str:
    return re.sub(r'^日程第[0-9０-９一二三四五六七八九十]+\s*', '', unicodedata.normalize('NFKC', title)).strip()


def find_plenary_votes(index_rows: list[dict], title: str, min_session: int, max_session: int | None = None) -> list[dict]:
    """参議院本会議の投票のうち、議案名が「題名（」で始まるもの（同名の改正法案や別の法案を拾わない）。
    max_session（成立回次）を渡すと、それより後の回次の同名の法案も拾わない。"""
    t = unicodedata.normalize('NFKC', title)
    out = []
    for r in index_rows:
        if int(r['回次']) < min_session or (max_session is not None and int(r['回次']) > max_session):
            continue
        name = strip_agenda(r['議案名'])
        if name.startswith(t + '(') or name == t:
            out.append(r)
    return out


def _canonical(name: str) -> str:
    from scripts.person_ids import canonical  # person_ids が normalize_name を読むので、循環しないよう呼ぶ時に読み込む
    return canonical(name)


class Cabinet:
    def __init__(self, rows: list[dict], norm=_canonical):
        self.rows = [dict(r, _n=norm(r['氏名'])) for r in rows]

    def position_at(self, name: str, date: str) -> tuple[str, str]:
        """(立場区分, 根拠)。同じ日に複数あれば重い方。"""
        best = ('other', '')
        rank = {'other': 0, 'vice_minister_or_chair': 1, 'minister_or_party_exec': 2, 'prime_minister': 3}
        for r in self.rows:
            if r['_n'] != name:
                continue
            start, end = r.get('就任日_西暦') or '', r.get('退任日_西暦') or ''
            if not start or date < start or (end and date > end):
                continue
            if r['区分'] == '閣僚' and '法制局長官' in r['役職']:
                continue  # 国会議員ではない職。
            if r['区分'] == '閣僚' and '副長官' in r['役職']:
                pos = 'vice_minister_or_chair'  # 内閣官房副長官などは官邸の名簿で閣僚の欄にあるが、大臣ではない。
            elif r['区分'] == '閣僚':
                pos = 'prime_minister' if r['役職'] == '内閣総理大臣' else 'minister_or_party_exec'
            elif r['区分'] in ('副大臣', '大臣政務官'):
                pos = 'vice_minister_or_chair'
            else:
                continue
            if rank[pos] > rank[best[0]]:
                best = (pos, f"{r['内閣名']} {r['区分']} {r['役職']}（{start}〜{end or '在任中'}）")
        return best


def stance_map(path: Path, norm=normalize_name) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    for x in json.loads(path.read_text(encoding='utf-8')):
        out.setdefault(norm(x['氏名']), []).append(x['立場'])
    return out


def stance_reason(a: list[str], b: list[str]) -> str:
    """質疑を数えない理由。2系統とも（全件）支持なら空文字。"""
    xs = a + b
    if xs and all(x == STANCE_SUPPORT for x in xs):
        return ''
    if xs and all(x == '反対' for x in xs):
        return '2系統とも反対（反対者として数えない）'
    if set(a) != set(b):
        return f"2系統の立場が一致しない（A:{'／'.join(a)}、B:{'／'.join(b)}。ADR 0007）"
    return f"2系統とも{'／'.join(sorted(set(a)))}（支持ではない）"


def build(collect_dir: Path, stance_dir: Path, votes_dir: Path, cabinet_csv: Path, aliases: dict[str, str] | None = None,
          roster_csv: Path | None = None, persons_csv: Path | None = None, overrides_csv: Path | None = None) -> tuple[list[dict], list[dict]]:
    """(関与の行, 注記の行)。注記は名寄せの不一致・投票の特定・立場の欠落など、人が確かめる事項。
    aliases は 正規化した別名 → 正規化した正名。名前を読む箇所（収集・立場・投票名簿・内閣名簿）のすべてで正規化の後に適用する。
    roster_csv（現職の名簿）で同姓同名を院で分け、行ごとに人物IDを付ける。名簿が無ければ人物ID は寄せた氏名そのもの。
    persons_csv（前の台帳）があれば、付けた人物IDと分離を引き継ぐ（名簿から消えた人も残す）。"""
    from scripts import person_ids

    aliases = aliases or {}

    def plain(name: str) -> str:
        n = normalize_name(name)
        return aliases.get(n, n)

    def norm(name: str) -> str:
        return person_ids.canonical(plain(name))

    cabinet_rows = read_csv(cabinet_csv)
    ledger = person_ids.build_ledger(read_csv(roster_csv) if roster_csv else [], cabinet_rows,
                                     previous=read_csv(persons_csv) if persons_csv and persons_csv.exists() else None,
                                     overrides=person_ids.load_overrides(overrides_csv))
    cabinet = Cabinet(cabinet_rows, norm)
    index = read_csv(votes_dir / 'votes_index.csv')
    members = read_csv(votes_dir / 'members.csv')
    rows: list[dict] = []
    notes: list[dict] = []

    def note(law, kind, text):
        notes.append({'法律ID': law, '種類': kind, '内容': text})

    for f in sorted(collect_dir.glob('*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        law, title = d['id'], d['title']
        session = int(re.search(r'-(\d+)-', law).group(1))
        a_path, b_path = stance_dir / f'{law}.lineA.json', stance_dir / f'{law}.lineB.json'
        sa, sb = stance_map(a_path, norm), stance_map(b_path, norm)
        if not a_path.exists() or not b_path.exists():
            note(law, '立場の判定なし', '系統A・Bの立場ファイルがそろわないため、質疑は1件も数えない')

        # 参議院本会議の個人別の賛否
        votes = find_plenary_votes(index, title, session, d.get('成立回次'))
        ballots: dict[str, str] = {}
        vote_row = None
        if len(votes) == 1:
            vote_row = votes[0]
            vs = vote_row['回次']
            same = [m for m in members if m['回次'] == vs]
            seats = Counter(norm(m['議員名']) for m in same)
            # 同姓同名で分けた名前は、対応表 (法律ID, 投票の出典URL) で決める。ただし同じ回次にその氏名の議員IDが2つ以上あると、
            # 対応表がどの議員IDの票を指すか分からないので決めない。
            mem = {m['議員ID']: ('' if ledger.is_split(norm(m['議員名'])) and seats[norm(m['議員名'])] > 1
                                else ledger.resolve(norm(m['議員名']), law, vote_row['出典URL'], sangiin_vote=True)[0]) for m in same}
            # 同じ回次で会派が変わると、同じ表記の議員IDが複数ある。この投票に記録のあるIDが1つだけなら同じ人とみなし、
            # 2つ以上あるとき（同姓同名の別人の可能性）は推測せず使わない。人物は人物IDで数える（参議院の名簿で分けた同姓同名は別人）。
            cast: dict[str, list[str]] = {}
            for b in read_csv(votes_dir / 'ballots' / f'ballots_{vs}.csv'):
                if b['投票ID'] == vote_row['投票ID'] and mem.get(b['議員ID']):
                    cast.setdefault(mem[b['議員ID']], []).append(b['賛否'])
            for n, xs in sorted(cast.items()):
                if len(xs) == 1:
                    ballots[n] = xs[0]
                else:
                    note(law, '名寄せ（同名）', f'第{vs}回の参議院の投票記録で、同じ表記の議員IDが複数この投票に記録されているため使わない：{n}')
            note(law, '参院本会議の投票', f"{vote_row['投票ID']}（{vote_row['投票日']}）賛成{vote_row['集計_賛成']}・反対{vote_row['集計_反対']}・投票なし{vote_row['集計_投票なし']}")
        else:
            note(law, '参院本会議の投票', f'議案名で特定できない（候補{len(votes)}件）。採決の関与は作らない')

        collected_names = set()
        chairs = {ledger.resolve(norm(v['氏名']), law, v.get('証拠URL') or '')[0] for v in d['involvements'] if v['行動'] == 'chair'} - {''}
        for v in d['involvements']:
            n = norm(v['氏名'])
            collected_names.add(n)
            pid, unresolved = ledger.resolve(n, law, v.get('証拠URL') or '')
            act, date, url = v['行動'], v.get('日付') or '', v.get('証拠URL') or ''
            # 同姓同名で分けた名前には役職を付けない（内閣名簿は院を持たず、どちらの人か決められない）。
            pos, why = cabinet.position_at(n, date) if date and not ledger.is_split(n) else ('other', '')
            title_at = v.get('当時の肩書') or ''
            if pos == 'other' and (pid in chairs or re.match(r'^[^（(]*委員長(?!報告)', title_at)):
                pos, why = 'vice_minister_or_chair', '本件の委員会の委員長（収集の記録）'
            a, b = '／'.join(sa.get(n, [])), '／'.join(sb.get(n, []))
            ballot = ballots.get(pid, '') if vote_row and pid else ''
            reason = ''
            if not re.match(r'^https?://', url):
                reason = '証拠URLが無い'
            elif ballot == 'N':
                reason = '参議院本会議で反対票（反対者として数えない）'
            elif act == 'question':
                if not sa or not sb:
                    reason = '立場の判定ファイルが無い（2系統の一致を確かめられない）'
                elif n not in sa or n not in sb:
                    reason = '立場の判定に本人の記録が無い'
                else:
                    reason = stance_reason(sa[n], sb[n])
            # 人物が決まらない理由は、ほかの理由が無いときだけ入れる（annotate が人物の決まった行を算入に戻すとき、
            # 立場や賛否で外した行まで戻さないように）。
            if not reason and unresolved:
                reason = unresolved
            rows.append({'法律ID': law, '題名': title, '氏名': plain(v['氏名']), '氏名_原表記': v['氏名'], '院': v.get('院') or '', '行動': act,
                         '当時の肩書': title_at, '立場区分': pos, '立場の根拠': why, '日付': date, '証拠URL': url,
                         '系統A': a, '系統B': b, '参院本会議の賛否': ballot, '算入': 'いいえ' if reason else 'はい', '除外理由': reason, '人物ID': pid})

        if vote_row:
            # 収集の関与にあるが、参議院の名簿にも内閣名簿にも無い名前（ひらがな表記など）は、照合できなかったとして残す。
            for n in sorted(collected_names):
                in_cab = any(r['_n'] == n for r in cabinet.rows)
                if ledger.resolve(n, law, vote_row['出典URL'], sangiin_vote=True)[0] not in ballots and not in_cab and any(v['院'] == '参議院' and norm(v['氏名']) == n and v['行動'] == 'question' for v in d['involvements']):
                    note(law, '名寄せ（不一致）', f'参議院の会議で質疑した人が、第{vote_row["回次"]}回の参議院の投票記録に見つからない（衆議院議員か、表記の違い）：{n}')
            for pid, yn in sorted(ballots.items()):
                if yn != 'Y':
                    continue
                n = person_ids.canonical(ledger.display(pid))
                pos, why = cabinet.position_at(n, vote_row['投票日']) if not ledger.is_split(n) else ('other', '')
                if pos == 'other' and pid in chairs:
                    pos, why = 'vice_minister_or_chair', '本件の委員会の委員長（収集の記録）'
                rows.append({'法律ID': law, '題名': title, '氏名': ledger.display(pid), '氏名_原表記': ledger.display(pid), '院': '参議院', '行動': 'vote',
                             '当時の肩書': '', '立場区分': pos, '立場の根拠': why, '日付': vote_row['投票日'], '証拠URL': vote_row['出典URL'],
                             '系統A': '／'.join(sa.get(n, [])), '系統B': '／'.join(sb.get(n, [])), '参院本会議の賛否': 'Y', '算入': 'はい', '除外理由': '', '人物ID': pid})
    person_ids.unify_names(rows, ledger)
    return rows, notes


def annotate(rows: list[dict], ledger, cabinet: 'Cabinet') -> tuple[int, list[dict]]:
    """できあがっている関与の一覧に、人物IDを付け直し、役職の照合を canonical で直す（何度流しても同じ結果）。
    (氏名・役職・算入を直した行の数, 行)。同姓同名で決まらない行は算入=いいえにし、決まるようになった行は戻す。
    役職は、寄せた氏名で新しく見つかったときだけ上書きする（髙/高の取りこぼしを拾う）。分けた名前には付けない。"""
    from scripts import person_ids

    chair_basis = '本件の委員会の委員長'
    out: list[dict] = []
    before: list[dict] = []
    dropped = 0
    for r in rows:
        old, r = r, dict(r)
        canon = person_ids.canonical(r['氏名'])
        pid, unresolved = ledger.resolve(r['氏名'], r['法律ID'], r['証拠URL'], person_ids._is_sangiin_vote(r))
        r['人物ID'] = pid
        if unresolved and r['算入'] == 'はい':
            r['算入'], r['除外理由'] = 'いいえ', unresolved
        elif not unresolved and r['除外理由'] == person_ids.UNRESOLVED:
            r['算入'], r['除外理由'] = 'はい', ''
        if ledger.is_split(canon):
            if r['立場区分'] != 'other' and not r['立場の根拠'].startswith(chair_basis):
                r['立場区分'], r['立場の根拠'] = 'other', ''
        elif r['日付']:
            pos, why = cabinet.position_at(canon, r['日付'])
            if pos != 'other':
                if r['立場の根拠'].startswith('読み直しで足した質疑'):
                    dropped += 1
                    continue  # 政府側の答弁だった人は、質疑の行として足さない（apply_resolved_stance の決まり）
                r['立場区分'], r['立場の根拠'] = pos, why
        out.append(r)
        before.append(old)
    person_ids.unify_names(out, ledger)
    changed = dropped + sum(any(a.get(k, '') != b[k] for k in HEADER if k != '人物ID') for a, b in zip(before, out))
    return changed, out


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--collect-dir', required=True, type=Path)
    p.add_argument('--stance-dir', required=True, type=Path)
    p.add_argument('--votes-dir', required=True, type=Path)
    p.add_argument('--cabinet', required=True, type=Path)
    p.add_argument('--aliases', type=Path, help='別名,正名 の CSV（非公開に置く）')
    p.add_argument('--roster', type=Path, help='現職の名簿 CSV（同姓同名を院で分ける。既定は data/acquired/diet-roster/current.csv）')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--notes-out', type=Path)
    a = p.parse_args(argv)
    aliases = load_aliases(a.aliases)
    from scripts import person_ids

    rows, notes = build(a.collect_dir, a.stance_dir, a.votes_dir, a.cabinet, aliases, a.roster or person_ids.ROSTER,
                        person_ids.OUT_DIR / 'persons.csv', person_ids.OVERRIDES)
    if aliases:
        applied = sorted({(r['氏名_原表記'], r['氏名']) for r in rows if normalize_name(r['氏名_原表記']) in aliases})
        notes.append({'法律ID': '', '種類': '別名の適用', '内容': f'別名表 {len(aliases)} 件、関与の行に適用 {len(applied)} 件'})
    write_csv(a.out, HEADER, rows)
    if a.notes_out:
        write_csv(a.notes_out, ['法律ID', '種類', '内容'], notes)
    counted = sum(r['算入'] == 'はい' for r in rows)
    print(f'関与 {len(rows)} 行（算入 {counted}、除外 {len(rows) - counted}）、注記 {len(notes)} 件')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
