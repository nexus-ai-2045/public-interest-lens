#!/usr/bin/env python3
"""成立した法律ごとに、付託された委員会の審議（委員名簿・採決・修正案・附帯決議）を国会会議録検索システム API から取る。

法律ができるまでの動きのうち、これまで手元に無かった次の4つを埋める。
  (1) 委員会の委員名簿（誰が審議の場にいたか）…会議録の冒頭「出席委員」の和集合
  (2) 委員会ごとの審議経過と委員会での採決…会議（号）の一覧、委員長が宣告した採決の結果と方法
  (3) 修正案の中身と提出者…委員長が読み上げる「○○君外N名から修正案が提出」と趣旨説明の発言
  (4) 附帯決議の本文…決議案の趣旨説明の発言（案文を朗読する）と、決議の採決・政府の所信

取得元は kokkai.ndl.go.jp の meeting API だけ。法律の付託委員会・付託日・議決日は enacted.csv（衆議院の議案情報）から引く。
API の応答は --raw に1リクエスト1ファイル（gzip）で保存し、解析（build）はその保存分だけで再現できる（再取得しない）。
原本はリポジトリに入れず、公開するのは抽出した CSV だけ（data/acquired/committee-deliberation/）。

使い方:
  python3 scripts/fetch_committee_deliberation.py fetch --raw .local/committee-deliberation/raw [--workers 3] [--limit N] [--ids 衆法-186-35 ...]
  python3 scripts/fetch_committee_deliberation.py register --raw .local/committee-deliberation/raw   # 取った応答を外部資料の保管庫に登録（fetch は取るたびに自動で登録する）
  python3 scripts/fetch_committee_deliberation.py build --raw .local/committee-deliberation/raw --out data/acquired/committee-deliberation

相手への負荷: 全体で約0.7秒に1リクエスト以下（並列でも共通の間隔を守る）。失敗は間隔を倍にして3回まで取り直す。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from register_external_material import register_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
API = 'https://kokkai.ndl.go.jp/api/meeting'
STORAGE = ROOT / '.local/external-materials'
TASK_ID = 'committee-deliberation'
ENACTED = ROOT / 'data/acquired/bill-census-full/enacted.csv'
UA = 'public-interest-lens committee-deliberation (research; contact via GitHub nexus-ai-2045/public-interest-lens)'
INTERVAL = 0.7
HOUSES = (('衆議院', '付託日_衆', '付託委員会_衆', '議決日_衆'), ('参議院', '付託日_参', '付託委員会_参', '議決日_参'))
SKIP_COMMITTEE = ('', '審査省略', '本会議')
ROLES = ('委員長', '副委員長', '理事', '会長', '副会長', '幹事', '委員', '会長代理', '委員長代理')
ROLE_RANK = {'委員長': 0, '会長': 0, '副委員長': 1, '副会長': 1, '理事': 2, '幹事': 2}
END_MARK = re.compile(r'…{3,}|―{3,}|ー{3,}|国務大臣|政府参考人|政府特別補佐人|事務局|専門員|説明員|参考人|本日の会議に付した案件|委員の異動|出席政府|出席説明員|法制局|調査局|調査室')

_lock = threading.Lock()
_last = [0.0]


def wareki(text: str) -> str:
    m = re.search(r'(明治|大正|昭和|平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日', text or '')
    if not m:
        return ''
    base = {'明治': 1867, '大正': 1911, '昭和': 1925, '平成': 1988, '令和': 2018}[m.group(1)]
    y = (1 if m.group(2) == '元' else int(m.group(2))) + base
    return f'{y}-{int(m.group(3)):02d}-{int(m.group(4)):02d}'


def committee_query_name(c: str) -> str:
    c = c.strip()
    return c if c.endswith(('委員会', '審査会', '調査会')) else c + '委員会'


def short_title(title: str) -> str:
    return re.sub(r'案$', '', title)


def raw_path(raw: Path, key: str) -> Path:
    return raw / (hashlib.sha1(key.encode()).hexdigest() + '.json.gz')


def http_get(url: str) -> bytes:
    for i in range(4):
        with _lock:
            wait = _last[0] + INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == 3:
                raise RuntimeError(f'{url}: {e}') from e
            time.sleep(INTERVAL * 2 ** (i + 2))
    raise RuntimeError('unreachable')


def query_params(bill: dict, house: str, d_from: str, d_to: str, committee: str | None) -> dict:
    p = {'nameOfHouse': house, 'from': d_from, 'until': d_to, 'any': short_title(bill['題名']),
         'maximumRecords': 10, 'recordPacking': 'json'}
    if committee:
        p['nameOfMeeting'] = committee
    return p


def plan(bill: dict):
    """この法律で取る問い合わせ（院ごと）を返す。"""
    for house, c_dt, c_cm, c_vote in HOUSES:
        cm = (bill[c_cm] or '').strip()
        if cm in SKIP_COMMITTEE:
            continue
        d_to = wareki(bill[c_vote])
        if not d_to:
            continue
        d_from = wareki(bill[c_dt]) or (date.fromisoformat(d_to) - timedelta(days=150)).isoformat()
        yield house, cm, d_from, d_to


def register_raw(p: Path, key: str, observed_at: str | None = None) -> str:
    """取った応答を外部資料の保管庫（.local/external-materials/<task-id>/）に登録する。内容は unverified のまま（AGENTS.md）。"""
    return register_once(input_path=p, source_url=API + '?' + key, task_id=TASK_ID, title='国会会議録検索システム API の応答（委員会の会議録）',
                         purpose='法律の委員会審議（委員名簿・採決・修正案・附帯決議）を取り出す', storage_root=STORAGE, observed_at=observed_at)


def fetch_one(bill: dict, house: str, cm: str, d_from: str, d_to: str, raw: Path) -> int:
    n = 0
    for committee in (committee_query_name(cm), None):
        params = query_params(bill, house, d_from, d_to, committee)
        start, got = 1, 0
        while True:
            q = dict(params, startRecord=start)
            key = urllib.parse.urlencode(sorted(q.items()))
            p = raw_path(raw, key)
            if p.exists():
                d = json.loads(gzip.decompress(p.read_bytes()))
            else:
                body = http_get(API + '?' + key)
                d = json.loads(body)
                p.write_bytes(gzip.compress(json.dumps({'query': key, 'response': d}, ensure_ascii=False).encode(), 6))
                register_raw(p, key, datetime.now().astimezone().isoformat(timespec='seconds'))
                d = {'query': key, 'response': d}
            d = d['response'] if 'response' in d else d
            n += 1
            got += len(d.get('meetingRecord') or [])
            nxt = d.get('nextRecordPosition')
            if not nxt:
                break
            start = int(nxt)
        if got:  # 委員会名で絞って1件でもあれば十分。0件なら絞らずに取り直す（委員会名の表記ゆれ対策）
            break
    return n


def cmd_fetch(a) -> int:
    global INTERVAL
    INTERVAL = a.interval
    raw = Path(a.raw)
    raw.mkdir(parents=True, exist_ok=True)
    bills = list(csv.DictReader(open(ENACTED, encoding='utf-8')))
    if a.ids:
        want = set(a.ids)
        bills = [b for b in bills if f"{b['種別']}-{b['提出回次']}-{b['番号']}" in want]
    jobs = [(b, *pl) for b in bills for pl in plan(b)]
    if a.limit:
        jobs = jobs[: a.limit]
    done = [0]

    def run(j):
        try:
            fetch_one(j[0], j[1], j[2], j[3], j[4], raw)
        except Exception as e:  # noqa: BLE001
            print('FAIL', j[0]['題名'], j[1], e, file=sys.stderr)
        done[0] += 1
        if done[0] % 100 == 0:
            print(f'{done[0]}/{len(jobs)}', file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(run, jobs))
    print('fetched', len(jobs), 'jobs', file=sys.stderr)
    return 0


# ---------------------------------------------------------------- 解析

def norm_name(s: str) -> str:
    s = unicodedata.normalize('NFKC', s or '')
    s = re.sub(r'\s+', '', s)
    return re.sub(r'(君|さん|議員)$', '', s)


NONMEMBER_RE = re.compile(r'事務総長|議長|外の出席者|参考人|専門|事務局|事務次長|調査員|説明員|国務大臣|政府|[()（）]|委員|会長|理事長|教授|社長|取締|基金|協会|連合|会社|銀行|分科|代行|執行|学部|局|代表|常任|大臣|議院|議員|運営|[—―]|発議|修正案|提出|内閣|官房|長官|副大臣|政務官')


def parse_attendance(header: str, house: str) -> list[tuple[str, str]]:
    """会議録冒頭の「出席委員」（参議院は「出席者は左のとおり」）から (氏名, 役職) を返す。"""
    i = header.find('出席委員')
    if i < 0:
        i = header.find('出席者は左のとおり')
    if i < 0:
        return []
    block = header[i:]
    block = block.split('\n', 1)[1] if '\n' in block else block
    m = END_MARK.search(block)
    if m:
        block = block[: m.start()]
    block = re.sub(r'(理|委|会|幹)[\s\u3000]+(事|員|長)', r'\1\2', block)
    out, role, buf = [], '委員', []
    single = ('委員長', '会長', '副委員長', '副会長', '会長代理', '委員長代理')
    def add(raw: str) -> None:
        name = norm_name(raw)
        if name and not NONMEMBER_RE.search(raw):  # 参考人・事務総長・専門員など委員でない出席者は名簿に入れない
            out.append((name, role))

    # 原本で「肥田 美代子」のように君が抜けた名前があるので、行の終わりで区切る（名前は行をまたがない）
    for line in re.split(r'[\r\n]+', block):
        named = False  # この行に君つきの名前があるか（行末の君なしは、名簿の行のときだけ名前とみなす。見出しを名前にしない）
        for tok in re.split(r'[\s\u3000]+', line):
            if not tok:
                continue
            while True:  # 「理事白坂亜紀君」のように役職語が頭に付くものを切る
                for r in sorted(ROLES, key=len, reverse=True):
                    if tok.startswith(r) and (tok == r or len(tok) > len(r) + 1):
                        role, buf, tok = r, [], tok[len(r):]
                        break
                else:
                    break
                if not tok:
                    break
            if not tok:
                continue
            if tok.endswith('君'):
                buf.append(tok[:-1])
                add(''.join(buf))
                buf, named = [], True
                if house == '衆議院' or role in single:
                    role = '委員'
            else:
                buf.append(tok)
        if buf:
            if named and 3 <= len(''.join(buf)) <= 7:
                add(''.join(buf))
            buf = []
    # 同じ会議で名前が複数回載る（役職つきと委員の欄など）ときは1人にして、高い役職を残す
    best: dict[str, str] = {}
    for name, r in out:
        if name not in best or ROLE_RANK.get(r, 9) < ROLE_RANK.get(best[name], 9):
            best[name] = r
    return list(best.items())


def agenda_text(header: str) -> str:
    i = header.find('本日の会議に付した案件')
    return header[i:] if i >= 0 else ''


CHAIR_RE = re.compile(r'^○[^　（]*(委員長|会長)(代理|代行)?(（[^）]*）)?')
# 法案本体の採決の結果。「撤回」は修正案の撤回許可などの手続なので含めない
RESULT_RE = re.compile(r'(修正議決すべきもの|可決すべきもの|否決すべきもの|承認すべきもの|不承認とすべきもの|議決すべきもの|継続審査|審査を終了)')
METHOD_RE = re.compile(r'(起立総員|起立多数|起立少数|異議なしと認め|異議ありませんか|全会一致|賛成多数|多数)')
_NAME = r'(?:^|(?<=[、。\s\u3000」）]))([^\s、。「」○（）()]{2,8}?)(?:君|さん)外([一二三四五六七八九十百〇\d]+)名'
PROPOSER_RE = re.compile(_NAME + r'から[^。]{0,80}?修正案')
PROPOSER2_RE = re.compile(_NAME + r'(?:提出|から提出|共同提出)[^。]{0,6}?(?:の|に係る)?修正案')
# 「○○法律案に対し、△△君外N名から、それぞれ修正案が提出されております」のように、法案ごとに提出者を挙げる宣告
PAIR_RE = re.compile(r'([^\s、。「」『』（）()○]{2,60}?(?:法律案|法案))に対し、?([^\s、。「」○（）()]{2,8}?)(?:君|さん)(?:外([一二三四五六七八九十百〇\d]+)名)?(?:から|ほか)')
# 採決の呼びかけ「△△君外N名提出の修正案について採決いたします」
VOTE_NAME_RE = re.compile(r'([^\s、。「」○（）()]{2,8}?)(?:君|さん)(?:外[一二三四五六七八九十百〇\d]+名)?(?:から|ほか)?(?:提出|共同提出)?の?修正案について採決')
SOLO_RE = re.compile(r'(?:^|(?<=[、。\s\u3000」）]))([^\s、。「」○（）()]{2,8}?)(?:君|さん)から[^。]{0,40}?修正案')
SOLO_PROPOSER_RE = re.compile(r'([^\s、。「」○（）()]{2,12}?)(?:君|さん)(?:から|ほか)[^。]{0,40}(?:修正案|附帯決議)')


def kanji_num(s: str) -> int:
    s = unicodedata.normalize('NFKC', s)
    if s.isdigit():
        return int(s)
    d = {'〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    if '百' in s or '十' in s:
        total, cur = 0, 0
        for ch in s:
            if ch in d:
                cur = d[ch]
            elif ch == '十':
                total += (cur or 1) * 10
                cur = 0
            elif ch == '百':
                total += (cur or 1) * 100
                cur = 0
        return total + cur
    return int(''.join(str(d.get(ch, 0)) for ch in s) or 0)


GOV_RE = re.compile(r'○[^\s　]{0,15}(?:国務大臣|大臣|副大臣|政務官|政務次官|長官)')


def speaker_kind(s: dict) -> str:
    sp = s['speech']
    if GOV_RE.match(sp):
        return 'other'  # 国家公安委員会委員長を兼ねる大臣など、役職に「委員長」を含む政府側の発言は委員長ではない
    if s.get('_chair') or CHAIR_RE.match(sp) or '委員長' in (s.get('speakerPosition') or '') or '会長' in (s.get('speakerPosition') or ''):
        return 'chair'
    return 'other'


def squeeze(t: str, n: int) -> str:
    t = re.sub(r'[ 　\t]+', ' ', t)
    t = re.sub(r'\n\s*', '\n', t).strip()
    return t[:n] + ('…' if len(t) > n else '')


def _flat(t: str) -> str:
    return t.replace('\u3000', '').replace(' ', '')


AGENDA_SENT_RE = re.compile(r'議題(?:と)?(?:いた|致)?し(?:ます|まして)')


def split_at_agenda(body: list[dict]) -> list[dict]:
    """委員長の1つの発言に、前の案件の結果と次の案件の議題の宣告が続くとき、宣告の文の手前で発言を分ける
    （前の案件の結果を次の案件の区間に混ぜず、次の案件の宣告より前の結果を元の案件に残すため）。"""
    out = []
    for r in body:
        t = r['speech']
        if speaker_kind(r) != 'chair' or '議題' not in t:
            out.append(r)
            continue
        cuts = []
        for m in AGENDA_SENT_RE.finditer(t):
            st = max(t.rfind('。', 0, m.start()), t.rfind('\n', 0, m.start())) + 1
            if st > 0 and t[:st].strip() and (not cuts or st > cuts[-1]):
                cuts.append(st)
        if not cuts:
            out.append(r)
            continue
        pos = [0, *cuts, len(t)]
        for a, b in zip(pos, pos[1:]):
            if t[a:b].strip():
                out.append({**r, 'speech': t[a:b], '_chair': True})
    return out



def chair_at(r: dict, attendance: list[tuple[str, str]]) -> str:
    """委員長提出の修正案を宣告した、その時点の委員長の名前。宣告した本人（代理でなければ）か、その会議の出席名簿の委員長。
    特定できなければ「委員長」のまま（未確認として保持し、人物には結びつけない）。"""
    pos = (r.get('speakerPosition') or '') + r['speech'][:40]
    if '代理' not in pos and '代行' not in pos:
        name = norm_name(r.get('speaker') or '')
        if name and '委員長' not in name:
            return name
    names = [n for n, role in attendance if role in ('委員長', '会長')]
    return names[0] if len(names) == 1 else '委員長'


def bill_segments(body: list[dict], short: str, n_items: int) -> list[tuple[int, int]]:
    """この法案が議題になっている発言の区間 [lo, hi) のリスト。ほかの案件が議題になるところで終わり、同じ会議で議題に戻れば別の区間になる。
    議題の宣告が見つからないとき、案件が1つだけの会議なら全体、複数なら区間なし（誤帰属を避ける）。"""
    decl = [i for i, r in enumerate(body) if speaker_kind(r) == 'chair' and re.search(r'議題(?:と)?(?:いた|す)', _flat(r['speech'])[:400])]
    if not any(short in _flat(body[i]['speech'])[:600] for i in decl):
        return [(0, len(body))] if n_items <= 1 else []
    segs, cur = [], None
    for i in decl:
        t = _flat(body[i]['speech'])
        if short in t[:600]:
            if cur is None:
                cur = i
        # 区間が終わるのは、別の案件の名前を挙げて議題にするとき。「本案及び修正案を一括して議題」のように名前のない宣告では終わらない
        elif cur is not None and re.search(r'法律案|法案|条約|議定書|協定|承認を求める|決議案|請願', t[:400]) \
                and '本案' not in (re.search(r'[^。\n]*議題[^。\n]*', t) or re.match('', '')).group(0):  # 「本案に対する附帯決議案を議題」は同じ法案の続き
            segs.append((cur, i))
            cur = None
    if cur is not None:
        segs.append((cur, len(body)))
    return segs


def mine(frag: str, short: str, loose: bool = True) -> bool:
    """法案名の断片 frag（題名が読点を含むと途中から切れる）がこの法案を指すか。"""
    f = re.sub(r'案$', '', frag)
    # 断片だけが挙がる場合は、断片が題名の後ろの部分に当たるときだけ：題名が「、」（loose のときは「及び」「並びに」も）で切れる、または
    # 題名が長くて名の抽出（最大40字）で前が切れるとき（「放送法…」は「有線テレビジョン放送法…」ではない）
    return short in frag or (len(f) >= 12 and short.endswith(f) and (len(frag) >= 39 or bool(re.search(r'(?:、|及び|並びに)$' if loose else r'、$', short[:len(short) - len(f)]))))


def names_other_bill(t: str, short: str, loose: bool = True) -> bool:
    """発言が法案名を挙げていて、その中にこの法案がない（別の法案の修正案）とき真。"""
    ns = re.findall(r'([^\s、。「」『』（）()○]{2,40}?(?:法律案|法案))', re.sub(r'\s+', '', t.replace('\u3000', '')))  # 法案名の途中の改行も除く
    ns = [n for n in ns if not re.fullmatch(r'(?:これより|次に|ただいま|なお)?(?:この|両|本|同|各|右の)(?:法律案|法案)', n)]  # 「この法律案」などの代名詞は別の法案ではない
    return bool(ns) and not any(mine(n, short, loose) for n in ns)



def analyze_meeting(m: dict, bill: dict) -> dict | None:
    """会議 m がこの法律の審議なら、抽出結果を返す。議題でなければ None。"""
    title = bill['題名']
    short = short_title(title)
    recs = m.get('speechRecord') or []
    if not recs:
        return None
    name_m = m.get('nameOfMeeting', '')
    if not name_m.endswith(('委員会', '審査会', '調査会')):
        return None  # 本会議などは対象外
    header = recs[0]['speech'] if str(recs[0].get('speechOrder')) == '0' else ''
    body = split_at_agenda([r for r in recs if str(r.get('speechOrder')) != '0'])
    ag = agenda_text(header)
    chair_speeches = [r for r in body if speaker_kind(r) == 'chair']
    declared = any(re.search(re.escape(short) + r'[^。]{0,120}?議題', r['speech'].replace('\u3000', '').replace(' ', '')) for r in chair_speeches[:30])
    in_header = short in ag.replace('\n', '').replace('　', '').replace(' ', '') or short in ag
    if not (in_header or declared):
        return None
    res = {'meeting': m, 'header': header, 'link': 'header' if in_header else 'agenda'}
    res['attendance'] = parse_attendance(header, m['nameOfHouse'])
    # 同じ会議で併せて議題になった案件数（本日の会議に付した案件のうち法案・条約・請願でない行は除く）
    items = [x.strip() for x in re.split(r'\n', ag)[1:] if re.search(r'(法律案|法案|条約|承認を求める|協定|議定書)', x)]
    res['n_items'] = len(items)
    res['n_speeches'] = len(body)
    res['speakers'] = len({r['speaker'] for r in body})
    res['witness'] = any(re.search(r'参考人', r['speech'][:60]) for r in body)
    # 採決（委員長の宣告）。この法案の議事の区間にあるものと、区間の外でもこの法案名に触れたものだけ（別の法案の結果を混ぜない）
    segs = bill_segments(body, short, res['n_items'])
    in_seg = lambda i: any(a <= i < b for a, b in segs)  # noqa: E731
    votes = []
    carry = None  # 直前の発言までに最後に挙げた案件がこの法案か（採決の呼びかけと結果が別の発言になる）
    for i, r in enumerate(body):
        if speaker_kind(r) != 'chair':
            continue
        t = r['speech']
        result, text, carry = own_result(t, short, bill.get('種別', '閣法'), carry)
        if result and ('採決' in t or '決しました' in t or '決定' in t) and (in_seg(i) or short in _flat(t)):
            votes.append({**r, '_own': (result, text)})
    res['votes'] = votes
    # 修正案：委員長が「○○君外N名から（提出）」「○○君外N名提出の修正案」「委員長提出の修正案」と宣告する発言を探す。
    # 法案ごとの議事の区間に限り、宣告ごとに提出者を1件ずつ取り、趣旨説明と採決結果は対応が確かなものだけ付ける（確かでなければ空のまま）。
    res['amend_calls'] = []
    chair_keys: set[str] = set()  # 委員長提出の修正案のキー（採決の宣告の「委員長提出」を実名のキーに結ぶ）
    announces = []  # (idx, 宣告の発言, [(筆頭, 外N名)], 動議か)
    for idx, hi in [(i, b) for a, b in segs for i in range(a, b)]:
        r = body[idx]
        t = r['speech']
        moved = bool(speaker_kind(r) != 'chair' and re.search(r'修正(?:の)?動議を提出|修正案を提出いたします|修正案を提出します', t[:500]))
        if not moved and (speaker_kind(r) != 'chair' or '修正案' not in t or not re.search(r'提出|趣旨', t)):
            continue
        if names_other_bill(t, short) and not any(mine(m.group(1), short) for m in PAIR_RE.finditer(_flat(t))):
            continue  # 別の法案の修正案
        if moved:  # 参議院の古い会議録：委員が「修正の動議を提出いたします」と自分で述べる
            props = [(r['speaker'], 0)]
        else:
            pairs = [(m.group(2), kanji_num(m.group(3)) if m.group(3) else 0) for m in PAIR_RE.finditer(_flat(t)) if mine(m.group(1), short)]
            ms = list(PROPOSER_RE.finditer(t)) or list(PROPOSER2_RE.finditer(t))
            props = pairs or [(m.group(1), kanji_num(m.group(2))) for m in ms]
            # 共同提出案と並ぶ単独提出案（「△△君外N名から修正案並びに□□君から修正案」）も取る
            have = {norm_name(p[0]) for p in props}
            # 宣告が複数の法案を挙げている（法案別の提出者を拾った／別の法案名がある）ときは、どの法案の単独提出者か分からないので足さない
            multi = bool(pairs) or any(not mine(n, short) for n in re.findall(r'([^\s、。「」『』（）()○]{2,40}?(?:法律案|法案))', _flat(t)))
            for sm in ([] if multi else SOLO_RE.finditer(re.sub(r'並びに|ならびに|及び|および|また、?', '、', t))):
                if norm_name(sm.group(1)) not in have:
                    props.append((sm.group(1), 0))
                    have.add(norm_name(sm.group(1)))
            if not props:
                if re.search(r'委員長(?:から|より)?(?:提出|修正案を提出)|委員長提出', t):
                    props = [(chair_at(r, res['attendance']), 0)]
                    chair_keys.add(norm_name(props[0][0]))
        if props:
            # 宣告に出てくる提出者の数が拾えた数より多いとき（長い会派名などで読み落とし）は、説明者を名前の証拠がなければ対応づけない
            n_said = len(re.findall(r'(?:君|さん)(?:外[一二三四五六七八九十百〇\d]+名)?(?:から|ほか)', t))
            announces.append((idx, r, props, moved, n_said > len(props), hi))
    # 委員長が筆頭提出者を宣告したあと、代表者が「修正の動議を提出いたします。その趣旨を御説明申し上げます」と述べる発言は、
    # 別の案の宣告ではなく同じ案の趣旨説明なので、案の境界にしない（説明の探索区間を切らない）。委員長が指名した人の動議に限る（独立した別案の動議は別の案のまま）
    def _named_explainer(b):  # 委員長が「趣旨の説明を求めます。○○君」と指名した人
        en = re.search(r'趣旨の説明を求めます。([^\s、。]{2,8}?)(?:君|さん)', _flat(b[1]['speech']))
        return norm_name(en.group(1)) if en else ''
    announces = [a for k, a in enumerate(announces) if not (
        a[3] and any((not b[3]) and len(b[2]) == 1 and 0 < a[0] - b[0] <= 7 and b[5] == a[5] and norm_name(b[2][0][0]) != norm_name(a[2][0][0])
                     and _named_explainer(b) == norm_name(a[2][0][0]) for b in announces[:k]))]
    calls: dict[str, dict] = {}
    for k, (idx, r, props, moved, ambiguous, hi) in enumerate(announces):
        nxt = next((a[0] for a in announces[k + 1:] if a[5] == hi and {norm_name(p[0]) for p in a[2]} != {norm_name(p[0]) for p in props}), hi)
        window = body[idx: min(idx + 7, nxt)]
        for main, more in props:
            key = norm_name(main)
            explainer = r if moved else None
            if not moved and len(props) == 1 and not ambiguous:
                en = re.search(r'趣旨の説明を求めます。([^\s、。]{2,8}?)(?:君|さん)', _flat(r['speech']))
                if en:
                    explainer = next((x for x in window[1:] if speaker_kind(x) != 'chair' and norm_name(x['speaker']) == norm_name(en.group(1)) and '修正' in x['speech']), None)
            if not moved and explainer is None:
                for r2 in window:
                    t2 = r2['speech']
                    if not (re.search(r'趣旨|要旨|概要', t2[:300]) and '修正' in t2[:400] and not re.search(r'採決|質疑は終局', t2[:120])
                            and ('御説明' in t2 or '説明申し上げ' in t2 or '説明いたし' in t2 or '要旨' in t2)):
                        continue
                    # 1つの宣告に複数の修正案があるときは、提出者本人（または文中に名前が出る人）の説明だけを対応づける
                    if (len(props) == 1 and not ambiguous) or norm_name(r2['speaker']) == key or key in norm_name(t2[:300]):
                        explainer = r2
                        break
            if moved and any(c0['exp'] is not None and norm_name(c0['exp']['speaker']) == key for c0 in calls.values()):
                continue  # 宣告の後に同じ人が趣旨を述べた同じ修正案
            c = calls.get(key)
            if c is None:
                c = calls[key] = {'rc': r, 'main': main, 'more': more, 'exp': explainer, 'outcome': ''}
            elif c['exp'] is None and explainer is not None:
                c['exp'] = explainer
    # 採決の結果：宣告した提出者（同じ発言か直前の採決の呼びかけ）に対応づける。特定できなければ空（採否不明）のまま
    buf = ''
    for i in [j for a, b in segs for j in range(a, b)]:
        if any(a == i for a, _ in segs):
            buf = ''
        if speaker_kind(body[i]) != 'chair':
            continue
        tt = body[i]['speech']
        while True:
            om = re.search(r'修正(?:案|の?動議)は(可決|否決|撤回)|修正(?:案|の?動議)(?:が|を)(可決|否決)|修正(?:案|の?動議)[^。]{0,40}?(可決|否決)されました', tt)
            if not om:
                buf = (buf + tt)[-1500:]
                break
            result = om.group(1) or om.group(2) or om.group(3)
            before = buf + tt[:om.start()]
            # 結果の直前に呼びかけられた提出者（最後に出た名前）。結果より後ろの名前は次の採決のもの
            named = [norm_name(m.group(1)) for m in list(PROPOSER_RE.finditer(before)) + list(PROPOSER2_RE.finditer(before)) + list(VOTE_NAME_RE.finditer(before))]
            pos = {}
            for m in list(PROPOSER_RE.finditer(before)) + list(PROPOSER2_RE.finditer(before)) + list(VOTE_NAME_RE.finditer(before)):
                pos[m.start()] = norm_name(m.group(1))
            if re.search(r'委員長(?:から|より)?(?:提出|修正案を提出)|委員長提出', before):
                pos[before.rfind('委員長')] = '委員長'
            last = pos[max(pos)] if pos else ''
            if last == '委員長':
                targets = [calls[k] for k in chair_keys if k in calls]
            elif last:
                targets = [calls[last]] if last in calls else []
            else:
                targets = list(calls.values()) if len(calls) == 1 else []
            for c in targets:
                if not c['outcome']:
                    c['outcome'] = result
            buf = ''
            tt = tt[om.end():]
    for c in calls.values():
        res['amend_calls'].append((c['rc'], (c['main'], c['more']), c['exp'], c['outcome']))
    # 附帯決議の趣旨説明・採決・政府の所信。この法案の議事の区間にあるものだけ（別の法案の決議を混ぜない）
    seg = [r for i, r in enumerate(body) if in_seg(i)]
    seg_chairs = [r for r in seg if speaker_kind(r) == 'chair']
    reso = []
    for r in seg:
        t = r['speech']
        if speaker_kind(r) == 'chair' or '附帯決議' not in t:
            continue
        if GOV_RE.match(t):
            continue  # 政府の対応表明（政府の所信）は決議の趣旨説明ではない
        if names_other_bill(t, short, loose=False):
            continue  # 全文が挙げる法案の中にこの法案が無い（別の法案への決議）ときは、一括審議でもこの法案の決議にしない
        if re.search(r'附帯決議(案)?(\s|　)*(\（案\）)?(につきまして|について|案を|案の|を付|の趣旨)|附帯決議(\（案\）|案)', t) and \
                re.search(r'提出者|提案者|案文|趣旨', t[:400]) and \
                re.search(r'右決議|決議する|朗読|(?:^|[\s　。])一[、\s　]', t):  # 案文がある発言だけ（過去の決議への質疑は除く）
            reso.append(r)
    res['resolutions'] = reso
    res['reso_decided'] = [r for r in seg_chairs if '附帯決議' in r['speech'] and re.search(r'付する|付すること|附すること|付すべし|異議なし|決しました|可決|決議とすることに決定', r['speech'])]
    res['reso_reply'] = [r for r in seg if speaker_kind(r) != 'chair' and '附帯決議' in r['speech'][:300] and re.search(r'尊重|所信|努力', r['speech']) and r not in reso
                         and re.match(r'○[^\s　]{0,15}(?:国務大臣|大臣|副大臣|政務官|政務次官|長官)', r['speech'])]  # 政府側の発言だけ
    # 決議ごとの対応づけ：次の決議の案文より前にある宣告と、その後の政府の所信だけ。確定できなければ空欄
    pos = {id(r): i for i, r in enumerate(seg)}
    pairs = []
    for k, r in enumerate(reso):
        lo = pos[id(r)]
        hi = min([pos[id(x)] for x in reso if pos[id(x)] > lo] or [len(seg)])
        decs = [d for d in res['reso_decided'] if lo < pos[id(d)] < hi]
        reps = [x for x in res['reso_reply'] if decs and pos[id(decs[0])] < pos[id(x)] < hi]
        pairs.append((r, decs, reps))
    res['reso_pairs'] = pairs
    return res


def load_meetings(raw: Path) -> dict[tuple, dict]:
    """保存した応答から、問い合わせキー → 会議のリストを返す（解析の入力）。"""
    out = {}
    for p in sorted(raw.glob('*.json.gz')):
        try:
            d = json.loads(gzip.decompress(p.read_bytes()))
        except Exception:  # noqa: BLE001
            continue
        resp = d.get('response', d)
        out[d.get('query', p.name)] = resp.get('meetingRecord') or []
    return out


def cmd_register(a) -> int:
    """登録前に取った応答（--raw にある控え）を、外部資料の保管庫に登録し直す。取得時刻は控えの更新時刻を使う。"""
    n = 0
    for p in sorted(Path(a.raw).glob('*.json.gz')):
        d = json.loads(gzip.decompress(p.read_bytes()))
        register_raw(p, d['query'])
        n += 1
    print(f'登録 {n}件', file=sys.stderr)
    return 0


def own_result(t: str, short: str, kind: str = '閣法', carry: bool | None = None) -> tuple[str | None, str | None, bool | None]:
    """委員長の1つの発言のうち、この法案本体の採決の結果 (結果の語, そこまでの抜粋元の文, 次の発言へ渡す「直前に挙げた案件はこの法案か」) を返す。
    直前に挙げた案件名（前の発言から続く場合は carry）がこの法案ならその結果。案件名がないときは、この法案の名が後ろに出ておらず、
    別の提出者の案を挙げていない結果だけ（前の案件の結果や、野党提出案の否決を混ぜない）。結果がなければ (None, None, carry)。"""
    sents = [x for x in re.split(r'(?<=。)|\n', _flat(t)) if x.strip()]
    last_named = (-1, carry) if carry is not None else None
    found = None
    for i, sent in enumerate(sents):
        ns = re.findall(r'([^\s、。「」『』（）()○]{2,40}?(?:法律案|法案|承認を求めるの件|条約|議定書))', sent)
        ns = [n for n in ns if not re.fullmatch(r'(?:これより|次に|ただいま|なお)?(?:この|両|本|同|各|右の)(?:法律案|法案)', n)]  # 「両法律案」などの代名詞は別の案件ではない
        if ns or short in sent:  # 題名に「条約」を含む法案は名前が途中で切れるので、法案名全体も照らす
            # 同じ題名でも提出者が違う案（内閣提出の電波法改正案と、野党提出の同名の案）は別の案件
            # （法案に対する修正案の提出者を述べる文は、本体の提出者ではない）
            alien = (re.search(r'君外[一二三四五六七八九十百〇\d]+名提出', sent) and '修正案' not in sent) if kind == '閣法' else '内閣提出' in sent
            last_named = (i, (short in sent or any(mine(n, short) for n in ns)) and not alien)
        m = RESULT_RE.search(sent)
        if not m or found:
            continue
        other = re.search(r'君外[一二三四五六七八九十百〇\d]+名提出', sent) if kind == '閣法' else '内閣提出' in sent
        if other or (last_named is None and any(short in x and re.search('採決|議題', x) and '附帯決議' not in x for x in sents[i + 1:])):
            continue
        if last_named is not None and not last_named[1]:
            continue
        start = last_named[0] if last_named and last_named[1] and last_named[0] >= 0 else 0
        found = ('修正議決すべきもの' if '修正議決すべきもの' in sent else m.group(1), ''.join(sents[start:i + 1]))
    carry_out = last_named[1] if last_named else carry
    return (*found, carry_out) if found else (None, None, carry_out)


def vote_fields(t: str, result: str) -> tuple[str, str]:
    """採決の宣告 t から、法案本体の結果 result の直前の採決の方法と、その採決の抜粋を取る。
    同じ発言の前にある修正案の採決の方法を拾わない。"""
    pos = t.find(result) if result and result in t else len(t)
    before = t[:pos]
    ms = list(METHOD_RE.finditer(before))
    st = before.rfind('採決')
    return (ms[-1].group(1) if ms else ''), squeeze(t[(st if st >= 0 else max(0, pos - 150)): min(len(t), pos + len(result) + 30)], 300)


def cmd_build(a) -> int:
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bills = list(csv.DictReader(open(ENACTED, encoding='utf-8')))
    by_query = defaultdict(list)
    for q, ms in load_meetings(raw).items():
        qd = dict(urllib.parse.parse_qsl(q))
        by_query[(qd.get('nameOfHouse'), qd.get('any'), qd.get('from'), qd.get('until'))].extend(ms)

    rows_m, rows_b, rows_a, rows_r = [], [], [], []
    for b in bills:
        bid = f"{b['種別']}-{b['提出回次']}-{b['番号']}"
        short = short_title(b['題名'])
        for house, cm, d_from, d_to in plan(b):
            seen, results = set(), []
            for m in by_query.get((house, short, d_from, d_to), []):
                if m['issueID'] in seen:
                    continue
                seen.add(m['issueID'])
                r = analyze_meeting(m, b)
                if r:
                    results.append(r)
            if not results:
                rows_b.append({'法律ID': bid, '題名': b['題名'], '院': house, '委員会': cm, '会議数': 0})
                continue
            results.sort(key=lambda r: r['meeting']['date'])
            att = defaultdict(lambda: {'n': 0, 'role': '委員'})
            for r in results:
                for name, role in r['attendance']:
                    x = att[name]
                    x['n'] += 1
                    if ROLE_RANK.get(role, 9) < ROLE_RANK.get(x['role'], 9):
                        x['role'] = role
                m = r['meeting']
                rows_m.append({'法律ID': bid, '院': house, '委員会': m['nameOfMeeting'], '日付': m['date'], '号': m['issue'],
                               '会議ID': m['issueID'], '議題の紐づけ': r['link'], '併せて議題の案件数': r['n_items'],
                               '発言数': r['n_speeches'], '発言者数': r['speakers'], '出席委員数': len(r['attendance']),
                               '参考人質疑': 'はい' if r['witness'] else ''})
            # 採決：法案名に触れた最後の宣告。なければ最後の宣告
            decisions = [(r['meeting'], v) for r in results for v in r['votes']]
            flat = lambda t: t.replace('\u3000', '').replace(' ', '')
            mine = [(m, v) for m, v in decisions if short in flat(v['speech']) or '本案' in v['speech']]
            pool = mine or decisions
            pick = None
            for m, v in pool:
                if v['_own'][0] == '修正議決すべきもの':
                    pick = (m, v)
            if pick is None and pool:
                pick = pool[-1]
            vote_text = method = result = ''
            vote_date = vote_url = ''
            if pick:
                m, v = pick
                result, t = v['_own']
                method, vote_text = vote_fields(t, result)
                vote_date, vote_url = m['date'], v.get('speechURL', '')
            chair = next((n for n, r in sorted(((n, x['role']) for n, x in att.items()), key=lambda z: ROLE_RANK.get(z[1], 9)) if r in ('委員長', '会長')), '')
            directors = sorted(n for n, x in att.items() if x['role'] == '理事')
            total = len(results)
            members = sorted(att.items(), key=lambda kv: (ROLE_RANK.get(kv[1]['role'], 9), -kv[1]['n'], kv[0]))
            n_amend = sum(len(r['amend_calls']) for r in results)
            rows_b.append({
                '法律ID': bid, '題名': b['題名'], '院': house, '委員会': cm, '会議数': total,
                '初回': results[0]['meeting']['date'], '最終': results[-1]['meeting']['date'],
                '参考人質疑の会議数': sum(1 for r in results if r['witness']),
                '委員長': chair, '理事': ';'.join(directors),
                '出席委員(出席数/会議数)': ';'.join(f"{n}({x['n']}/{total})" for n, x in members),
                '採決日': vote_date, '採決の結果': result, '採決の方法': method, '採決の宣告': vote_text, '採決の発言URL': vote_url,
                '修正案の宣告数': n_amend, '附帯決議': 'あり' if any(r['resolutions'] for r in results) else '',
            })
            bill_amends = []
            for r in results:
                m = r['meeting']
                for (rc, (main, n_more), ex, outcome) in r['amend_calls']:
                    bill_amends.append({
                        '法律ID': bid, '題名': b['題名'], '院': house, '委員会': m['nameOfMeeting'], '日付': m['date'],
                        '提出者(筆頭)': norm_name(main), '提出者の人数': n_more + 1, '修正案の結果': outcome,
                        '趣旨説明者': norm_name(ex['speaker']) if ex else '',
                        '宣告の抜粋': squeeze(rc['speech'], 240),
                        '趣旨説明の抜粋': squeeze(ex['speech'], 700) if ex else '',
                        '宣告のURL': rc.get('speechURL', ''), '趣旨説明のURL': ex.get('speechURL', '') if ex else '',
                    })
                for rs, decs, reps in r['reso_pairs']:
                    dec = ' / '.join(squeeze(x['speech'], 120) for x in decs[:2])
                    rep = ' / '.join(squeeze(x['speech'], 160) for x in reps[:1])
                    pm = PROPOSER_RE.findall(rs['speech'][:600]) or []
                    rows_r.append({
                        '法律ID': bid, '題名': b['題名'], '院': house, '委員会': m['nameOfMeeting'], '日付': m['date'],
                        '趣旨説明者': norm_name(rs['speaker']),
                        '本文': squeeze(rs['speech'], 3000), '決議の宣告': dec, '政府の所信': rep,
                        '発言URL': rs.get('speechURL', ''),
                    })
            merged = merge_amends(bill_amends)
            for x in merged:
                x['可否の根拠'] = '会議録の宣告' if x['修正案の結果'] else ''
            unknown = [x for x in merged if not x['修正案の結果']]
            if result == '修正議決すべきもの' and len(unknown) == 1 and not any(x['修正案の結果'] == '可決' for x in merged):
                unknown[0]['修正案の結果'], unknown[0]['可否の根拠'] = '可決', '法案が修正議決されたこと（修正案が1つだけ）から推定'
            rows_a.extend(merged)
    hb = ['法律ID', '題名', '院', '委員会', '会議数', '初回', '最終', '参考人質疑の会議数', '委員長', '理事', '出席委員(出席数/会議数)', '採決日', '採決の結果',
          '採決の方法', '採決の宣告', '採決の発言URL', '修正案の宣告数', '附帯決議']
    for h in ('衆議院', '参議院'):
        write(out / f'bill_committee_{h}.csv', hb, [r for r in rows_b if r['院'] == h])
    write(out / 'meetings.csv', ['法律ID', '院', '委員会', '日付', '号', '会議ID', '議題の紐づけ', '併せて議題の案件数', '発言数', '発言者数', '出席委員数', '参考人質疑'], rows_m)
    write(out / 'amendments.csv', ['法律ID', '題名', '院', '委員会', '日付', '提出者(筆頭)', '提出者の人数', '修正案の結果', '可否の根拠', '趣旨説明者', '宣告の抜粋', '趣旨説明の抜粋', '宣告のURL', '趣旨説明のURL'], rows_a)
    merged_r: dict[str, dict] = {}
    for r in rows_r:  # 一括して議題になった法律は同じ発言を指すので、1行にして法律IDを並べる
        k = r['発言URL']
        if k in merged_r:
            merged_r[k]['法律ID'] += ';' + r['法律ID']
            merged_r[k]['題名'] += ';' + r['題名']
        else:
            merged_r[k] = dict(r)
    rows_r = list(merged_r.values())
    for h in ('衆議院', '参議院'):
        write(out / f'resolutions_{h}.csv', ['法律ID', '題名', '院', '委員会', '日付', '趣旨説明者', '本文', '決議の宣告', '政府の所信', '発言URL'], [r for r in rows_r if r['院'] == h])
    c = Counter(bool(int(r.get('会議数') or 0)) for r in rows_b)
    print(f'bill-house 行 {len(rows_b)}（会議あり {c[True]} / なし {c[False]}）、会議 {len(rows_m)}、修正案 {len(rows_a)}、附帯決議 {len(rows_r)}', file=sys.stderr)
    return 0


def merge_amends(items: list[dict]) -> list[dict]:
    """同じ法律・院・日・委員会の修正案の宣告と趣旨説明を、提出者（筆頭）・趣旨説明者の一致で1件にまとめる。"""
    groups: list[list[dict]] = []
    for it in items:
        names = {it['提出者(筆頭)'], it['趣旨説明者']} - {''}
        for g in groups:
            gn = set().union(*({x['提出者(筆頭)'], x['趣旨説明者']} - {''} for x in g))
            # 名前は対応づけの補助。同じ日の同じ委員会のものだけ同じ案とみなす（翌日に出し直した別案を潰さない）
            if names & gn and g[0]['日付'] == it['日付'] and g[0]['委員会'] == it['委員会']:
                g.append(it)
                break
        else:
            groups.append([it])
    out = []
    for g in groups:
        best = max(g, key=lambda x: (bool(x['趣旨説明の抜粋']), len(x['趣旨説明の抜粋'])))
        row = dict(g[0])
        row['趣旨説明者'] = best['趣旨説明者']
        row['趣旨説明の抜粋'] = best['趣旨説明の抜粋']
        row['趣旨説明のURL'] = best['趣旨説明のURL']
        row['修正案の結果'] = next((x['修正案の結果'] for x in g if x['修正案の結果']), '')
        if re.search(r'及び|並びに|(?:君|さん)$|(?:君|さん)外|外[一二三四五六七八九十百〇\d]+名|ほか', row['提出者(筆頭)']):  # 宣告の読み違い。趣旨説明者がいればその人、いなければ特定できず
            row['提出者(筆頭)'] = row['趣旨説明者']
        if row['提出者(筆頭)'] == '委員長':
            row['提出者の人数'] = 1  # 提出時点の委員長を特定できなかったもの。名前は付けない
        out.append(row)
    return out


def write(path: Path, header: list[str], rows: list[dict]):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, header, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch')
    f.add_argument('--raw', required=True)
    f.add_argument('--workers', type=int, default=3)
    f.add_argument('--interval', type=float, default=INTERVAL, help='全体のリクエスト間隔（秒）')
    f.add_argument('--limit', type=int, default=0)
    f.add_argument('--ids', nargs='*')
    f.set_defaults(fn=cmd_fetch)
    g = sub.add_parser('register')
    g.add_argument('--raw', required=True)
    g.set_defaults(fn=cmd_register)
    b = sub.add_parser('build')
    b.add_argument('--raw', required=True)
    b.add_argument('--out', required=True)
    b.set_defaults(fn=cmd_build)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == '__main__':
    raise SystemExit(main())
