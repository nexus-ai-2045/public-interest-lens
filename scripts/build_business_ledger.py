"""経済界の帳簿：要望（規制改革ホットライン）→ 該当法令 → 要望のあとに成立した当該法令の改正法 → その法律の結果。

点数・順位には入れない別の帳簿（ADR 0014 決定9〜11 の続き）。新しく取得しない。入力は既存の2つだけ：
- 規制改革ホットラインの提案（data/acquired/blocking-actors/1_regulatory-requests/hotline*.csv、原本照合済みの行だけ）
- 全法律の結果（data/derived/all-laws-v1/outcomes.csv）と成立法の一覧（data/acquired/bill-census-full/enacted.csv）

読み方の約束（認知の罠を避けるため、出力の「確かさ」列に常に書く）：
- 「要望のあとに同じ法令の改正法が成立した」は時間順の対応であって、要望が改正を起こした証拠ではない。条文と要望の中身の照合はしていない。
- 結ぶのは要望の受付から3年以内に公布された改正法だけ（WINDOW_DAYS）。
- 法令名の取り出しは 該当法令 欄の文字列から機械で行い、改正法の題名に法令名が含まれるものを結ぶ。法令名のない行（政省令・通知・「記載なし」）は結ばない。
- 提案主体は団体名があるものだけ名前を出し、「個人」「民間企業」「民間団体」は区分でまとめる（個人は名指ししない）。団体名のそろえは scripts/org_names.py の org_key()。

使い方（リポジトリのルートで）: python3 scripts/build_business_ledger.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_org_ledger import org_name  # noqa: E402
from scripts.org_names import org_key  # noqa: E402

REQ_DIR = ROOT / 'data/acquired/blocking-actors/1_regulatory-requests'
REQ_FILES = ('hotline.csv', 'hotline-h26-h27.csv', 'hotline-h29-later.csv')
ENACTED = ROOT / 'data/acquired/bill-census-full/enacted.csv'
OUTCOMES = ROOT / 'data/derived/all-laws-v1/outcomes.csv'
LOBBY_DIR = ROOT / 'data/acquired/lobbying'
OUT_DIR = ROOT / 'data/derived/business-ledger-v1'
VERIFIED = '原本照合済み'

# 提案主体の区分（名前のパターン順に最初に当たったもの）。経済団体は経済界の総合団体・地域の経済団体。
ECONOMIC_BODIES = re.compile(r'経済団体連合会|経団連|商工会議所|経済同友会|新経済連盟|経済連合会|中小企業団体中央会|商工会連合会')
ANONYMOUS = {'個人': '個人', '民間企業': '民間企業', '民間団体': '民間団体'}
LOCAL_GOV = re.compile(r'(都|道|府|県|市|町|村|特別区)$|知事|市長|町長|村長|地方自治体|自治体')
INDUSTRY = re.compile(r'協会|連盟|組合|連合|工業会|懇話会|協議会|連合会|振興会|団体|学会|会議所|センター|機構|公社|公益')

# 法令の通称。正式名称の一部を略したもので、改正法の題名には正式名称で出る。
ALIASES = {
    '独占禁止法': '私的独占の禁止及び公正取引の確保に関する法律',
    '廃棄物処理法': '廃棄物の処理及び清掃に関する法律',
    '景品表示法': '不当景品類及び不当表示防止法',
    '公益認定法': '公益社団法人及び公益財団法人の認定等に関する法律',
    '薬事法': '医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律',
}
# 改称などで同じ法律が題名に別の名前で出るもの（検索に使う名前の組）。薬事法は2014-11-25 に現在の名前へ改称。
EQUIV = {
    '医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律': ('医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律', '薬事法'),
}
# 「、」で区切られる名前の後半だけを拾ってしまうもの（取り出しの規則では「、」を名前に含めない）。
TRUNCATED = {'有効性及び安全性の確保等に関する法律': '医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律'}
STATUTE = re.compile(r'([^\s、，,・（）()第]{2,40}?(?:法律|法))(?=第|\d|施行|、|・|$|等|\s|（|同|及び|の)')
NOT_STATUTE_SUFFIX = ('施行令', '施行規則', '省令', '政令', '告示', '通知', '指針', '要綱')
# 要望から改正法の公布までを結ぶ窓。規制改革実施計画の実施期限が通常1〜3年なので3年（1,096日）。これより離れた改正は別の動機とみなして結ばない。
WINDOW_DAYS = 1096
ERA = {'平成': 1988, '令和': 2018, '昭和': 1925}


def read_requests() -> list[dict[str, str]]:
    rows = []
    for name in REQ_FILES:
        with (REQ_DIR / name).open(encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                if r.get('確度', '').startswith(VERIFIED):
                    rows.append(r)
    return rows


def read_hearings() -> list[dict[str, str]]:
    """審議会・検討会で名前のある業界団体が述べた立場（ロビー活動の一経路）を、要望と同じ列に直す。"""
    rows = []
    for path in sorted((ROOT / 'data/acquired/blocking-actors/2_shingikai').glob('*.csv')):
        with path.open(encoding='utf-8', newline='') as f:
            for i, r in enumerate(csv.DictReader(f), 2):
                if r.get('確度', '').startswith(VERIFIED) and r['発言者の区分'] == '業界団体':
                    rows.append({'受付番号': f'審議会-{path.stem}-{i}', '受付日': r['開催日'], '提案主体': org_name(r['発言者の所属・肩書']),
                                 '提案事項': r['要旨'], '所管省庁': r['所管省庁'], '対応分類': f"団体の立場：{r['立場']}", '該当法令': r['関連法令'],
                                 '関連技術': r['関連技術'], '出典URL': r['出典URL'], '経路': '審議会・検討会での発言', '取込の確度': '原本照合済み（機械の照合とAI2系統が一致）'})
    return rows


def read_lobbying() -> list[dict[str, str]]:
    """経団連・商工会議所などの提言・要望書・陳情（data/acquired/lobbying/、scripts/verify_lobbying_quotes.py で引用と法律名が出典の本文にあると機械で確かめ、さらに独立した AI 2系統が提案主体・日付・求めた内容まで出典と一致と判定した行だけ。AGENTS.md の2系統の一致）。"""
    rows = []
    for path in sorted(LOBBY_DIR.glob('*.csv')):
        with path.open(encoding='utf-8', newline='') as f:
            for i, r in enumerate(csv.DictReader(f), 2):
                if r.get('確度') == '原文照合済み（機械）' and r.get('AI2系統') == '一致':
                    rows.append({'受付番号': f'提言-{path.stem}-{i}', '受付日': r['日付'], '提案主体': r['提案主体'],
                                 '提案事項': f"{r['題名']}：{r['求めた内容']}", '所管省庁': r.get('宛先', ''), '対応分類': '（回答の記録なし）',
                                 '該当法令': r['該当法令'], '関連技術': '', '出典URL': r['出典URL'], '経路': r['経路'], '取込の確度': '原文照合済み（機械とAI2系統が一致）'})
    return rows


def request_date(number: str, received: str) -> tuple[str, str]:
    """(ISO 日付, 根拠)。受付番号 YYMMDDnnn（平成）が日付になればそれを使い、無ければ受付日の文字列を読む。取れなければ空。"""
    m = re.match(r'^(\d{2})(\d{2})(\d{2})\d{3}$', number or '')
    if m:
        try:
            return date(1988 + int(m[1]), int(m[2]), int(m[3])).isoformat(), '受付番号'
        except ValueError:
            pass
    iso = re.match(r'^(\d{4})-(\d{2})-(\d{2})', received or '')
    if iso:
        return iso.group(0), '受付日'
    wa = re.match(r'^(平成|令和)(\d+)年(\d+)月(\d+)日', received or '')
    if wa:
        try:
            return date(ERA[wa[1]] + int(wa[2]), int(wa[3]), int(wa[4])).isoformat(), '受付日'
        except ValueError:
            pass
    return '', ''


def parse_wareki(text: str) -> str:
    m = re.match(r'\s*(平成|令和|昭和)\s*(元|\d+)年\s*(\d+)月\s*(\d+)日', text or '')
    if not m:
        return ''
    year = 1 if m[2] == '元' else int(m[2])
    try:
        return date(ERA[m[1]] + year, int(m[3]), int(m[4])).isoformat()
    except ValueError:
        return ''


def proposer_kind(name: str) -> tuple[str, str]:
    """(表示名, 区分)。匿名の区分は名前を出さない。"""
    name = (name or '').strip()
    if name in ANONYMOUS:
        return f'（{name}・名前は出さない）', ANONYMOUS[name]
    if not name or name.startswith('（団体名の記載なし'):
        return '（提案主体の記載なし）', '不明'
    if ECONOMIC_BODIES.search(name):
        return name, '経済団体'
    if INDUSTRY.search(name):
        return name, '業界団体'
    if LOCAL_GOV.search(name):
        return name, '自治体'
    return name, 'その他'


def statutes(text: str) -> list[str]:
    """該当法令 欄から、法律の名前（政省令・通知は除く）を重複なく取り出す。通称は正式名称へ。"""
    out: list[str] = []
    text = text or ''
    for m in STATUTE.finditer(text):
        name = m.group(1)
        if text[m.end():].startswith(('施行令', '施行規則', '施行細則')) or name.endswith(NOT_STATUTE_SUFFIX) or name in ('同法', '本法', '当該法'):
            continue
        name = ALIASES.get(TRUNCATED.get(name, name), TRUNCATED.get(name, name))
        if name not in out:
            out.append(name)
    return out


def title_has(title: str, law: str) -> bool:
    """改正法の題名に法令名が、別の法令名の一部としてではなく現れるか（前が漢字・ひらがなの続きなら別の法令）。"""
    for m in re.finditer(re.escape(law), title):
        before = title[m.start() - 1] if m.start() else ''
        if not before or before in '、・「（(' or title[:m.start()].endswith(('及び', '並びに')):
            return True
    return False


def load_bills() -> list[dict[str, str]]:
    outcomes = {}
    with OUTCOMES.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            outcomes[r['id']] = r
    bills = []
    with ENACTED.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if '改正' not in r['題名']:
                continue
            bill_id = f"{r['種別']}-{r['提出回次']}-{r['番号']}"
            o = outcomes.get(bill_id, {})
            bills.append({'id': bill_id, '題名': r['題名'], '公布日': parse_wareki(r['公布日']), '結果': o.get('結果', '（結果の表に無い）'),
                          '額の表示': o.get('損失または便益の額', '') or '', '公開可否': o.get('公開可否', ''), '確かさ': o.get('確かさ', ''),
                          '出典URL': r['経過URL']})
    return bills


def build() -> dict[str, int]:
    bills = load_bills()
    requests, chain = [], []
    for r in [{**x, '経路': '規制改革ホットライン', '取込の確度': '原本照合済み（機械の照合とAI2系統が一致）'} for x in read_requests()] + read_hearings() + read_lobbying():
        d, basis = request_date(r['受付番号'], r['受付日'])
        shown, kind = proposer_kind(r['提案主体'])
        laws = statutes(r['該当法令'])
        rid = r['受付番号']
        matched = []
        for law in laws:
            for b in bills:
                if any(title_has(b['題名'], alt) for alt in EQUIV.get(law, (law,))) and b['公布日'] and d and 0 < (date.fromisoformat(b['公布日']) - date.fromisoformat(d)).days <= WINDOW_DAYS:
                    matched.append((law, b))
        requests.append({
            '要望ID': rid, '経路': r['経路'], '取込の確度': r['取込の確度'], '受付日': d, '日付の根拠': basis, '提案主体': shown, '区分': kind, '提案事項': r['提案事項'],
            '所管省庁': r['所管省庁'], '省庁の回答': r['対応分類'], '該当法令': r['該当法令'], '取り出した法律': '、'.join(laws),
            '関連技術': r['関連技術'], '要望後3年以内の改正法': len({b['id'] for _, b in matched}), '出典URL': r['出典URL'],
        })
        for law, b in matched:
            chain.append({
                '要望ID': rid, '経路': r['経路'], '提案主体': shown, '区分': kind, '法律名': law, '改正法ID': b['id'], '改正法題名': b['題名'],
                '公布日': b['公布日'], '要望から公布までの日数': (date.fromisoformat(b['公布日']) - date.fromisoformat(d)).days,
                '改正法の結果': b['結果'], '額の表示': b['額の表示'], '公開可否': b['公開可否'], '結果の確かさ': b['確かさ'],
                '対応の確かさ': '低（法令名の一致と時間順だけ。条文と要望の中身は未照合。要望が原因とは読まない）',
                '要望の出典URL': r['出典URL'], '改正法の経過URL': b['出典URL'],
            })
    chain.sort(key=lambda c: (c['要望ID'], c['改正法ID'], c['法律名']))
    requests.sort(key=lambda c: (c['受付日'] or '9999', c['要望ID'], c['提案事項']))

    by_org: dict[tuple[str, str], dict] = defaultdict(lambda: {'要望': 0, '対応不可': 0, '改正法あり': 0, '額あり': 0, 'laws': set(), 'bills': set(), 'urls': set()})
    chain_by_req = defaultdict(list)
    for c in chain:
        chain_by_req[c['要望ID']].append(c)
    for q in requests:
        key = (org_key(q['提案主体']) or q['提案主体'], q['区分'])
        t = by_org[key]
        t.setdefault('name', q['提案主体'])
        t['要望'] += 1
        t['対応不可'] += q['省庁の回答'].startswith('対応不可')
        t['改正法あり'] += q['要望後3年以内の改正法'] > 0
        for c in chain_by_req.get(q['要望ID'], []):
            t['bills'].add(c['改正法ID'])
            t['額あり'] += c['改正法の結果'] == '額あり'
        t['urls'].add(q['出典URL'])
    org_rows = [{'提案主体': t['name'], '区分': k[1], '要望の件数': t['要望'], '省庁が対応不可': t['対応不可'], '3年以内に改正法が成立した要望': t['改正法あり'],
                 '結ばれた改正法の本数': len(t['bills']), '出典URL': ' '.join(sorted(t['urls']))}
                for k, t in by_org.items()]
    org_rows.sort(key=lambda r: (-r['要望の件数'], r['提案主体']))

    write(OUT_DIR / 'requests.csv', requests)
    write(OUT_DIR / 'chain.csv', chain)
    write(OUT_DIR / 'by-proposer.csv', org_rows)
    summary = {
        '要望': len(requests), '法律名を取れた要望': sum(1 for q in requests if q['取り出した法律']), '日付を取れた要望': sum(1 for q in requests if q['受付日']),
        '3年以内に改正法が成立した要望': sum(1 for q in requests if q['要望後3年以内の改正法']), '対応の行': len(chain),
        '結ばれた改正法': len({c['改正法ID'] for c in chain}), '額ありの改正法': len({c['改正法ID'] for c in chain if c['改正法の結果'] == '額あり'}),
        '提案主体': len(org_rows),
    }
    (OUT_DIR / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return summary


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False))
