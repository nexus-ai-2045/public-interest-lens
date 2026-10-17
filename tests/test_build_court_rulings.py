import unittest

from scripts.build_court_rulings import compare, ruling_kind


def case(**kw):
    base = {'id': 'x-01', '通称': '例', '判決日': '2013-01-11', '事件番号': '平成24(行ヒ)279',
            '規制への判断': '違法・無効', '判例URL': 'https://www.courts.go.jp/hanrei/82895/detail2/index.html',
            '関連URL': ['https://www.mhlw.go.jp/a']}
    base.update(kw)
    return base


class BuildCourtRulingsTest(unittest.TestCase):
    def test_agrees_when_date_number_and_direction_match(self):
        agreed, disputed = compare({'x-01': case()}, {'x-01': case(事件番号='平成24（行ヒ）279', 規制への判断='省令は違法で無効')})
        self.assertEqual(len(agreed), 1)
        self.assertEqual(disputed, [])
        self.assertIn('2系統一致', agreed[0]['確認状況'])
        self.assertEqual(agreed[0]['関連URL'], 'https://www.mhlw.go.jp/a')

    def test_mismatch_and_unconfirmed_go_to_disputed(self):
        agreed, disputed = compare(
            {'x-01': case(), 'x-02': case(id='x-02', 判決日='未確認'), 'x-03': case(id='x-03')},
            {'x-01': case(判決日='2013-01-12'), 'x-02': case(id='x-02')},
        )
        self.assertEqual(agreed, [])
        reasons = {d['id']: d['理由'] for d in disputed}
        self.assertEqual(reasons['x-01'], '判決日が不一致')
        self.assertEqual(reasons['x-02'], '判決日が未確認')
        self.assertEqual(reasons['x-03'], '片系統のみ')

    def test_third_line_can_settle_and_case_numbers_normalize(self):
        agreed, disputed = compare({'x-01': case()}, {'x-01': case(判決日='2013-01-12')},
                                   {'x-01': case(事件番号='平成24年(行ヒ)第279号')})
        self.assertEqual(disputed, [])
        self.assertIn('系統A・C', agreed[0]['確認状況'])

    def test_direction_buckets(self):
        self.assertEqual(ruling_kind('合憲・適法（規制維持）'), '規制維持')
        self.assertEqual(ruling_kind('侵害認定（技術側が敗訴）'), '規制維持')
        self.assertEqual(ruling_kind('無罪（規制の適用を否定）'), '規制否定')
        self.assertEqual(ruling_kind('違憲'), '規制否定')
        self.assertEqual(ruling_kind('未確認'), '')
        self.assertEqual(ruling_kind('その他（破棄差戻し。差戻審で差止め認容）'), 'その他')


if __name__ == '__main__':
    unittest.main()
