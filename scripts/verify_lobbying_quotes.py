"""ロビー活動の取り込み行の機械照合：出典URLの本文を取り直し、引用の原文と法律名が本当にそこにあるかを確かめる（系統Aの照合）。

入力は data/acquired/lobbying/*.csv の「引用」「該当法令」「出典URL」。結果は同じ表の「確度」列に書く。
- 原文照合済み（機械）：引用が本文に空白・改行・全半角の違いを除いて含まれ、該当法令の全部が本文に出る。
- 照合できず：本文に引用が無い、または法律名が本文に出ない（行は残すが、経済界の帳簿には入れない）。
- 未取得：URL が取れない（通信拒否・PDF の抽出失敗）。
AI の読み（系統B）は別。確かさの高い取り込みには2系統の一致が要る（AGENTS.md）ので、この機械照合だけの行は帳簿で「中」までとする。

使い方: python3 scripts/verify_lobbying_quotes.py [--dir data/acquired/lobbying] [--offline-cache DIR]
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'data/acquired/lobbying'
UA = 'Mozilla/5.0 (compatible; public-interest-lens verifier)'
OK, NG, MISSING = '原文照合済み（機械）', '照合できず', '未取得'


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ('script', 'style')

    def handle_endtag(self, tag):
        self._skip -= tag in ('script', 'style') and self._skip > 0

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def norm(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def fetch_text(url: str) -> str | None:
    """本文の文字列。取れなければ None。PDF は pdftotext、HTML は文字だけ取り出す。"""
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / 'body'
        res = subprocess.run(['curl', '-sSL', '--max-time', '60', '-A', UA, '-o', str(raw), '-w', '%{http_code}', url],
                             capture_output=True, text=True)
        if res.returncode != 0 or not res.stdout.startswith('2') or not raw.exists():
            return None
        data = raw.read_bytes()
        if data[:4] == b'%PDF':
            out = subprocess.run(['pdftotext', '-layout', str(raw), '-'], capture_output=True)
            return out.stdout.decode('utf-8', 'ignore') if out.returncode == 0 else None
        for enc in ('utf-8', 'cp932', 'euc-jp'):
            try:
                html = data.decode(enc)
                break
            except UnicodeDecodeError:
                html = ''
        parser = _Text()
        parser.feed(html or data.decode('utf-8', 'ignore'))
        return ' '.join(parser.parts)


def verify_row(row: dict[str, str], cache: dict[str, str | None]) -> str:
    url = row['出典URL']
    if url not in cache:
        cache[url] = fetch_text(url)
    text = cache[url]
    if text is None:
        return MISSING
    body = norm(text)
    laws = [x for x in re.split(r'[、,]', row['該当法令']) if x]
    if norm(row['引用']) and norm(row['引用']) in body and laws and all(norm(x) in body for x in laws):
        return OK
    return NG


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', type=Path, default=DEFAULT_DIR)
    args = ap.parse_args()
    cache: dict[str, str | None] = {}
    total = {OK: 0, NG: 0, MISSING: 0}
    for path in sorted(args.dir.glob('*.csv')):
        with path.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fields = list(reader.fieldnames or [])
        if '確度' not in fields:
            fields.append('確度')
        for r in rows:
            r['確度'] = verify_row(r, cache)
            total[r['確度']] += 1
        with path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
    print(total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
