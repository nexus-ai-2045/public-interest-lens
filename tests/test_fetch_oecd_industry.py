import unittest

from scripts import fetch_oecd_industry as f

HEAD = 'DATAFLOW,FREQ,REF_AREA,SECTOR,TRANSACTION,ACTIVITY,UNIT_MEASURE,PRICE_BASE,TIME_PERIOD,OBS_VALUE,REF_YEAR_PRICE,UNIT_MULT,CURRENCY'


def line(area='JPN', act='J', price='L', year='2015', val='100', ref='2020', mult='6', cur='JPY', tr='B1G', sec='S1', unit='XDC'):
    return f'X,A,{area},{sec},{tr},{act},{unit},{price},{year},{val},{ref},{mult},{cur}'


class UrlTests(unittest.TestCase):
    def test_key_has_twelve_dimensions(self):
        url = f.build_url('JPN')
        key = url.split('/')[-1].split('?')[0]
        self.assertEqual(len(key.split('.')), 12)
        self.assertTrue(key.startswith('A.JPN.S1.S1.B1G._Z._T+J+I+K+H+A+C+F+G+L+M+N+P+Q+R+S+T+B+D._Z.XDC.V+L+LR.N.'))


    def test_new_sections_are_listed_and_water_waste_is_not(self):
        # field-expansion-v1：新分野の節を足す。macro-v1 の結び直し（2026-10-29）で B・D を足した。水道・廃棄物（E）は足さない。
        self.assertEqual(list(f.ACTIVITIES), ['_T', 'J', 'I', 'K', 'H', 'A', 'C', 'F', 'G', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'B', 'D'])
        self.assertNotIn('E', f.ACTIVITIES)


class UnitTests(unittest.TestCase):
    def test_unit_label(self):
        self.assertEqual(f.unit_label('JPY', '6'), '百万JPY')
        self.assertEqual(f.unit_label('USD', '9'), '十億USD')
        with self.assertRaises(ValueError):
            f.unit_label('USD', '4')


class ParseTests(unittest.TestCase):
    def test_parse_filters_and_sorts(self):
        text = '\n'.join([
            HEAD,
            line(year='2016', val='110'),
            line(year='2015', val='100'),
            line(price='V', year='2015', val='90'),
            line(act='Z9', val='5'),
            line(tr='D1', val='7'),
            line(val=''),
            line(year='2017', val='', price='LR'),
        ])
        rows = f.parse_table(text, 'U')
        self.assertEqual([(r['価格'], r['年'], r['値']) for r in rows], [('L', '2015', '100'), ('L', '2016', '110'), ('V', '2015', '90')])
        self.assertEqual(rows[0]['基準年'], '2020')
        self.assertEqual(rows[2]['基準年'], '')
        self.assertEqual(f.parse_table(HEAD + '\n' + line(act='C', val='5'), 'U')[0]['産業'], 'C')  # 新しい節は表に出る
        self.assertEqual(f.parse_table(HEAD + '\n' + line(act='D', val='5'), 'U')[0]['産業'], 'D')  # 電気・ガス（エネルギー分野）
        self.assertEqual(f.parse_table(HEAD + '\n' + line(act='E', val='5'), 'U'), [])  # E は取得しない
        self.assertEqual(rows[0]['単位'], '百万JPY')
        self.assertEqual(rows[0]['出典URL'], 'U')

    def test_missing_years_are_not_filled(self):
        text = '\n'.join([HEAD, line(year='2000'), line(year='2002')])
        self.assertEqual([r['年'] for r in f.parse_table(text, 'U')], ['2000', '2002'])

    def test_duplicate_same_value_ok_conflict_fails(self):
        same = '\n'.join([HEAD, line(), line()])
        self.assertEqual(len(f.parse_table(same, 'U')), 1)
        conflict = '\n'.join([HEAD, line(val='1'), line(val='2')])
        with self.assertRaises(ValueError):
            f.parse_table(conflict, 'U')


if __name__ == '__main__':
    unittest.main()


class RebuildTests(unittest.TestCase):
    def test_rebuild_reads_old_raw_and_bd_raw_and_keeps_both_sources(self):
        import csv
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp, 'raw'), Path(tmp, 'out')
            raw.mkdir()
            out.mkdir()
            old_url = 'OLD-URL'
            (out / 'sources.csv').write_text(f'国,産業,出典URL\nJPN,*,{old_url}\n', encoding='utf-8')
            (raw / 'table6-JPN.csv').write_text('\n'.join([HEAD, line(act='J', val='1')]), encoding='utf-8')
            # 新版の原本は B・D 以外（J）の値が旧版と違っても、B・D だけを取る
            (raw / 'table6-bd-JPN.csv').write_text('\n'.join([HEAD, line(act='J', val='999'), line(act='B', val='5'), line(act='D', val='6')]), encoding='utf-8')
            f.main(['--raw', str(raw), '--out', str(out), '--rebuild'])
            rows = list(csv.DictReader((out / 'industry_va.csv').open(encoding='utf-8')))
            self.assertEqual(sorted((r['産業'], r['値']) for r in rows), [('B', '5'), ('D', '6'), ('J', '1')])
            sources = f.load_sources(out / 'sources.csv')
            self.assertEqual(f.source_url(sources, 'JPN', 'J'), old_url)
            self.assertEqual(f.source_url(sources, 'JPN', 'B'), f.build_url('JPN'))
