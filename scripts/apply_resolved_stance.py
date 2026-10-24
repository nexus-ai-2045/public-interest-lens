#!/usr/bin/env python3
"""関与の一覧（allocation-v1/involvements.csv）に、読み直しで決まった審議での立場を反映する。

入力:
- 関与の一覧（--involvements）
- 読み直しの最終の立場（--resolved、private-m2/causal-chain/stance-final.csv。scripts/reread_causal_chain_stance.py merge の出力）
- 参議院の個人別の賛否（--votes-dir）。新しく足す質疑の人が本会議で反対していないかを見る。

反映の決まり（ADR 0007 の「2系統一致」を保つ）:
1. 関与の一覧で「2系統の立場が一致しない」「立場の判定に本人の記録が無い」で外していた質疑は、
   読み直しで立場が決まっていれば、それに置き換える。支持なら算入、それ以外は理由つきで外す。
   参議院本会議の反対票・証拠URLの発言者違いで外した行には触れない。
2. 読み直しで立場が決まった議員のうち、関与の一覧に質疑の行が無い人は、質疑の行として足す。
   質疑は成立を左右しないので額の配分には入らない（議員ページに記録として出るだけ）。
   足すのは国会議員だと確かめられた人だけ（参議院の名簿・内閣の名簿・関与の一覧に有る人、
   または会議録の見出しに肩書の括弧が無い人）。参考人・政府参考人（局長など）は足さない。
3. 上位の読み手（系統C・D が割れた組の判定者）の支持は、系統C か D のどちらかと一致したとき
   （3つの読みのうち2つが同じ）だけ算入する。判定者だけの支持は理由つきで外す。
4. 置き換えた行の系統A・B は元の値を残し、読み直しの結果は除外理由と算入で表す。
   足した行・置き換えた行には立場の根拠に印をつけ、もう一度流したときは今の stance-final で作り直す（何度流しても同じ結果）。
5. 最終の採決（関与の一覧の vote の日）より後の発言は、成立を後押しした質疑ではないので足さない。
7. 足すのはその法案の審議での発言だけ（委員会は付託先、本会議は法案の正式名が出て、別の法案の名前が出ない発言）。
6. 質疑として足すのは質問した人だけ。同じ法律で提出・修正・委員長の行がある人（提出者・大臣・委員長として答弁や
   説明をした人）と、発言の日に大臣・副大臣・政務官だった人（政府側の答弁）は足さない。
実名は入力データとして扱うだけで、このファイルには書かない。

使い方:
  python3 scripts/apply_resolved_stance.py --involvements data/derived/allocation-v1/involvements.csv \
    --resolved /mnt/project-files/private-m2/causal-chain/stance-final.csv --votes-dir data/acquired/sangiin-votes --aliases /mnt/project-files/private-m2/allocation/aliases.csv [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from allocation_involvements import HEADER, Cabinet, find_plenary_votes, load_aliases, normalize_name, read_csv  # noqa: E402
from person_ids import canonical  # noqa: E402

REPLACEABLE = ('2系統の立場が一致しない', '立場の判定に本人の記録が無い', '立場の判定ファイルが無い')
DATE = re.compile(r"/txt/\d{9}X\d{3}(\d{8})/")
HOUSE = re.compile(r"/txt/\d{4}(\d)\d{4}X")
ADDED = '読み直しで足した質疑（stance-final）'
REPLACED = '読み直しで置き換えた質疑（stance-final）'
JUDGE_ONLY = '上位の読み手だけの判定（系統C・D のどちらとも違う。ADR 0007）'


def house_of(url: str, fallback: str) -> str:
    """会議録の URL の会議 ID（先頭1桁・回次3桁の次の桁）から院を読む。0=衆議院、1=参議院。"""
    m = HOUSE.search(url)
    return {'0': '衆議院', '1': '参議院'}.get(m.group(1), fallback) if m else fallback


def decide(s: dict) -> tuple[bool, str]:
    """(算入するか, 外す理由)。"""
    if s['立場'] != '支持':
        return False, f"読み直しで{s['立場']}（{s['決め方']}。支持ではない）"
    if s['決め方'] == '上位の読み手の判定' and '支持' not in (s.get('系統C'), s.get('系統D')):
        return False, JUDGE_ONLY
    return True, ''


def ballots_for(votes_dir: Path, title: str, session: int, norm) -> dict[str, str]:
    """参議院本会議の個人別の賛否（正規化した氏名 → Y/N）。投票が1件に決まらなければ空。"""
    votes = find_plenary_votes(read_csv(votes_dir / 'votes_index.csv'), title, session)
    if len(votes) != 1:
        return {}
    v = votes[0]
    mem = {m['議員ID']: norm(m['議員名']) for m in read_csv(votes_dir / 'members.csv') if m['回次'] == v['回次']}
    cast: dict[str, list[str]] = {}
    for b in read_csv(votes_dir / 'ballots' / f"ballots_{v['回次']}.csv"):
        if b['投票ID'] == v['投票ID'] and b['議員ID'] in mem:
            cast.setdefault(mem[b['議員ID']], []).append(b['賛否'])
    return {n: xs[0] for n, xs in cast.items() if len(xs) == 1}


def apply(inv: list[dict], resolved: list[dict], votes_dir: Path, aliases: dict[str, str] | None = None,
          legislators: set[str] | None = None, cabinet: Cabinet | None = None,
          on_bill=None, split: set[str] | None = None) -> tuple[list[dict], Counter]:
    """legislators：質疑の行を新しく足してよい人（正規化した氏名）。None なら全員。
    on_bill(法律ID, 原表記の氏名, 証拠URL)：その発言がこの法案の審議か。None なら確かめない。
    split：人物台帳で同姓同名に分かれた氏名（canonical）。読み直しは氏名で結ぶのでどちらの人の立場か分からず、使わない。"""
    aliases = aliases or {}
    split = split or set()
    norm = lambda x: aliases.get(normalize_name(x), normalize_name(x))
    laws = {r['法律ID'] for r in inv}
    c: Counter = Counter()
    res = {}
    for r in resolved:
        if r['法案ID'] in laws and r['区分'] == '議員' and r['立場'] in ('支持', '反対', '中立'):
            if canonical(norm(r['氏名'])) in split:
                c['使わない:同姓同名で人物を決められない'] += 1
                continue
            res[(r['法案ID'], norm(r['氏名']))] = r
    out = []
    has_question = set()
    other_role = {(r['法律ID'], r['氏名']) for r in inv if r['行動'] in ('decide', 'amend', 'chair')}
    for r in inv:
        r = dict(r)
        key = (r['法律ID'], r['氏名'])
        if r['行動'] == 'question' and r['立場の根拠'] == ADDED:
            continue  # 前回足した行は捨てて、今の stance-final から作り直す。
        if r['行動'] == 'question':
            has_question.add(key)
            s = res.get(key)
            if s and (r['立場の根拠'] == REPLACED or (r['算入'] == 'いいえ' and r['除外理由'].startswith(REPLACEABLE))):
                counted, reason = decide(s)
                r['算入'] = 'はい' if counted else 'いいえ'
                r['除外理由'] = reason
                r['立場の根拠'] = REPLACED
                c[f"置き換え:{s['立場']}"] += 1
            elif r['立場の根拠'] == REPLACED:
                # 前回置き換えたが、今の stance-final では支持・反対・中立のどれでもない（無関係・判定待ち）。
                r['算入'] = 'いいえ'
                r['除外理由'] = '読み直しで立場が決まらない（無関係または判定待ち）'
                c['置き換え:立場なし'] += 1
        out.append(r)
    titles = {r['法律ID']: r['題名'] for r in inv}
    last_vote: dict[str, str] = {}
    for r in inv:
        if r['行動'] == 'vote' and r['日付']:
            last_vote[r['法律ID']] = max(last_vote.get(r['法律ID'], ''), r['日付'])
    ballots: dict[str, dict[str, str]] = {}
    for (law, n), s in sorted(res.items()):
        if (law, n) in has_question:
            continue
        if legislators is not None and n not in legislators:
            c['足さない:国会議員と確かめられない'] += 1
            continue
        if law not in ballots:
            ballots[law] = ballots_for(votes_dir, titles[law], int(law.split('-')[1]), norm)
        m = DATE.search(s['証拠URL'])
        date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else ''
        if date and law in last_vote and date > last_vote[law]:
            c['足さない:最終の採決より後の発言'] += 1
            continue
        pos, basis = cabinet.position_at(n, date) if cabinet and date else ('other', '')
        if (law, n) in other_role or pos != 'other':
            c['足さない:提出者・政府側・委員長の発言'] += 1
            continue
        if on_bill is not None and not on_bill(law, s['氏名'], s['証拠URL']):
            c['足さない:別の法案の審議での発言'] += 1
            continue
        ballot = ballots[law].get(n, '')
        if ballot == 'N':
            reason = '参議院本会議で反対票（反対者として数えない）'
        else:
            reason = decide(s)[1]
        out.append({'法律ID': law, '題名': titles[law], '氏名': n, '氏名_原表記': s['氏名'], '院': house_of(s['証拠URL'], s['院']), '行動': 'question',
                    '当時の肩書': '', '立場区分': pos, '立場の根拠': ADDED, '日付': date,
                    '証拠URL': s['証拠URL'], '系統A': s['系統C'] or s['立場'], '系統B': s['系統D'] or s['立場'], '参院本会議の賛否': ballot,
                    '算入': 'いいえ' if reason else 'はい', '除外理由': reason})
        c[f"追加:{s['立場']}" + ('（反対票）' if ballot == 'N' else '')] += 1
    return out, c


def untitled_speakers(speeches: Path) -> set[str]:
    """会議録の見出しに肩書の括弧が1つも無い発言者（委員として質疑した国会議員）のファイル上の氏名。"""
    out = set()
    for f in speeches.glob('*/*.txt'):
        heads = re.findall(r'^■ [^\n]*', f.read_text(encoding='utf-8'), re.M)
        if heads and not any('（' in h for h in heads):
            out.add(f.stem.split('_', 1)[1])
    return out


def legislators(inv: list[dict], sangiin: list[dict], cabinet: list[dict], speeches: Path, norm) -> set[str]:
    names = {r['氏名'] for r in inv} | {norm(r['議員名']) for r in sangiin}
    names |= {norm(r['氏名']) for r in cabinet if r['区分'] != '閣僚' or '法制局長官' not in r['役職']}
    return names | {norm(n) for n in untitled_speakers(speeches)}


def bill_checker(speeches: Path, enacted: list[dict]):
    """発言がその法案の審議かを確かめる関数を返す。
    委員会なら付託された委員会であること。本会議なら、その発言に法案の正式名が出ること
    （同じ発言に別の法案の名前も出るなら、どちらへの立場か分けられないので False。
    例：国際観光旅客税法案と国際観光振興法の改正をまとめて議題にした本会議）。"""
    committee = {f"{r['種別']}-{r['提出回次']}-{r['番号']}": {'衆議院': r['付託委員会_衆'], '参議院': r['付託委員会_参']} for r in enacted}
    names: dict[str, list[str]] = {}
    for f in sorted(speeches.parent.glob('*.json')):
        if not f.name.startswith('stance'):
            m = json.loads(f.read_text(encoding='utf-8'))
            names[m['id']] = sorted(set(m.get('keywords', [])), key=len, reverse=True)
    from reread_causal_chain_stance import EXTRA  # 法案ごとの通称（国際観光旅客税 など）
    others = sorted({k for i, ks in names.items() for k in ks + EXTRA.get(i, [])}, key=len, reverse=True)

    def ok(law: str, name: str, url: str) -> bool:
        f = next((speeches / law).glob(f'*_{name}.txt'), None)
        if f is None:
            return False
        m = re.search(r'^■ \S+ (衆議院|参議院) (\S+) 第\d+号[^\n]*\nspeechURL: ' + re.escape(url) + r'\n\n(.*?)(?=\n■ |\Z)',
                      f.read_text(encoding='utf-8'), re.S | re.M)
        if not m:
            return False
        house, meeting, body = m.groups()
        if meeting != '本会議':
            return meeting == f"{committee.get(law, {}).get(house, '')}委員会"
        own = names.get(law, [])
        mine = set(own + EXTRA.get(law, []))
        # 長い名前から順に、発言の中のどこが自分の法案でどこが別の法案かを決める
        # （「国際観光旅客税」の中の「国際観光」を、別の法案の名前とも自分の名前とも数えないため）。
        seen = set()
        for k in sorted(mine | set(others), key=len, reverse=True):
            if k in body:
                seen.add(k)
                body = body.replace(k, '\0')
        mixed = any(k not in mine for k in seen)
        return not mixed and any(k in seen for k in own)
    return ok


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--involvements', required=True, type=Path)
    p.add_argument('--resolved', required=True, type=Path)
    p.add_argument('--votes-dir', required=True, type=Path)
    p.add_argument('--aliases', required=True, type=Path, help='別名,正名 の CSV（非公開に置く）')
    p.add_argument('--cabinet', type=Path, default=Path('data/acquired/office-holders/cabinet.csv'))
    p.add_argument('--enacted', type=Path, default=Path('data/acquired/bill-census-full/enacted.csv'))
    p.add_argument('--speeches', type=Path, help='会議録の発言ファイルの置き場（既定は --resolved の隣の speeches/）')
    p.add_argument('--persons', type=Path, default=Path('data/derived/person-ids/persons.csv'), help='人物台帳（同姓同名の判定に使う）')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args(argv)
    inv = read_csv(a.involvements)
    aliases = load_aliases(a.aliases)
    norm = lambda x: aliases.get(normalize_name(x), normalize_name(x))
    cab_rows = read_csv(a.cabinet)
    legis = legislators(inv, read_csv(a.votes_dir / 'members.csv'), cab_rows, a.speeches or a.resolved.parent / 'speeches', norm)
    speeches = a.speeches or a.resolved.parent / 'speeches'
    on_bill = bill_checker(speeches, read_csv(a.enacted))
    names = Counter(canonical(r['氏名']) for r in read_csv(a.persons)) if a.persons.exists() else Counter()
    out, c = apply(inv, read_csv(a.resolved), a.votes_dir, aliases, legis, Cabinet(cab_rows, norm), on_bill,
                   split={n for n, k in names.items() if k > 1})
    bad = [r for r in out if r['算入'] == 'はい' and not re.match(r'^https://kokkai\.ndl\.go\.jp/', r['証拠URL']) and r['行動'] == 'question']
    if bad:
        raise SystemExit(f'算入する質疑に会議録の URL が無い行があります: {len(bad)}')
    print(dict(sorted(c.items())), f'{len(inv)} → {len(out)} 行')
    if not a.dry_run:
        with a.involvements.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            w.writerows(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
