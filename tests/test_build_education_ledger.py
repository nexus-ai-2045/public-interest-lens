import csv
import unittest
from pathlib import Path

from scripts import build_education_ledger as b
from scripts import fetch_education_stats as f

LEDGER = Path(__file__).resolve().parents[1] / 'data/derived/education-ledger-v1'


def rows(name):
    with (LEDGER / name).open(encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


class DidTests(unittest.TestCase):
    def g(self, d):
        return {y: {'差': v} for y, v in d.items()}

    def test_full_window_is_confirmed(self):
        g = self.g({2001: 1.0, 2002: 1.0, 2003: 1.0, 2005: 3.0, 2006: 3.0})
        r = b.did(g, 2004)
        self.assertEqual(r['状態'], '確定')
        self.assertAlmostEqual(r['差の差'], 2.0)

    def test_post_window_not_filled_is_provisional(self):
        g = self.g({2001: 1.0, 2002: 1.0, 2003: 1.0, 2005: 3.0})
        self.assertEqual(b.did(g, 2004)['状態'], '暫定')
        self.assertEqual(b.did(self.g({2001: 1.0, 2002: 1.0, 2003: 1.0}), 2004)['状態'], '暫定')

    def test_too_few_pre_years_is_unmeasurable(self):
        self.assertEqual(b.did(self.g({2003: 1.0, 2005: 2.0}), 2004)['状態'], '測定不能')

    def test_trend_removal_zero_for_linear_gap(self):
        g = self.g({y: 0.5 * (y - 2000) for y in range(1999, 2008)})
        r = b.did(g, 2004)
        self.assertAlmostEqual(r['趨勢除去後の差の差'], 0.0, places=9)


class ComparatorTests(unittest.TestCase):
    def test_catch_up_ireland_and_unknown_are_excluded(self):
        def s(c, gdp, emp):
            return {c: {2000: gdp}}, {c: {2000: emp}}
        gdp, emp = {}, {}
        for c, g, e in [('JPN', 100, 10), ('AAA', 90, 10), ('BBB', 70, 10), ('IRL', 200, 10)]:
            gdp[c], emp[c] = {2000: g}, {2000: e}
        gdp['CCC'] = {2000: 100}
        used, rep = b.comparators({'GDP（購買力平価）': gdp, '就業者数': emp})
        self.assertEqual(used, ['AAA'])
        why = {r['国']: r['理由'] for r in rep}
        self.assertIn('8割未満', why['BBB'])
        self.assertIn('ゆがむ', why['IRL'])
        self.assertIn('確かめられない', why['CCC'])

    def test_median_needs_three_countries(self):
        st = {'x': {'JPN': {2000: 5.0}, 'A': {2000: 1.0}, 'B': {2000: 2.0}}}
        self.assertEqual(b.gaps(st, 'x', ['A', 'B']), {})
        st['x']['C'] = {2000: 3.0}
        self.assertAlmostEqual(b.gaps(st, 'x', ['A', 'B', 'C'])[2000]['差'], 3.0)


class FetchParseTests(unittest.TestCase):
    def test_msti_keeps_levels_of_oecd_members_only(self):
        head = 'DATAFLOW,REF_AREA,FREQ,MEASURE,UNIT_MEASURE,PRICE_BASE,TRANSFORMATION,TIME_PERIOD,OBS_VALUE'
        text = '\n'.join([head,
                           'X,JPN,A,H,PT_B1GQ,_Z,_Z,2000,0.4',
                           'X,JPN,A,H,PT_B1GQ,_Z,GY,2000,5.0',
                           'X,CHN,A,H,PT_B1GQ,_Z,_Z,2000,0.1',
                           'X,JPN,A,H,PT_B1GQ,_Z,_Z,2001,'])
        out = f.msti_rows(text)
        self.assertEqual([(r['国'], r['年'], r['値']) for r in out], [('JPN', 2000, '0.4')])


class LedgerFilesTests(unittest.TestCase):
    def test_every_law_in_actions_exists_and_amounts_are_unmeasured(self):
        with (Path(b.OUTCOMES)).open(encoding='utf-8', newline='') as fh:
            known = {r['id'] for r in csv.DictReader(fh)}
        for a in rows('actions.csv'):
            for lid in a['法律ID'].split(';'):
                self.assertIn(lid, known)
        for r in rows('chains.csv'):
            self.assertEqual(r['額'], '未測定')
            self.assertIn(r['状態'], {'確定', '暫定', '測定不能', '指標なし'})

    def test_confirmed_rows_have_numbers_and_enough_countries(self):
        for r in rows('chains.csv'):
            if r['状態'] == '確定':
                self.assertNotEqual(r['差の差'], '')
                self.assertGreaterEqual(int(r['比較国数']), b.MIN_COUNTRIES)

    def test_committed_files_are_current(self):
        before = {n: (LEDGER / n).read_bytes() for n in ('chains.csv', 'law-links.csv', 'indicator-gaps.csv', 'comparators.csv')}
        b.main()
        for n, body in before.items():
            self.assertEqual((LEDGER / n).read_bytes(), body, n)


if __name__ == '__main__':
    unittest.main()
