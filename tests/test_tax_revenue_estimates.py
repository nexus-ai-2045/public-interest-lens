"""政府予測の取得が失敗したときのCSV保全を検証する。"""
from __future__ import annotations

import csv
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import fetch_tax_revenue_estimates as estimates


def table(categories=('個人所得課税', '法人課税'), amount='0'):
    return '（内国税関係）による増減収見込額\n' + '\n'.join(
        f'{n}．{category}\n改正事項  {amount} -' for n, category in zip('１２３４', categories)) + '\n合計\n（地方税関係）'


class TaxRevenueEstimatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'estimates.csv'
        self.raw = self.root / 'raw'
        self.raw.mkdir()
        (self.raw / 'fy2024.pdf').write_bytes(b'%PDF fixture')
        self.rows = []
        for year in (2023, 2024):
            for category in ('個人所得課税', '法人課税'):
                row = dict.fromkeys(estimates.HEADER, '')
                row.update({'年度': str(year), '税目': category, '平年度_億円': '100', '初年度_億円': '', '出典URL': 'https://www.mof.go.jp/test.pdf', '外部資料ID': 'fixture'})
                self.rows.append(row)
        with self.out.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=estimates.HEADER)
            writer.writeheader()
            writer.writerows(self.rows)
        self.original = self.out.read_bytes()

    def run_fetch(self, text=None, registration=None, extraction=None, replace=None, sources=None):
        with patch.multiple(estimates, OUT=self.out, RAW=self.raw, SOURCES=sources or {2024: 'https://www.mof.go.jp/test.pdf'}), \
             patch.object(estimates, 'register_once', side_effect=registration, return_value='registered'), \
             patch.object(estimates.subprocess, 'run', side_effect=extraction, return_value=subprocess.CompletedProcess([], 0, stdout=text or table())), \
             patch.object(estimates.os, 'replace', side_effect=replace, wraps=None if replace else estimates.os.replace):
            return estimates.main(['--pause', '0'])

    def assert_preserved(self):
        self.assertEqual(hashlib.sha256(self.out.read_bytes()).hexdigest(), hashlib.sha256(self.original).hexdigest())

    def record_previous_items(self):
        for row in self.rows:
            row.update({'決め方': '計の行', '改正事項': '項目A、項目B'})
        with self.out.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=estimates.HEADER)
            writer.writeheader()
            writer.writerows(self.rows)
        self.original = self.out.read_bytes()

    def test_intra_category_partial_preserves_bytes(self):
        self.record_previous_items()
        for tail in (
            '項目B  判読不能 判読不能\n{category}計  判読不能 判読不能',
            '項目B  判読不能 判読不能\n{category}計  100 -',
            '項目B  90 -\n{category}計  判読不能 判読不能',
            '',
            '{category}計  100 -',
            '項目B  90 -',
        ):
            text = '（内国税関係）による増減収見込額\n' + '\n'.join(
                f'{n}．{category}\n項目A  10 -\n' + tail.format(category=category)
                for n, category in zip('１２', ('個人所得課税', '法人課税'))
            ) + '\n合計\n（地方税関係）'
            with self.subTest(tail=tail):
                self.out.write_bytes(self.original)
                self.assertEqual(self.run_fetch(text), 1)
                self.assert_preserved()

    def test_complete_single_and_multiple_items(self):
        single = estimates.parse(table(('法人課税',), '10'))
        self.assertEqual(single[0]['決め方'], '改正事項が1行')
        self.assertEqual(single[0]['平年度_億円'], 10)
        self.record_previous_items()
        text = '（内国税関係）による増減収見込額\n' + '\n'.join(
            f'{n}．{category}\n項目A  10 -\n項目B  90 -\n{category}計  100 -'
            for n, category in zip('１２', ('個人所得課税', '法人課税'))
        ) + '\n合計\n（地方税関係）'
        self.assertEqual(self.run_fetch(text), 0)
        with self.out.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([r['決め方'] for r in rows[2:]], ['計の行', '計の行'])
        self.assertEqual([r['改正事項'] for r in rows[2:]], ['項目A、項目B', '項目A、項目B'])
        self.assertEqual([r['平年度_億円'] for r in rows[2:]], ['100', '100'])

    def test_empty_partial_and_duplicate_parse_preserve_bytes(self):
        for text in ('no table', table(('個人所得課税',)), table(('個人所得課税', '個人所得課税')), table(('個人所得課税',)) + '\n２．法人課税\n解析不能'):
            with self.subTest(text=text):
                self.assertEqual(self.run_fetch(text), 1)
                self.assert_preserved()

    def test_registration_and_extraction_failures_preserve_bytes(self):
        for kwargs in ({'registration': OSError('registration')}, {'extraction': subprocess.CalledProcessError(1, 'pdftotext')}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.run_fetch(**kwargs), 1)
                self.assert_preserved()

    def test_atomic_replace_and_write_failures_preserve_bytes(self):
        self.assertEqual(self.run_fetch(replace=OSError('replace')), 1)
        self.assert_preserved()
        with patch.object(estimates.csv.DictWriter, 'writerows', side_effect=OSError('write')):
            self.assertEqual(self.run_fetch(), 1)
        self.assert_preserved()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['estimates.csv', 'raw'])

    def test_success_preserves_other_year_and_zero_and_missing(self):
        self.assertEqual(self.run_fetch(), 0)
        with self.out.open(encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[:2], self.rows[:2])
        self.assertEqual([r['平年度_億円'] for r in rows[2:]], ['0', '0'])
        self.assertEqual([r['初年度_億円'] for r in rows[2:]], ['', ''])

    def test_partial_batch_or_unconfirmed_new_year_does_not_commit(self):
        self.assertEqual(self.run_fetch(sources={2024: 'https://www.mof.go.jp/test.pdf', 2026: 'https://www.mof.go.jp/new.pdf'}), 1)
        self.assert_preserved()

    def test_new_missing_amount_or_duplicate_input_is_rejected(self):
        self.assertEqual(self.run_fetch(table(amount='-')), 1)
        self.assert_preserved()
        with self.out.open('a', encoding='utf-8', newline='') as f:
            csv.DictWriter(f, fieldnames=estimates.HEADER).writerow(self.rows[0])
        self.original = self.out.read_bytes()
        self.assertEqual(self.run_fetch(), 1)
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
