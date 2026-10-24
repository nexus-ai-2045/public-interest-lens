import tempfile
import unittest
from pathlib import Path

from scripts import fetch_fiscal as f


def row(*cells):
    return list(cells) + [None] * (8 - len(cells))


class YearTests(unittest.TestCase):
    def test_fiscal_year_labels(self):
        self.assertEqual(f.fiscal_year_of('Ｈ元'), 1989)
        self.assertEqual(f.fiscal_year_of('R6'), 2024)
        self.assertEqual(f.fiscal_year_of('昭和42'), 1967)
        self.assertEqual(f.fiscal_year_of('令和６年度'.replace('年度', '')), 2024)

    def test_cabinet_date(self):
        self.assertEqual(f.cabinet_date('経済財政運営と改革の基本方針2020について\n令和２年７ 月 17日 \n閣議決定'), '2020-07-17')
        self.assertEqual(f.cabinet_date('平 成 27 年 6 月 30 日'), '2015-06-30')
        self.assertIsNone(f.cabinet_date('日付なし'))


class FxTests(unittest.TestCase):
    def test_dates_carry_down_and_quarter_totals_are_skipped(self):
        text = '\n'.join([
            '年,月,日,Year,Month,Day,金額(amount),売買通貨,Currency pairs',
            '平成3年,5月,13日,1991,May,13,139,米ドル売り・日本円買い,x',
            ',6月,10日,,Jun,10,211,米ドル売り・日本円買い,x',
            ',,13日,,,13,"1,213",米ドル売り・日本円買い,x',
            '平成3年4～6月期計,,,April - June 1991,,,563,,',
        ])
        got = f.parse_feio(text.encode('cp932'), 'u')
        self.assertEqual([r[0] for r in got], ['1991-05-13', '1991-06-10', '1991-06-13'])
        self.assertEqual(got[2][1], '1213')


class ExpenseTests(unittest.TestCase):
    cols = {'当初': 4, '補正': 5}

    def test_parent_total_and_children(self):
        rows = [row(None, '社会保障関係費'), row(None, '1.', '年金', None, 10, '-'), row(None, '2.', '医療', None, 5, 1),
                row(None, '計', None, None, 15, 1), row(None, '国債費', None, None, 7, '-'), row(None, '合　計', None, None, 22, 1)]
        got = [(n, p, v['当初']) for n, p, v, _ in f.expense_rows(rows, self.cols, bracket_parents=False)]
        self.assertIn(('社会保障関係費', None, 15.0), got)
        self.assertIn(('年金', '社会保障関係費', 10.0), got)
        self.assertIn(('国債費', None, 7.0), got)
        self.assertIn(('合計', None, 22.0), got)

    def test_rows_after_the_total_are_marked(self):
        rows = [row(None, '国債費', None, None, 7, '-'), row(None, '合　計', None, None, 7, '-'),
                row(None, '平成５年度決算不足補てん繰戻', None, None, '-', 5), row(None, '総　合　計', None, None, 7, 5)]
        got = [(n, out) for n, _, _, out in f.expense_rows(rows, self.cols, bracket_parents=False)]
        self.assertEqual(got, [('国債費', False), ('合計', False), ('平成5年度決算不足補てん繰戻', True), ('総合計', False)])

    def test_parent_without_total_returns_children_to_top(self):
        # 昭和60年度：「地方財政関係費」に内訳が1つだけで「計」がない
        rows = [row(None, '地方財政関係費'), row(None, None, '地方交付税交付金', None, 9, '-'), row(None, '防衛関係費', None, None, 3, 1)]
        got = [(n, p) for n, p, _, _ in f.expense_rows(rows, self.cols, bracket_parents=False)]
        self.assertEqual(got, [('地方交付税交付金', None), ('防衛関係費', None)])

    def test_dash_only_row_is_not_a_heading(self):
        rows = [row(None, '28.', '予備費', None, '－', '－'), row(None, None, '重要経費計', None, 10, 2)]
        got = [(n, p) for n, p, _, _ in f.expense_rows(rows, self.cols, bracket_parents=False)]
        self.assertEqual(got, [('重要経費計', None)])

    def test_following_nameless_row_holds_the_plain_amount(self):
        # 古い年：名前の行は括弧書き（他の経費を含めた額）、次の名前のない行が本来の額。空の欄は名前の行の額
        rows = [row(None, '治山治水対策事業費', None, None, 120, 6), row(None, None, None, None, 119, None)]
        (_, _, vals, _), = f.expense_rows(rows, self.cols, bracket_parents=False)
        self.assertEqual((vals['当初'], vals['補正']), (119.0, 6.0))

    def test_negative_nameless_row_before_total_is_ignored(self):
        cols = {'決算': 4}
        rows = [row(None, '（社会保障関係費）'), row(None, '失業対策費', None, None, 76), row(None, None, None, None, -744), row(None, '計', None, None, 741)]
        got = [(n, p, v['決算']) for n, p, v, _ in f.expense_rows(rows, cols, bracket_parents=True)]
        self.assertEqual(got, [('失業対策費', '社会保障関係費', 76.0), ('社会保障関係費', None, 741.0)])

    def test_preceding_nameless_rows_are_not_used(self):
        # 令和元・2年度：名前のない行（臨時・特別の措置を除いた額）が名前の行の前にある
        rows = [row(None, '社会保障関係費'), row(None, None, None, None, 33, 3), row(None, '計', None, None, 34, 3),
                row(None, None, None, None, 23, -1), row(None, '国債費', None, None, 23, -1)]
        got = [(n, p, v['当初']) for n, p, v, _ in f.expense_rows(rows, self.cols, bracket_parents=False)]
        self.assertEqual(got, [('社会保障関係費', None, 34.0), ('国債費', None, 23.0)])

    def test_bracket_subtotal_closes_parent(self):
        rows = [row(None, None, '(社会保障関係費)'), row(None, '1.', '生活保護費', None, 3, 1), row(None, None, '(小　計　1～6)', None, 3, 1),
                row(None, '11.', '国債費', None, 4, 0)]
        got = [(n, p) for n, p, _, _ in f.expense_rows(rows, self.cols, bracket_parents=False)]
        self.assertEqual(got, [('生活保護費', '社会保障関係費'), ('社会保障関係費', None), ('国債費', None)])


class LocalTests(unittest.TestCase):
    def test_reads_this_and_previous_year_net_totals(self):
        text = '\n'.join([
            '第11表　歳入決算額の状況,,,,,,,,',
            'その1　総　　括,,,,,,,,',
            '区分,令和6年度,,,,,,令和5年度純計額,',
            ',都道府県,,市町村,,純計額,,,',
            '地方交付税,"10,067,039",16.8,"9,867,579",13.7,"19,934,618",16.6,"19,006,956",16.3',
        ])
        got = {(r[0], r[4]): r[5] for r in f.parse_local(text.encode('cp932'), 'u')}
        self.assertEqual(got, {(2024, '地方交付税'): '19934618000000', (2023, '地方交付税'): '19006956000000'})

    def test_other_tables_are_refused(self):
        self.assertEqual(f.parse_local('第11表　団体規模別歳入の状況,,\n区分,,'.encode('cp932'), 'u'), [])


class KeepTests(unittest.TestCase):
    def test_build_without_raw_files_keeps_previous_rows(self):
        # 新しい作業環境では原本（Git の外）が無い。表を空で上書きしない
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            out.mkdir()
            (out / 'fx_interventions.csv').write_text('実施日,金額,単位,売買通貨,出典URL\n2024-04-29,59185,億円,米ドル売り・日本円買い,' + f.FEIO_CSV + '\n', encoding='utf-8')
            url = f.MOF_STAT + '19b.xlsx'
            (out / 'fiscal_flows.csv').write_text('年度,会計,段階,区分,項目,金額,単位,出典URL,備考\n2024,一般会計,当初,主要経費別,国債費,1,円,' + url + ',\n', encoding='utf-8')
            f.do_build(Path(tmp) / 'raw', out, Path(tmp) / 'manifest.csv')
            self.assertIn('2024-04-29,59185', (out / 'fx_interventions.csv').read_text(encoding='utf-8'))
            self.assertIn('2024,一般会計,当初,主要経費別,国債費,1,円', (out / 'fiscal_flows.csv').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
