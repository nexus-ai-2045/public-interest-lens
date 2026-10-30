"""閣法を所管の省庁に結ぶ（霞が関の帳簿の1本目。案はプロジェクトの共有フォルダ analysis/霞が関の力関係_案_2026-10-24.md）。

閣法の原案は所管の省庁が書き、国会では所管の大臣が提案理由を説明する。説明した人の肩書（会議録の発言者の肩書）から省庁を決める。
- fetch: 提案理由の説明（data/acquired/bill-speeches/speeches.csv の説明のURL）ごとに、国会会議録 API で発言者の肩書を取る。
  原本の JSON は .local/ministry/positions/ に置き、解析の前に外部資料として .local/external-materials/ministry-positions/ に登録する
  （AGENTS.md。中身の確かさは unverified から）。表 data/acquired/bill-speeches/speaker-positions.csv に URL・取得時刻・外部資料ID と一緒に書く。
- build: 肩書から所管の省庁を決め、data/derived/ministry-v1/cabinet-bills.csv を書く（通信しない）。
  肩書が「国務大臣」だけのときは、内閣の名簿（data/acquired/office-holders/cabinet.csv）のその日の役職で決める。
  省庁の名前は、当時の名前と、2001年の再編後の名前（今の名前）の両方を持つ。決まらない法律は「決まらない」と理由を書く（推定で埋めない）。

使い方（リポジトリのルートで）:
  python3 scripts/build_ministry_bills.py fetch   # 無い肩書だけ取る
  python3 scripts/build_ministry_bills.py build
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from register_external_material import register_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEECHES = ROOT / 'data/acquired/bill-speeches/speeches.csv'
CABINET = ROOT / 'data/acquired/office-holders/cabinet.csv'
POSITIONS = ROOT / 'data/acquired/bill-speeches/speaker-positions.csv'
RAW = ROOT / '.local/ministry/positions'
OUT = ROOT / 'data/derived/ministry-v1/cabinet-bills.csv'
API = 'https://kokkai.ndl.go.jp/api/speech'
STORAGE = ROOT / '.local/external-materials'
TASK_ID = 'ministry-positions'
UA = 'public-interest-lens ministry (research; GitHub nexus-ai-2045/public-interest-lens)'

# 肩書の先頭の役職 → (当時の省庁, 今の省庁)。上から順に当てる。今の省庁は2001年1月の再編後の名前（防衛庁は2007年に防衛省）。
ROLES: list[tuple[str, str, str]] = [
    ('法務大臣', '法務省', '法務省'), ('外務大臣', '外務省', '外務省'), ('大蔵大臣', '大蔵省', '財務省'), ('財務大臣', '財務省', '財務省'),
    ('文部科学大臣', '文部科学省', '文部科学省'), ('文部大臣', '文部省', '文部科学省'), ('科学技術庁長官', '科学技術庁', '文部科学省'),
    ('厚生労働大臣', '厚生労働省', '厚生労働省'), ('厚生大臣', '厚生省', '厚生労働省'), ('労働大臣', '労働省', '厚生労働省'),
    ('農林水産大臣', '農林水産省', '農林水産省'), ('経済産業大臣', '経済産業省', '経済産業省'), ('通商産業大臣', '通商産業省', '経済産業省'),
    ('国土交通大臣', '国土交通省', '国土交通省'), ('運輸大臣', '運輸省', '国土交通省'), ('建設大臣', '建設省', '国土交通省'),
    ('北海道開発庁長官', '北海道開発庁', '国土交通省'), ('国土庁長官', '国土庁', '国土交通省'),
    ('環境大臣', '環境省', '環境省'), ('環境庁長官', '環境庁', '環境省'), ('防衛大臣', '防衛省', '防衛省'), ('防衛庁長官', '防衛庁', '防衛省'),
    ('総務大臣', '総務省', '総務省'), ('自治大臣', '自治省', '総務省'), ('郵政大臣', '郵政省', '総務省'), ('総務庁長官', '総務庁', '総務省'),
    ('国家公安委員会委員長', '国家公安委員会（警察庁）', '国家公安委員会（警察庁）'),
    ('復興大臣', '復興庁', '復興庁'), ('デジタル大臣', 'デジタル庁', 'デジタル庁'),
    ('金融再生委員会委員長', '金融再生委員会', '金融庁'), ('金融担当', '金融庁', '金融庁'),
    ('経済企画庁長官', '経済企画庁', '内閣府'), ('沖縄開発庁長官', '沖縄開発庁', '内閣府'),
    ('内閣官房長官', '内閣官房', '内閣官房'), ('内閣府特命担当大臣', '内閣府', '内閣府'), ('金融庁', '金融庁', '金融庁'),
    # 内閣府・内閣官房に置かれた担当大臣（特命担当の名前が付かない時期の呼び方）。行政改革は内閣官房の推進本部が所管。
    ('行政改革担当', '内閣官房', '内閣官房'), ('沖縄及び北方対策担当', '内閣府', '内閣府'), ('科学技術政策担当', '内閣府', '内閣府'),
    ('防災担当', '内閣府', '内閣府'), ('構造改革特区担当', '内閣府', '内閣府'),
]


# 財務大臣と金融担当を兼ねた大臣が説明した法律は、題名で金融庁の所管かどうかを選ぶ（国際機関への加盟・政府系の銀行の法律は財務省）。
FSA_BILL = re.compile(r'金融|保険業|銀行法|資金決済|信託業|公認会計士|振替|事業性融資')
MOF_BILL = re.compile(r'加盟|政策投資銀行|国際協力銀行|外国為替')


def ministry_of(title: str, bill: str = '') -> tuple[str, str] | None:
    """肩書（「国務大臣（内閣府特命担当大臣（金融））」なども）から省庁を決める。先頭に近い役職を優先する。
    兼務の肩書で財務大臣と金融担当の両方があるときだけ、法律の題名（bill）で選ぶ。"""
    t = re.sub(r'[\s　]', '', title)
    # 副大臣・政務次官・大臣政務官が説明したときは、その大臣の省庁（「厚生労働副大臣」→「厚生労働大臣」）。
    t = re.sub(r'(副大臣|政務次官|大臣政務官)', '大臣', t)
    hits = [(t.find(role), then, now) for role, then, now in ROLES if role in t]
    # 「内閣府特命担当大臣（金融…）」は内閣府でなく金融庁（同じ位置の内閣府より先に取る）。
    fsa = re.search(r'内閣府特命担当大臣（[^）]*金融', t)
    if fsa:
        hits.append((fsa.start() - 0.5, '金融庁', '金融庁'))
    if not hits:
        return None
    _, then, now = min(hits)
    if now == '財務省' and any(h[2] == '金融庁' for h in hits) and FSA_BILL.search(bill) and not MOF_BILL.search(bill):
        return ('金融庁', '金融庁')
    return (then, now)


def speech_ref(url: str) -> tuple[str, str] | None:
    m = re.search(r'/txt/([0-9A-Z]+)/(\d+)', url)
    return (m.group(1), m.group(2)) if m else None


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


POS_HEADER = ['法律ID', '説明のURL', '発言者', '肩書', 'API_URL', '取得日時', '外部資料ID']


def register(raw: Path, url: str, fetched_at: str) -> str:
    return register_once(input_path=raw, source_url=url, task_id=TASK_ID, title='国会会議録検索システム API の応答（閣法の提案理由の説明）',
                         purpose='閣法の所管の省庁を決める（説明した大臣の肩書）', storage_root=STORAGE, observed_at=fetched_at)


def fetch(pause: float) -> None:
    done = {r['説明のURL']: r for r in read(POSITIONS)} if POSITIONS.exists() else {}
    RAW.mkdir(parents=True, exist_ok=True)
    # 先に取った原本で、まだ外部資料に登録していないものを登録する（取得時刻は表の記録）。
    for r in done.values():
        ref = speech_ref(r['説明のURL'])
        raw = RAW / f'{ref[0]}-{ref[1]}.json' if ref else None
        if not r.get('外部資料ID') and raw and raw.exists():
            r['外部資料ID'] = register(raw, r['API_URL'], r['取得日時'])
    todo = [r for r in read(SPEECHES) if r['id'].startswith('閣法') and r['説明のURL'] and r['説明のURL'] not in done]
    for i, r in enumerate(todo, 1):
        ref = speech_ref(r['説明のURL'])
        if not ref:
            continue
        url = f'{API}?' + urllib.parse.urlencode({'issueID': ref[0], 'speechNumber': ref[1], 'recordPacking': 'json'})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30) as res:
                body = res.read()
        except OSError as e:
            print(f'取れない {r["id"]}: {e}', file=sys.stderr)
            continue
        fetched_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        raw = RAW / f'{ref[0]}-{ref[1]}.json'
        raw.write_bytes(body)
        material = register(raw, url, fetched_at)  # 解析の前に登録する
        rec = (json.loads(body).get('speechRecord') or [{}])[0]
        done[r['説明のURL']] = {'法律ID': r['id'], '説明のURL': r['説明のURL'], '発言者': rec.get('speaker') or '', '肩書': rec.get('speakerPosition') or '',
                              'API_URL': url, '取得日時': fetched_at, '外部資料ID': material}
        if i % 100 == 0:
            write(POSITIONS, POS_HEADER, sorted(done.values(), key=lambda x: x['説明のURL']))
            print(f'{i}/{len(todo)}', file=sys.stderr)
        time.sleep(pause)
    write(POSITIONS, POS_HEADER, sorted(done.values(), key=lambda x: x['説明のURL']))


OUT_HEADER = ['法律ID', '題名', '説明者', '説明の日付', '肩書', '所管_当時', '所管_今', '決め方', '出典URL']


def build() -> dict[str, int]:
    if not SPEECHES.exists():
        # speeches.csv は Git に入っていない取得物（fetch_bill_speeches.py）。無いときは既存の生成物のまま続ける。
        if not OUT.exists():
            raise SystemExit(f'{SPEECHES} も {OUT} も無い：先に scripts/fetch_bill_speeches.py を回す')
        print(f'警告：{SPEECHES} が無いので作り直さず、既存の {OUT} を使う', file=sys.stderr)
        return {'会議録の肩書': 0, '内閣の名簿': 0, '決まらない': 0}
    pos = {r['説明のURL']: r for r in read(POSITIONS)} if POSITIONS.exists() else {}
    norm = lambda s: re.sub(r'[\s　]', '', s)  # noqa: E731
    cabinet = read(CABINET)
    rows, counts = [], {'会議録の肩書': 0, '内閣の名簿': 0, '決まらない': 0}
    for r in read(SPEECHES):
        if not r['id'].startswith('閣法'):
            continue
        p = pos.get(r['説明のURL'], {})
        title, how, found = p.get('肩書', ''), '', None
        if title:
            found = ministry_of(title, r['題名'])
            how = '会議録の肩書' if found else ''
        if not found and r['説明の発言者']:
            day, name = r['説明の日付'], norm(r['説明の発言者'])
            held = [c['役職'] + c['所管'] for c in cabinet if norm(c['氏名']) == name and c['就任日_西暦'] <= day and (not c['退任日_西暦'] or day <= c['退任日_西暦'])]
            picks = {m for m in (ministry_of(h, r['題名']) for h in held) if m}
            if len(picks) == 1:
                found, how = picks.pop(), '内閣の名簿'
                title = title or '／'.join(held)
        if not found:
            how = '決まらない：' + ('説明の記録が無い' if not r['説明のURL'] else '肩書から省庁を決められない' if title else '肩書が取れていない')
        counts[how.split('：')[0]] += 1
        rows.append({'法律ID': r['id'], '題名': r['題名'], '説明者': r['説明の発言者'], '説明の日付': r['説明の日付'], '肩書': title,
                     '所管_当時': found[0] if found else '', '所管_今': found[1] if found else '', '決め方': how, '出典URL': r['説明のURL']})
    write(OUT, OUT_HEADER, rows)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'build'])
    ap.add_argument('--pause', type=float, default=0.3)
    a = ap.parse_args()
    if a.cmd == 'fetch':
        fetch(a.pause)
    print(json.dumps(build(), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
