import json
import unittest

from scripts import fetch_more_stats as f


class EraTests(unittest.TestCase):
    def test_header_labels(self):
        y, era = f.era_year_label('平成\n3年', None)
        self.assertEqual((y, era), (1991, '平成'))
        self.assertEqual(f.era_year_label(4.0, era)[0], 1992)
        y, era = f.era_year_label('令和\n元年', era)
        self.assertEqual((y, era), (2019, '令和'))
        self.assertEqual(f.era_year_label(2.0, era)[0], 2020)
        self.assertEqual(f.era_year_label(2015, None)[0], 2015)
        self.assertEqual(f.era_year_label('2016年9月期', None)[0], None)

    def test_to_number(self):
        self.assertEqual(f.to_number('<284>'), (284.0, True))
        self.assertEqual(f.to_number(3), (3.0, False))
        self.assertIsNone(f.to_number('-'))
        self.assertIsNone(f.to_number(None))


class MatrixTests(unittest.TestCase):
    def test_industry_table_carries_parent_labels(self):
        rows = [
            ['title'] + [None] * 6,
            [None] * 7,
            [None] * 7,
            ['区分', None, None, None, None, '平成\n3年', 4.0],
            ['入職率', None, None, None, None, None, None],
            [None, 'ＧＴ', '調査産業計', None, None, 16.7, 15.8],
            [None, 'Ｅ', '製造業', None, None, 13.6, 12.5],
            [None, None, None, '消費関連', None, 15.3, 16.7],
            ['離職率', None, None, None, None, None, None],
            [None, 'ＧＴ', '調査産業計', None, None, 17.0, '-'],
        ]
        recs = f.parse_matrix_table(rows, 3, 5, [0], [2, 3], skip_label_cols=[1])
        got = {(s, lab, y): v for s, lab, y, v, _e, _s in recs}
        self.assertEqual(got[('入職率', '調査産業計', 1991)], 16.7)
        self.assertEqual(got[('入職率', '製造業/消費関連', 1992)], 16.7)
        self.assertEqual(got[('離職率', '調査産業計', 1991)], 17.0)
        self.assertNotIn(('離職率', '調査産業計', 1992), got)  # 数でないセルは書かない


class MonthlyLabourTests(unittest.TestCase):
    def test_filters_calendar_year_and_size(self):
        head = ['種別', '年', '月', '産業分類', '規模', '就業形態'] + f.MK_MEASURES
        def row(year, month, ind, size, form, wage):
            return ['実数', str(year), month, ind, size, form, wage] + [''] * (len(f.MK_MEASURES) - 1)
        text = '\n'.join(','.join(r) for r in [
            head,
            row(2000, 'CY', 'TL  ', 'T', '0', '350000'),
            row(2000, '01', 'TL  ', 'T', '0', '999'),   # 月次は使わない
            row(2000, 'CY', 'TL  ', '4', '0', '111'),   # 500人以上は使わない
            row(2000, 'CY', 'XX  ', 'T', '0', '222'),   # 未知の産業コードは使わない
        ])
        out = f.parse_mk_csv(text, 'u')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][:5], ['現金給与総額', '調査産業計/就業形態計/事業所規模5人以上', 2000, '350000', '円'])


class BojTests(unittest.TestCase):
    def test_year_end_only(self):
        text = ('STATUS,200\nNEXTPOSITION,\nSERIES_CODE,NAME_OF_TIME_SERIES_J,UNIT_J,FREQUENCY,CATEGORY_J,LAST_UPDATE,SURVEY_DATES,VALUES\n'
                'A_B,x,億円,QUARTERLY,c,20260810,199003,100\nA_B,x,億円,QUARTERLY,c,20260810,199004,110\nA_B,x,億円,QUARTERLY,c,20260810,199104,NA\n')
        out = f.parse_boj_csv(text, {'A_B': '製造業／残高／銀行勘定'}, 'u')
        self.assertEqual([(r[1], r[2], r[3]) for r in out], [('製造業', 1990, '110')])

    def test_select_codes(self):
        meta = {'RESULTSET': [
            {'SERIES_CODE': 'DLLILKG90_DLLI5DS2T', 'FREQUENCY': 'QUARTERLY', 'NAME_OF_TIME_SERIES_J': '総貸出／残高'},
            {'SERIES_CODE': 'DLLILKG90_DLLI5DS3T', 'FREQUENCY': 'QUARTERLY', 'NAME_OF_TIME_SERIES_J': '総貸出／設備資金'},
            {'SERIES_CODE': '', 'FREQUENCY': '', 'NAME_OF_TIME_SERIES_J': '見出し'}]}
        self.assertEqual([c for c, _ in f.boj_select_codes(meta)], ['DLLILKG90_DLLI5DS2T'])


class FsaTests(unittest.TestCase):
    def test_period_and_table(self):
        self.assertEqual(f.fsa_period('11年3月期'), (1999, 3))
        self.assertEqual(f.fsa_period('2016年9月期'), (2016, 9))
        rows = [
            [None, None, None, None, None, '11年3月期', '11年9月期', '12年3月期', '12年9月期'],
            [None, '全国銀行', None, '総与信(億円)', None, 500, 510, 520, 530],
            [None, None, None, '金融再生法開示債権（億円）', None, 50, 51, 52, 53],
            [None, None, None, '不良債権比率(％)', None, 6.2, 5.9, '-', 5.0],
        ]
        got = f.parse_fsa_table1(rows)
        self.assertEqual(got[(1999, 3)], {'総与信': 500.0, '金融再生法開示債権': 50.0, '不良債権比率': 6.2})
        self.assertNotIn('不良債権比率', got[(2000, 3)])  # '-' は書かない


class EnergyTests(unittest.TestCase):
    def test_blocks_and_units(self):
        rows = [
            [None, '4.電源構成'],
            [None, None, None, None, None, '(億kWh)'],
            [None, '年度', None, 2010, 2011],
            [None, '原子力', None, 2882.3, None],
            [None, '合計', None, 11494.5, 10000],
            [None, None],
            [None, None, None, None, None, '(構成比)'],
            [None, '年度', None, 2010, 2011],
            [None, '原子力', None, 0.25, 0.1],
        ]
        out = f.parse_energy_sheet('4', rows, 'u')
        self.assertEqual([(r[1], r[2], r[3], r[4]) for r in out],
                         [('原子力', 2010, '2882.3', '億kWh'), ('合計', 2010, '11494.5', '億kWh'), ('合計', 2011, '10000', '億kWh')])


class WorldBankTests(unittest.TestCase):
    def test_skips_null(self):
        body = json.dumps([{}, [
            {'indicator': {'id': 'X'}, 'country': {'id': 'JP'}, 'countryiso3code': 'JPN', 'date': '2000', 'value': 1.5},
            {'indicator': {'id': 'X'}, 'country': {'id': 'JP'}, 'countryiso3code': 'JPN', 'date': '2001', 'value': None}]]).encode()
        out = f.parse_wb_json(body, '名', '%', 'u')
        self.assertEqual([(r[1], r[2], r[3]) for r in out], [('JPN', 2000, '1.5')])


if __name__ == '__main__':
    unittest.main()
