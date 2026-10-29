"""税制改正の「増減収見込額（平年度）」を、財務省の税制改正の大綱から取る（法律へ配分しない年度・税目の政府予測）。

令和6年度分からは財務省のサイトに、それより前は国立国会図書館インターネット資料収集保存事業（WARP）の保存版にある。
WARP は混み合うと 403 の案内ページを返すので、PDF が返るまで間をおいて取り直す。
取った PDF は外部資料として登録し（AGENTS.md）、pdftotext で読んで「（内国税関係）による増減収見込額」の表から
税目ごと（個人所得課税・資産課税・法人課税・消費課税）の平年度と初年度の額（億円）を書き出す。
税目の「計」の行があればそれを、無ければその税目の1行だけの改正事項の額を使う。
税目内に未解析の行がある場合や、記録済みの計・改正事項が消えた場合は旧CSVを保持して失敗する。
消費税の改正（免税制度・簡易課税など、率の変更ではないもの）を含む税目には「消費税の改正を含む」と印を付ける。

使い方（リポジトリのルートで）: python3 scripts/fetch_tax_revenue_estimates.py [--pause 30]
"""
from __future__ import annotations

import argparse
import csv
import os
import tempfile
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from register_external_material import register_once
except ImportError:  # unittest から scripts.* として読むとき
    from scripts.register_external_material import register_once

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / '.local/tax-revenue-estimates'
STORAGE = ROOT / '.local/external-materials'
TASK_ID = 'tax-revenue-estimates'
OUT = ROOT / 'data/acquired/tax-revenue-estimates/estimates.csv'
UA = 'Mozilla/5.0 (public-interest-lens; tax-revenue-estimates)'
WARP = 'https://warp.ndl.go.jp'
MOF = 'https://www.mof.go.jp/tax_policy/tax_reform/outline'

# 年度 → 取る URL。平成23・29年度、令和2年度の大綱の PDF には内国税の表が無く（別の PDF）、WARP で見つかっていないので資料待ち。
# 平成23年度の改正は震災で2本の法律（閣法-177-82・閣法-177-2）に分かれ、大綱の見込みと成立した中身が違うので、見つかっても注意して使う。
SOURCES = {
    2012: f'{WARP}/20120105/20120104021326/http://www.mof.go.jp/tax_policy/tax_reform/outline/fy2012/24zougensyuu.pdf',
    2013: f'{WARP}/20160110/20160106083234/http://www.mof.go.jp/tax_policy/tax_reform/outline/fy2013/250129taikou.pdf',
    2014: f'{WARP}/20160110/20160106083234/http://www.mof.go.jp/tax_policy/tax_reform/outline/fy2014/251224taikou.pdf',
    2015: f'{WARP}/20160110/20160106083234/http://www.mof.go.jp/tax_policy/tax_reform/outline/fy2015/20150114taikou.pdf',
    2016: f'{WARP}/20160110/20160106083234/http://www.mof.go.jp/tax_policy/tax_reform/outline/fy2016/20151224taikou.pdf',
    2018: f'{WARP}/20200109/20200106003103/http://www.mof.go.jp/tax_policy/tax_reform/outline/fy2018/20171222taikou.pdf',
    2019: f'{WARP}/20210303/20210301003005/www.mof.go.jp/tax_policy/tax_reform/outline/fy2019/20181221taikou.pdf',
    2021: f'{WARP}/20210303/20210301003005/www.mof.go.jp/tax_policy/tax_reform/outline/fy2021/20201221taikou.pdf',
    2022: f'{WARP}/20240903/20240901002709/https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2022/20211224taikou.pdf',
    2023: f'{WARP}/20240903/20240901002709/https://www.mof.go.jp/tax_policy/tax_reform/outline/fy2023/20221223taikou.pdf',
    2024: f'{MOF}/fy2024/20231222taikou.pdf',
    2025: f'{MOF}/fy2025/20241227taikou.pdf',
    2026: f'{MOF}/fy2026/20251226taikou.pdf',
}
CATEGORIES = ('個人所得課税', '資産課税', '法人課税', '消費課税')
HEADER = ['年度', '税目', '平年度_億円', '初年度_億円', '決め方', '消費税の改正を含む', '改正事項', '出典URL', '外部資料ID', '取得日時']
NUM = r'(▲\s*[\d,]+|[\d,]+|-|－)'
ROW = re.compile(rf'^\s*(.+?)\s{{2,}}{NUM}\s+{NUM}\s*$')


def number(text: str) -> int | None:
    t = text.replace(' ', '').replace(',', '')
    if t in ('-', '－', ''):
        return None
    return -int(t[1:]) if t.startswith('▲') else int(t)


def parse(text: str) -> list[dict]:
    """「（内国税関係）による増減収見込額」の表を税目ごとにまとめる。"""
    start = text.find('（内国税関係）による増減収見込額')
    if start < 0:
        return []
    body = text[start:]
    end = body.find('（地方税関係）')
    lines = (body[:end] if end > 0 else body).splitlines()
    out, cur, items, total = [], None, [], None
    headings = []

    def close():
        if cur is None:
            return
        if not items:
            raise ValueError('税目の改正事項を解析できない')
        if total is not None:
            plain, first, how = total[0], total[1], '計の行'
        elif len(items) == 1:
            plain, first, how = items[0][1], items[0][2], '改正事項が1行'
        else:
            return
        names = '、'.join(i[0] for i in items)
        out.append({'税目': cur, '平年度_億円': '' if plain is None else plain, '初年度_億円': '' if first is None else first,
                    '決め方': how, '消費税の改正を含む': '1' if re.search(r'消費税|軽減税率', names) else '', '改正事項': names})

    for line in lines:
        head = re.match(r'^\s*[１２３４５６７８９]．\s*(\S+課税)', line)
        if head:
            close()
            cur, items, total = head.group(1), [], None
            if cur not in CATEGORIES or cur in headings:
                raise ValueError('未知または重複した税目見出し')
            headings.append(cur)
            continue
        if re.match(r'^\s*合\s*計', line) or line.lstrip().startswith('（注'):
            close()
            cur = None
            continue
        if cur is None or not line.strip():
            continue
        m = ROW.match(line)
        if not m:
            raise ValueError('税目内に未解析の行がある')
        name = re.sub(r'\s+', '', m.group(1))
        if name.endswith('計') and name.startswith(cur):
            if total is not None:
                raise ValueError('税目の計が重複')
            total = (number(m.group(2)), number(m.group(3)))
        else:
            items.append((re.sub(r'^（\d+）', '', name), number(m.group(2)), number(m.group(3))))
    close()
    if set(headings) != {r['税目'] for r in out}:
        raise ValueError('税目の一部を解析できない')
    return out


def fetch_pdf(url: str, path: Path, pause: float, tries: int = 6) -> str | None:
    """PDF が返るまで取り直す。取れたら取得時刻を返す。"""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=120) as res:
                body = res.read()
        except Exception:  # 混雑の 403 も、ここで待って取り直す
            body = b''
        if body.startswith(b'%PDF'):
            path.write_bytes(body)
            return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
        time.sleep(pause * (i + 1))
    return None


def original_url(url: str) -> str:
    m = re.match(r'https://warp\.ndl\.go\.jp/\d+/\d+/(?:https?://)?(.+)$', url)
    return 'https://' + m.group(1) if m else url


def validate_rows(rows: list[dict]) -> None:
    keys = set()
    for r in rows:
        if set(r) != set(HEADER):
            raise ValueError('CSVの列が一致しない')
        key = (int(r['年度']), r['税目'])
        if key in keys or r['税目'] not in CATEGORIES:
            raise ValueError('年度・税目が重複または不正')
        keys.add(key)
        for field in ('平年度_億円', '初年度_億円'):
            if str(r[field]) != '' and not re.fullmatch(r'-?\d+', str(r[field])):
                raise ValueError('金額が不正')
        if r['消費税の改正を含む'] not in ('', '1') or not r['出典URL'].startswith('https://www.mof.go.jp/') or not r['外部資料ID']:
            raise ValueError('出典または消費税の印が不正')


def atomic_write(rows: list[dict]) -> None:
    validate_rows(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=OUT.parent, delete=False) as f:
            temporary = Path(f.name)
            w = csv.DictWriter(f, fieldnames=HEADER, lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, OUT)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pause', type=float, default=30.0)
    a = ap.parse_args(argv)
    old = {}
    try:
        if OUT.exists():
            with OUT.open(encoding='utf-8', newline='') as f:
                previous = list(csv.DictReader(f))
            validate_rows(previous)
            for r in previous:
                old.setdefault(int(r['年度']), []).append(r)
        RAW.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as exc:
        print(f'旧CSVまたは保存先の検査失敗（{type(exc).__name__}）。更新なし', file=sys.stderr)
        return 1
    candidate = dict(old)
    failures = []
    for fy, url in SOURCES.items():
        try:
            expected = {r['税目'] for r in old.get(fy, [])}
            if not expected:
                raise ValueError('新年度の期待税目が未確認')
            pdf = RAW / f'fy{fy}.pdf'
            fetched = None
            if not pdf.exists() or not pdf.read_bytes().startswith(b'%PDF'):
                fetched = fetch_pdf(url, pdf, a.pause)
                if fetched is None:
                    raise ValueError('PDF取得失敗')
            mid = register_once(input_path=pdf, source_url=url, task_id=TASK_ID, title=f'{fy}年度の税制改正の大綱（財務省）',
                                purpose='年度・税目別の政府増減収予測を保存する', storage_root=STORAGE, observed_at=fetched)
            text = subprocess.run(['pdftotext', '-layout', str(pdf), '-'], capture_output=True, text=True, check=True).stdout
            parsed = parse(text)
            if not parsed or {r['税目'] for r in parsed} != expected or len(parsed) != len(expected):
                raise ValueError('税目の空・部分・重複解析')
            before = {r['税目']: r for r in old[fy]}
            for row in parsed:
                previous = before[row['税目']]
                if previous['決め方'] == '計の行' and row['決め方'] != '計の行':
                    raise ValueError('記録済みの計の行が消えた')
                previous_items = set(previous['改正事項'].split('、')) - {''}
                if not previous_items.issubset(row['改正事項'].split('、')):
                    raise ValueError('記録済みの改正事項が消えた')
                for field in ('平年度_億円', '初年度_億円'):
                    if row[field] == '' and before[row['税目']][field] != '':
                        raise ValueError('記録済みの金額が欠測になった')
            when = fetched or next((r['取得日時'] for r in old[fy] if r['取得日時']), '')
            candidate[fy] = [{'年度': fy, **r, '出典URL': original_url(url), '外部資料ID': mid, '取得日時': when} for r in parsed]
            validate_rows(candidate[fy])
        except Exception as exc:
            failures.append(f'{fy}年度（{type(exc).__name__}）')
    if failures:
        print('検査失敗、旧CSVを保持：' + '、'.join(failures), file=sys.stderr)
        return 1
    rows = [r for fy in sorted(candidate) for r in sorted(candidate[fy], key=lambda r: CATEGORIES.index(r['税目']))]
    try:
        if not rows:
            raise ValueError('空の候補')
        atomic_write(rows)
    except Exception as exc:
        print(f'保存失敗（{type(exc).__name__}）。旧CSVを保持', file=sys.stderr)
        return 1
    print(f'{len(rows)}行を検査して保存')
    return 0


if __name__ == '__main__':
    sys.exit(main())
