import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_court_rulings import compare, lane_acceptance, public_judgment, ruling_kind

ROOT = Path(__file__).resolve().parents[1]


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

    def test_unconfirmed_fields_are_filled_from_newer_line(self):
        agreed, _ = compare({'x-01': case(裁判所='未確認（候補は東京地裁）', 判断の要旨='判断内容は確認できていない', 結果='棄却')},
                            {'x-01': case(裁判所='東京地方裁判所', 判断の要旨='違反しない', 結果='請求棄却')})
        self.assertEqual(agreed[0]['裁判所'], '東京地方裁判所')
        self.assertEqual(agreed[0]['判断の要旨'], '違反しない')
        self.assertEqual(agreed[0]['結果'], '棄却')

    def test_direction_buckets(self):
        self.assertEqual(ruling_kind('合憲・適法（規制維持）'), '規制維持')
        self.assertEqual(ruling_kind('侵害認定（技術側が敗訴）'), '規制維持')
        self.assertEqual(ruling_kind('無罪（規制の適用を否定）'), '規制否定')
        self.assertEqual(ruling_kind('違憲'), '規制否定')
        self.assertEqual(ruling_kind('未確認'), '')
        self.assertEqual(ruling_kind('その他（破棄差戻し。差戻審で差止め認容）'), 'その他')
        self.assertEqual(ruling_kind('その他（請求棄却。全文は読んだ。大分類の変更は未採用）'), 'その他')
        self.assertEqual(ruling_kind('違憲であるとは認められない'), '規制否定')
        self.assertEqual(ruling_kind('規制維持（違憲であるとは認められない）'), '規制維持')
        self.assertEqual(public_judgment('合憲・適法（規制維持）'), '規制維持')
        self.assertEqual(public_judgment('合憲である'), '規制維持')
        self.assertNotIn('合憲', public_judgment('合憲である'))
        self.assertEqual(
            public_judgment('合憲・適法（規制維持）（請求棄却。最高裁の憲法判断の有無は未確認）'),
            '規制維持（請求棄却。最高裁の憲法判断の有無は未確認）',
        )
        kept = 'その他（著作権侵害の一部認定。規制の合憲性は争点でない）'
        self.assertEqual(public_judgment(kept), kept)
        self.assertEqual(public_judgment('規制維持（違憲であるとは認められない）'), '規制維持（違憲であるとは認められない）')

    def test_committed_table_matches_report_and_keeps_open_rows(self):
        with (ROOT / 'data/acquired/court-rulings/rulings.csv').open(encoding='utf-8') as rulings_file:
            rulings = list(csv.DictReader(rulings_file))
        with (ROOT / 'data/acquired/court-rulings/disputed.csv').open(encoding='utf-8') as disputed_file:
            disputed = list(csv.DictReader(disputed_file))
        report = (ROOT / 'docs/reports/court-rulings.md').read_text(encoding='utf-8')
        self.assertEqual(len(rulings), 40)
        self.assertEqual(len(disputed), 8)
        self.assertEqual({r['id'] for r in rulings} & {d['id'] for d in disputed}, set())
        counts = {}
        for row in rulings:
            counts[ruling_kind(row['規制への判断'])] = counts.get(ruling_kind(row['規制への判断']), 0) + 1
        self.assertEqual(counts, {'規制維持': 23, '規制否定': 14, 'その他': 3})
        self.assertIn('一致した40件', report)
        self.assertIn('未確認の8件', report)
        self.assertNotIn('一致した24件', report)
        by_id = {r['id']: r for r in rulings}
        self.assertEqual(by_id['adm-02']['規制への判断'], 'その他（請求棄却。判示の全文は未読）')
        self.assertIn('確認していない', by_id['adm-02']['判断の要旨'])
        self.assertEqual(ruling_kind(by_id['adm-02']['規制への判断']), 'その他')
        self.assertEqual(by_id['med-04']['規制への判断'], '規制維持')
        self.assertNotIn('合憲', by_id['med-04']['規制への判断'])
        self.assertIn('原文は未確認', by_id['med-04']['判断の要旨'])
        self.assertEqual(by_id['tech-07']['判決日'], '2014-04-25')
        self.assertEqual(by_id['add-02']['規制への判断'], '規制維持')
        self.assertEqual(by_id['tech-03']['規制への判断'], '侵害認定（技術側が敗訴）')
        self.assertEqual(ruling_kind(by_id['tech-03']['規制への判断']), '規制維持')
        self.assertTrue(all('合憲・適法' not in row['規制への判断'] for row in rulings))
        for held in ('tech-01', 'tech-02', 'med-06'):
            self.assertIn(held, by_id)
        self.assertEqual(
            {d['id'] for d in disputed},
            {'add-07', 'add-07b', 'adm-04c', 'biz-03', 'med-05', 'tech-04c', 'tech-07b', 'tech-07c'},
        )

    def test_regeneration_matches_committed_table(self):
        script = ROOT / 'scripts/build_court_rulings.py'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            subprocess.run(
                [sys.executable, str(script), '--in', str(ROOT / 'data/acquired/court-rulings/lines'),
                 '--out', str(out), '--lines', 'ABCDEF'],
                check=True, cwd=ROOT,
            )
            for name in ('rulings.csv', 'disputed.csv'):
                committed = (ROOT / 'data/acquired/court-rulings' / name).read_bytes()
                self.assertEqual(committed, (out / name).read_bytes(), name)

    def test_new_lane_waits_until_two_signatures_agree(self):
        one = lane_acceptance([case(規制への判断='規制維持（違憲であるとは認められない）')])
        self.assertEqual(one['status'], 'waiting')
        self.assertFalse(one['writes_historical'])
        pair = lane_acceptance([
            case(規制への判断='規制維持（違憲であるとは認められない）'),
            case(事件番号='平成24年(行ヒ)第279号', 規制への判断='規制維持（違憲であるとは認められない）'),
        ])
        self.assertEqual(pair['status'], 'accepted')
        self.assertEqual(pair['kind'], '規制維持')
        self.assertFalse(pair['writes_historical'])
        split = lane_acceptance([
            case(規制への判断='規制維持（違憲であるとは認められない）'),
            case(規制への判断='違憲'),
        ])
        self.assertEqual(split['status'], 'waiting')


if __name__ == '__main__':
    unittest.main()
