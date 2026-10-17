"""scripts/allocation_involvements.py の数える条件を、架空の名前と架空の資料で確かめる。実在の人物・会議録は使わない。"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import allocation_involvements as m

URL = 'https://example.test/minutes/'


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class AllocationInvolvementsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.collect, self.stance, self.votes, self.cabinet = root / 'collect', root / 'stance', root / 'votes', root / 'cabinet.csv'
        self.collect.mkdir()
        self.stance.mkdir()
        inv = [
            {'氏名': '甲野 太郎', '院': '衆議院', '行動': 'decide', '当時の肩書': '架空大臣', '日付': '2001-03-01', '証拠URL': URL + '1'},
            {'氏名': '乙川　花子', '院': '参議院', '行動': 'chair', '当時の肩書': '委員長', '日付': '2001-03-10', '証拠URL': URL + '2'},
            {'氏名': '丙山次郎', '院': '参議院', '行動': 'question', '当時の肩書': None, '日付': '2001-03-09', '証拠URL': URL + '3'},
            {'氏名': '丁田三郎', '院': '衆議院', '行動': 'question', '当時の肩書': None, '日付': '2001-03-02', '証拠URL': URL + '4'},
            {'氏名': '戊井四郎', '院': '衆議院', '行動': 'question', '当時の肩書': None, '日付': '2001-03-02', '証拠URL': URL + '5'},
            {'氏名': '己原五郎', '院': '参議院', '行動': 'question', '当時の肩書': None, '日付': '2001-03-09', '証拠URL': URL + '6'},
            {'氏名': '庚野六郎', '院': '衆議院', '行動': 'amend', '当時の肩書': '理事（委員長報告に記載）', '日付': '2001-03-02', '証拠URL': ''},
        ]
        (self.collect / '閣法-151-9.json').write_text(json.dumps({'id': '閣法-151-9', 'title': '架空振興法案', 'involvements': inv}, ensure_ascii=False), encoding='utf-8')
        a = [{'氏名': '丙山次郎', '立場': '支持'}, {'氏名': '丁田三郎', '立場': '支持'}, {'氏名': '戊井四郎', '立場': '反対'}, {'氏名': '己原五郎', '立場': '支持'}]
        b = [{'氏名': '丙山次郎', '立場': '支持'}, {'氏名': '丁田三郎', '立場': '中立'}, {'氏名': '戊井四郎', '立場': '反対'}, {'氏名': '己原五郎', '立場': '支持'}]
        (self.stance / '閣法-151-9.lineA.json').write_text(json.dumps(a, ensure_ascii=False), encoding='utf-8')
        (self.stance / '閣法-151-9.lineB.json').write_text(json.dumps(b, ensure_ascii=False), encoding='utf-8')
        write_csv(self.votes / 'votes_index.csv', ['投票ID', '回次', '投票日', '議案名', '集計_賛成', '集計_反対', '集計_投票なし', '出典URL'], [
            ['151-0320-v001', '151', '2001-03-20', '日程第１ 架空振興法案（内閣提出、衆議院送付）', '3', '1', '0', 'https://example.test/vote/1'],
            ['151-0320-v002', '151', '2001-03-20', '日程第２ 架空振興法の一部を改正する法律案（内閣提出）', '4', '0', '0', 'https://example.test/vote/2'],
        ])
        write_csv(self.votes / 'members.csv', ['議員ID', '回次', '議員名', '会派'], [
            ['1', '151', '乙川花子', 'A会'], ['2', '151', '丙山次郎', 'B会'], ['3', '151', '己原五郎', 'A会'], ['4', '151', '辛田七子', 'A会'], ['5', '151', '辛田七子', 'C会'],
        ])
        write_csv(self.votes / 'ballots' / 'ballots_151.csv', ['投票ID', '議員ID', '賛否'], [
            ['151-0320-v001', '1', 'Y'], ['151-0320-v001', '2', 'Y'], ['151-0320-v001', '3', 'N'], ['151-0320-v001', '5', 'Y'], ['151-0320-v002', '3', 'Y'],
        ])
        write_csv(self.cabinet, ['内閣名', '区分', '氏名', '役職', '就任日_西暦', '退任日_西暦'], [
            ['架空内閣', '閣僚', '甲野 太郎', '架空大臣', '2000-07-04', '2001-04-26'],
            ['架空内閣', '閣僚', '辛田 七子', '内閣官房副長官', '2000-07-04', '2001-04-26'],
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        rows, notes = m.build(self.collect, self.stance, self.votes, self.cabinet)
        return {(r['氏名'], r['行動']): r for r in rows}, notes

    def test_name_normalization_removes_spaces_and_honorifics(self):
        self.assertEqual(m.normalize_name('甲野 太郎君'), '甲野太郎')
        self.assertEqual(m.normalize_name('乙川　花子 議員'), '乙川花子')

    def test_counting_rules(self):
        rows, _ = self.build()
        self.assertEqual(rows[('甲野太郎', 'decide')]['立場区分'], 'minister_or_party_exec')
        self.assertEqual(rows[('乙川花子', 'chair')]['立場区分'], 'vice_minister_or_chair')
        self.assertEqual(rows[('丙山次郎', 'question')]['算入'], 'はい')
        self.assertIn('一致しない', rows[('丁田三郎', 'question')]['除外理由'])
        self.assertIn('反対', rows[('戊井四郎', 'question')]['除外理由'])
        # 支持の質疑でも、参議院本会議で反対した人は数えない。
        self.assertIn('反対票', rows[('己原五郎', 'question')]['除外理由'])
        self.assertEqual(rows[('庚野六郎', 'amend')]['除外理由'], '証拠URLが無い')
        # 「委員長報告」は委員長の立場ではない。
        self.assertEqual(rows[('庚野六郎', 'amend')]['立場区分'], 'other')

    def test_votes_come_only_from_the_matching_plenary_vote(self):
        rows, notes = self.build()
        votes = {k[0]: r for k, r in rows.items() if k[1] == 'vote'}
        self.assertEqual(sorted(votes), sorted(['乙川花子', '丙山次郎', '辛田七子']))
        self.assertEqual(votes['丙山次郎']['証拠URL'], 'https://example.test/vote/1')
        # 委員長は採決でも委員長の立場、内閣官房副長官は大臣ではない。
        self.assertEqual(votes['乙川花子']['立場区分'], 'vice_minister_or_chair')
        self.assertEqual(votes['辛田七子']['立場区分'], 'vice_minister_or_chair')
        self.assertTrue(any('151-0320-v001' in n['内容'] for n in notes))

    def test_missing_stance_files_exclude_questions(self):
        (self.stance / '閣法-151-9.lineB.json').unlink()
        rows, notes = self.build()
        self.assertIn('立場の判定ファイルが無い', rows[('丙山次郎', 'question')]['除外理由'])
        self.assertTrue(any(n['種類'] == '立場の判定なし' for n in notes))


if __name__ == '__main__':
    unittest.main()
