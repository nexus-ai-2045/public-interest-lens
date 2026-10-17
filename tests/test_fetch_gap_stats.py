import json
import unittest

from scripts import fetch_gap_stats as f


def sdmx(head, *lines):
    return '\n'.join([head, *lines])


TENURE_HEAD = 'DATAFLOW,REF_AREA,MEASURE,UNIT_MEASURE,SEX,AGE,TENURE,FREQ,TIME_PERIOD,OBS_VALUE'


def tline(area='JPN', measure='TENURE_EMP', sex='_T', age='_T', tenure='M_LT12', year='2015', val='10.5', unit='PT_POP_SUB'):
    return f'X,{area},{measure},{unit},{sex},{age},{tenure},A,{year},{val}'


class HelperTests(unittest.TestCase):
    def test_jp_count(self):
        self.assertEqual(f.jp_count('4億9,030万3,745'), 490_303_745)
        self.assertEqual(f.jp_count('1億5,594万3,915件'), 155_943_915)
        self.assertEqual(f.jp_count('3,768'), 3768)
        with self.assertRaises(ValueError):
            f.jp_count('abc')

    def test_tenure_url_key_has_seven_dimensions(self):
        key = f.TENURE_URL.split('/')[-1].split('?')[0]
        self.assertEqual(len(key.split('.')), 7)

    def test_year_tokens_heisei_to_reiwa(self):
        self.assertEqual(f.year_tokens([28, 29, 30, '元', 2.0, 3]), [2016, 2017, 2018, 2019, 2020, 2021])
        self.assertEqual(f.year_tokens(['19', '20']), [2007, 2008])
        with self.assertRaises(ValueError):
            f.year_tokens([30, 29])
        with self.assertRaises(ValueError):
            f.year_tokens(['x'])


class OecdTests(unittest.TestCase):
    def test_tenure_filters_and_labels(self):
        text = sdmx(TENURE_HEAD, tline(), tline(year='2014', val='11'), tline(area='ZZZ'), tline(age='Y25T29'),
                    tline(tenure='Y_5T9'), tline(val=''), tline(measure='TENURE_EMP_DEP', sex='F', tenure='Y_GE10', val='30'))
        rows = f.parse_tenure(text, 'U')
        self.assertEqual([(r['区分'], r['年'], r['値']) for r in rows],
                         [('勤続10年以上／雇用者（被用者）／女性', '2015', '30'),
                          ('勤続1年未満／就業者全体／男女計', '2014', '11'),
                          ('勤続1年未満／就業者全体／男女計', '2015', '10.5')])

    def test_tenure_conflict_and_unit(self):
        with self.assertRaises(ValueError):
            f.parse_tenure(sdmx(TENURE_HEAD, tline(val='1'), tline(val='2')), 'U')
        with self.assertRaises(ValueError):
            f.parse_tenure(sdmx(TENURE_HEAD, tline(unit='PT')), 'U')

    def test_wages_real_and_nominal(self):
        head = 'DATAFLOW,REF_AREA,MEASURE,UNIT_MEASURE,PAY_PERIOD,PRICE_BASE,AGGREGATION_OPERATION,SEX,TIME_PERIOD,OBS_VALUE,BASE_PER,UNIT_MULT'
        text = sdmx(head,
                    'X,JPN,WG,USD_PPP,A,Q,MEAN,_Z,2000,40000,2025,0',
                    'X,JPN,WG,JPY,A,V,MEAN,_Z,2000,4000000,,0',
                    'X,ZZZ,WG,JPY,A,V,MEAN,_Z,2000,1,,0',
                    'X,JPN,WG,JPY,A,Q,MEAN,_Z,2001,,2025,0')
        rows = f.parse_wages(text, 'U')
        self.assertEqual([(r['区分'], r['値'], r['単位']) for r in rows],
                         [('名目／JPY', '4000000', 'JPY／年'), ('実質（2025年価格）／米ドル（購買力平価）', '40000', '米ドル（購買力平価）／年')])
        with self.assertRaises(ValueError):
            f.parse_wages(sdmx(head, 'X,JPN,WG,JPY,A,V,MEAN,_Z,2000,1,,6'), 'U')

    def test_broadband_selects_fixed_all_access(self):
        head = 'DATAFLOW,REF_AREA,FREQ,NETWORK_TYPE,MEASURE,NETWORK_ACCESS_MODE,NETWORK_SPEED,UNIT_MEASURE,TIME_PERIOD,OBS_VALUE,UNIT_MULT'
        text = sdmx(head,
                    'X,JPN,A,FBB,SUB,_T,_Z,100HB,2010,26.6,0',
                    'X,JPN,A,FBB,SUB,_T,_Z,SB,2010,33000000,0',
                    'X,JPN,Q,FBB,SUB,_T,_Z,100HB,2010,26.6,0',
                    'X,JPN,A,FBB,SUB,DSL,_Z,100HB,2010,5,0',
                    'X,JPN,A,FBB,SUB,_T,ST_100_1000,100HB,2010,5,0',
                    'X,JPN,A,FBB,DATA,_T,_Z,100HB,2010,5,0')
        rows = f.parse_broadband(text, 'U')
        self.assertEqual(sorted((r['単位'], r['値']) for r in rows), [('契約数', '33000000'), ('契約数/100人', '26.6')])


class WorldBankTests(unittest.TestCase):
    def test_parse_wb_skips_null_and_other_countries(self):
        data = [{'page': 1, 'pages': 1}, [
            {'countryiso3code': 'JPN', 'date': '2000', 'value': 5.3},
            {'countryiso3code': 'JPN', 'date': '2001', 'value': None},
            {'countryiso3code': 'ZZZ', 'date': '2000', 'value': 1.0}]]
        rows = f.parse_wb(json.dumps(data), 'U', 'GFDD.SI.02')
        self.assertEqual([(r['国'], r['年'], r['値']) for r in rows], [('JPN', '2000', '5.3')])

    def test_parse_wb_multi_page_fails(self):
        with self.assertRaises(ValueError):
            f.parse_wb(json.dumps([{'page': 1, 'pages': 2}, []]), 'U', 'GFDD.SI.02')


def airport_block(name, cal, fy):
    rows = [[None, '空港名 ：', name] + [None] * 14,
            [None, '項目', None, '着 陸 回 数 （回）'] + [None] * 13,
            [None, None, '国際線', '国内線', '計'] + [None] * 12,
            [None, '年別'] + [None] * 15,
            [None] * 17]
    for tok, intl, dom in cal:
        rows.append([None, tok, 1, 1, 2, 0, 0, 0, intl, 0, 0, dom, intl + dom, 0, None, None, None])
    rows += [[None] * 17, [None] * 17]
    for tok, intl, dom in fy:
        rows.append([None, tok, 1, 1, 2, 0, 0, 0, intl, 0, 0, dom, intl + dom, 0, None, None, None])
    rows += [[None] * 17, [None] * 17, [None, '項目'] + [None] * 15, [None, '年別'] + [None] * 15, [None] * 17, [None, '28', 5] + [None] * 14]
    return rows


class AirportTests(unittest.TestCase):
    def test_parse_two_blocks(self):
        rows = [[None, '暦年・年度別空港管理状況調書'] + [None] * 15]
        rows += airport_block('中部国際  （会社管理）', [('30', 100, 50), ('元', 110, 60)], [('30', 90, 40), ('元', 95, 45)])
        rows += airport_block('成田国際（会社管理）', [('30', 1, 2), ('元', 3, 4)], [('30', 5, 6), ('元', 7, 8)])
        out = f.parse_airports(rows, 's')
        self.assertEqual(out[('中部国際（会社管理）', '暦年', '合計', 2018)], 150)
        self.assertEqual(out[('中部国際（会社管理）', '暦年', '国際線', 2019)], 110)
        self.assertEqual(out[('中部国際（会社管理）', '年度', '国内線', 2019)], 45)
        self.assertEqual(out[('成田国際（会社管理）', '年度', '合計', 2018)], 11)
        self.assertEqual(len(out), 2 * 2 * 2 * 3)

    def test_total_mismatch_is_dropped(self):
        rows = airport_block('A', [('30', 10, 5)], [('30', 10, 5)])
        for r in rows:
            if r[1] == '30' and r[12] == 15:
                r[12] = 16
        self.assertEqual(f.parse_airports(rows, 's'), {})

    def test_wrong_block_count_fails(self):
        rows = airport_block('A', [('30', 10, 5)], [])
        with self.assertRaises(ValueError):
            f.parse_airports(rows, 's')


def rail_sheet(title, header2, data):
    rows = [['', '機関別', '民鉄'] + [''] * 5, ['年　度', '', *header2], ['', ''] + [''] * 6] + data
    return title, rows


class RailTests(unittest.TestCase):
    def sheets(self):
        s1 = rail_sheet('(ⅰ)旅客・貨物輸送数量', ['旅客'] * 6, [
            ['平成', 30.0, 100.0, 5.0, 60.0, 20.0, 80.0, 3.0],
            ['', '', '', '', -9.0, '', '', ''],
            ['令和', '元', 110.0, 6.0, 65.0, 21.0, 85.0, 4.0],
            ['', '（注）ＪＲ', '', '', '', '', '', '']])
        s2 = rail_sheet('(ⅱ)輸送人キロ・トンキロ', ['人キロ'] * 6, [['平成', 30.0, 1000.0, 50.0, 600.0, 800.0, 30.0, '']])
        return [s1, s2]

    def test_parse_rail(self):
        rows = f.parse_rail(self.sheets(), 'U')
        got = {(r['区分'], r['年']): r['値'] for r in rows}
        self.assertEqual(got[('民鉄／旅客', '2018')], '100')
        self.assertEqual(got[('民鉄／旅客', '2019')], '110')
        self.assertEqual(got[('JR（国鉄）／旅客', '2019')], '85')
        self.assertEqual(got[('民鉄＋JR（国鉄）／旅客（合計）', '2019')], '195')
        self.assertEqual(got[('民鉄／人キロ', '2018')], '1000')
        self.assertNotIn(('民鉄／旅客', '2020'), got)

    def test_missing_sheet_fails(self):
        with self.assertRaises(ValueError):
            f.parse_rail(self.sheets()[:1], 'U')


H22_TEXT = ('オンラインでの利用が可能な申請・届出等手続の全申請・届出等件数に占めるオンラ イン利用の割合（以下「オンライン利用率」という。）は、平成22年度においては、31.8％ '
            '（4億9,030万3,745件中1億5,594万3,915件）となっています。このうち、国民や - 1 - 企業による利用頻度の高い重点手続（注１）のオンライン利用率は、37.1％（4億381万 9,006件中1億4,992万227件）となっています。 '
            '前年度と比較すると、オンラインでの利用が可能な申請・届出等手続全体では、0.3 ポイント増加（21 年度 31.5％）し、重点手続については、3.6 ポイント増加（21 年度 33.5％）しています。')


class EgovTests(unittest.TestCase):
    def test_h22(self):
        rows = f.egov_rows('h22', H22_TEXT, 'U', 'T')
        got = {(r['区分'], r['年']): r['値'] for r in rows}
        self.assertEqual(got[('全申請・届出等手続（オンライン利用可能分）', '2010')], '31.8')
        self.assertEqual(got[('全申請・届出等手続（オンライン利用可能分）', '2009')], '31.5')
        self.assertEqual(got[('重点手続（71手続）', '2010')], '37.1')
        self.assertEqual(got[('重点手続（71手続）', '2009')], '33.5')
        self.assertIn('490,303,745', rows[0]['備考'])

    def test_h20(self):
        text = ('オンライン化されている手続全体の件数は 4 億 6,961 万 1,207 件で、そのうちオンラ インを利用した件数は 1 億 5,998 万 3,207 件（34.1％）となっており、 19 年度の実績 （21.9％）と比較すると')
        got = {r['年']: r['値'] for r in f.egov_rows('h20', text, 'U', 'T')}
        self.assertEqual(got, {'2008': '34.1', '2007': '21.9'})

    def test_h27_whitepaper(self):
        text = ('全申請・届出等件数 31 におけるオンライン利用率は、47.3%（オンライン利用件数は2億6,131万6,784件、前年度差1.9ポイント増加）となっている。'
                'このうち、改善促進手続 32 のオンライン利用率は、43.3％（オンライン利用件数は1億7,468万1,859件、前年度差2.1ポイント増加）')
        got = {(r['区分'], r['年']): r['値'] for r in f.egov_rows('h27', text, 'U', 'T')}
        self.assertEqual(got, {('全申請・届出等手続（オンライン利用可能分）', '2015'): '47.3', ('改善促進手続', '2015'): '43.3'})

    def test_missing_sentence_fails_and_never_guesses(self):
        with self.assertRaises(ValueError):
            f.egov_rows('h22', '無関係な文章', 'U', 'T')
        with self.assertRaises(ValueError):
            f.egov_rows('h99', H22_TEXT, 'U', 'T')

    def test_dedupe_keeps_own_year_row_and_rejects_conflict(self):
        own = {'区分': 'a', '年': '2012', '値': '41.2', '備考': '年間申請等件数'}
        prev = {'区分': 'a', '年': '2012', '値': '41.2', '備考': '同資料が記す24年度の値'}
        self.assertEqual(f.dedupe_egov([own, prev]), [own])
        self.assertEqual(f.dedupe_egov([prev, own]), [own])
        with self.assertRaises(ValueError):
            f.dedupe_egov([own, {**prev, '値': '40'}])


class StatusTests(unittest.TestCase):
    def test_status_rows_are_complete_and_all_failures(self):
        for r in f.STATUS_ROWS:
            self.assertEqual(len(r), len(f.STATUS_COLUMNS))
            self.assertEqual(r[2], '取得できず')
            self.assertTrue(r[3])


if __name__ == '__main__':
    unittest.main()
