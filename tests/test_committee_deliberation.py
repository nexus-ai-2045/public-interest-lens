"""委員会の審議の取り込み（scripts/fetch_committee_deliberation.py、build_committee_amend_involvements.py）の解析が決まりどおりであること。"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import fetch_committee_deliberation as F  # noqa: E402

HEADER_LOWER = """令和元年十一月二十二日（金曜日）
　　　　午前十時十五分開議
　出席委員
　　　委員長　松島みどり君
　　　理事　伊藤　忠彦君　理事　越智　隆雄君
　　　　　　井野　俊郎君　　　　石川　昭政君
　　　　…………………………………
　　　法務大臣　　　　　　　森　まさこ君
本日の会議に付した案件
　会社法の一部を改正する法律案（内閣提出第一〇号）
"""
HEADER_UPPER = """　　出席者は左のとおり。
　　　　委員長　　　　　　　　　三宅　伸吾君
　　　　理　事
　　　　　　　　　　　　　　　　白坂　亜紀君
　　　　　　　　　　　　　　　　西田　昌司君
　　　　委　員
　　　　　　　　　　　　　　　　大家　敏志君
　　　国務大臣
　　　　財務大臣
"""


def rec(order, speaker, speech, position=''):
    return {'speechOrder': order, 'speaker': speaker, 'speech': speech, 'speakerPosition': position, 'speechURL': f'https://kokkai.ndl.go.jp/txt/x/{order}'}


class CommitteeDeliberationTest(unittest.TestCase):
    def test_attendance_lower_house(self) -> None:
        self.assertEqual(F.parse_attendance(HEADER_LOWER, '衆議院'),
                         [('松島みどり', '委員長'), ('伊藤忠彦', '理事'), ('越智隆雄', '理事'), ('井野俊郎', '委員'), ('石川昭政', '委員')])

    def test_attendance_upper_house(self) -> None:
        self.assertEqual(F.parse_attendance(HEADER_UPPER, '参議院'),
                         [('三宅伸吾', '委員長'), ('白坂亜紀', '理事'), ('西田昌司', '理事'), ('大家敏志', '委員')])

    def test_kanji_number(self) -> None:
        self.assertEqual([F.kanji_num(x) for x in ('四', '十二', '二十', '百五', '3')], [4, 12, 20, 105, 3])

    def test_amendment_and_vote(self) -> None:
        bill = {'題名': '会社法の一部を改正する法律案'}
        m = {'nameOfMeeting': '法務委員会', 'nameOfHouse': '衆議院', 'date': '2019-11-22', 'issue': '第11号', 'issueID': 'X', 'meetingURL': 'u',
             'speechRecord': [
                 rec(0, '会議録情報', HEADER_LOWER),
                 rec(1, '松島みどり', '○松島委員長　これより会議を開きます。内閣提出、会社法の一部を改正する法律案を議題といたします。この際、本案に対し、越智隆雄さん外四名から、修正案が提出されております。'),
                 rec(2, '山尾志桜里', '○山尾委員　ただいま議題となりました修正案につきまして、その趣旨を御説明申し上げます。'),
                 rec(3, '松島みどり', '○松島委員長　起立総員。よって、本修正案は可決いたしました。'),
                 rec(4, '松島みどり', '○松島委員長　起立多数。よって、本案は修正議決すべきものと決しました。'),
             ]}
        r = F.analyze_meeting(m, bill)
        self.assertIsNotNone(r)
        (rc, (main, more), ex, outcome), = r['amend_calls']
        self.assertEqual((main, more, ex['speaker'], outcome), ('越智隆雄', 4, '山尾志桜里', '可決'))
        self.assertTrue(any('修正議決すべきもの' in v['speech'] for v in r['votes']))

    def test_other_bill_meeting_is_not_linked(self) -> None:
        bill = {'題名': '会社法の一部を改正する法律案'}
        m = {'nameOfMeeting': '法務委員会', 'nameOfHouse': '衆議院', 'date': 'd', 'issue': 'i', 'issueID': 'X', 'meetingURL': 'u',
             'speechRecord': [rec(0, '会議録情報', '出席委員\n　委員長　松島みどり君\n本日の会議に付した案件\n　民法の一部を改正する法律案'),
                              rec(1, '松島みどり', '○松島委員長　民法の一部を改正する法律案を議題といたします。会社法の一部を改正する法律に触れる質疑。')]}
        self.assertIsNone(F.analyze_meeting(m, bill))

    def test_merge_amends(self) -> None:
        base = {'法律ID': 'b', '題名': 't', '院': '衆議院', '委員会': 'c', '日付': 'd', '提出者の人数': 3, '修正案の結果': '', '宣告の抜粋': '', '趣旨説明の抜粋': '', '宣告のURL': 'u1', '趣旨説明のURL': ''}
        a = {**base, '提出者(筆頭)': '逢沢一郎', '趣旨説明者': ''}
        b = {**base, '提出者(筆頭)': '逢沢一郎', '趣旨説明者': '逢沢一郎', '趣旨説明の抜粋': 'x', '趣旨説明のURL': 'u2', '修正案の結果': '可決'}
        out = F.merge_amends([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]['修正案の結果'], out[0]['趣旨説明のURL']), ('可決', 'u2'))

    def test_merge_amends_keeps_names_containing_honorific_characters(self) -> None:
        base = {'法律ID': 'b', '題名': 't', '院': '衆議院', '委員会': 'c', '日付': 'd', '提出者の人数': 2, '修正案の結果': '', '宣告の抜粋': '', '趣旨説明の抜粋': '', '宣告のURL': 'u1', '趣旨説明のURL': '', '趣旨説明者': ''}
        out = F.merge_amends([{**base, '提出者(筆頭)': '畑野君枝'}])
        self.assertEqual(out[0]['提出者(筆頭)'], '畑野君枝')

    def test_merge_amends_keeps_other_days_apart(self) -> None:
        base = {'法律ID': 'b', '題名': 't', '院': '衆議院', '委員会': 'c', '提出者の人数': 3, '宣告の抜粋': '', '趣旨説明の抜粋': '', '宣告のURL': 'u1', '趣旨説明のURL': '', '提出者(筆頭)': '逢沢一郎', '趣旨説明者': '逢沢一郎'}
        a = {**base, '日付': '2000-01-01', '修正案の結果': '撤回'}
        b = {**base, '日付': '2000-01-02', '修正案の結果': '可決'}
        out = F.merge_amends([a, b])
        self.assertEqual([x['修正案の結果'] for x in out], ['撤回', '可決'])

    def test_published_csv_if_present(self) -> None:
        d = ROOT / 'data/acquired/committee-deliberation'
        p = d / 'amendments.csv'
        if not p.exists():
            self.skipTest('取り込み前')
        for r in csv.DictReader(p.open(encoding='utf-8', newline='')):
            self.assertTrue(r['宣告のURL'].startswith('https://kokkai.ndl.go.jp/'), r)
            self.assertIn(r['修正案の結果'], ('可決', '否決', '撤回', ''))


def _rec(order, speaker, speech):
    return {'speechOrder': order, 'speaker': speaker, 'speech': speech, 'speechURL': f'u{order}', 'speakerPosition': '委員長' if speaker.startswith('委員長') else ''}


def _meeting(recs, agenda='本日の会議に付した案件\n甲法の一部を改正する法律案\n乙法の一部を改正する法律案'):
    head = _rec(0, '会議録情報', '出席委員\n委員長 山田一郎君\n' + agenda)
    return {'nameOfHouse': '衆議院', 'nameOfMeeting': '甲委員会', 'date': '2000-01-01', 'issue': '1', 'issueID': 'x', 'speechRecord': [head] + recs}


def _ch(o, s):
    return _rec(o, '委員長 山田一郎', '○委員長（山田一郎君）' + s)


KOU = {'題名': '甲法の一部を改正する法律案'}
OTSU = {'題名': '乙法の一部を改正する法律案'}


class CommitteeFlowTest(unittest.TestCase):
    """法案ごとの議事の区間と、修正案・採決・附帯決議の対応づけ（別の法案の結果を混ぜない）。"""

    def test_amendment_only_from_this_bills_segment_and_outcome_matched(self) -> None:
        recs = [
            _ch(1, '乙法の一部を改正する法律案を議題といたします。'),
            _ch(2, '田中太郎君外二名から、乙法の一部を改正する法律案に対する修正案が提出されております。'),
            _ch(3, '甲法の一部を改正する法律案を議題といたします。'),
            _ch(4, '鈴木花子君外三名から、甲法の一部を改正する法律案に対する修正案、佐藤次郎君外四名から、甲法の一部を改正する法律案に対する修正案が提出されております。'),
            _rec(5, '鈴木花子', '○鈴木花子君 ただいま議題となりました修正案につきまして、提出者を代表して、その趣旨を御説明申し上げます。'),
            _ch(6, 'まず、佐藤次郎君外四名提出の修正案について採決いたします。本修正案は否決されました。'),
            _ch(7, '次に、鈴木花子君外三名提出の修正案について採決いたします。本修正案は可決されました。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        got = {F.norm_name(m): (ex['speaker'] if ex else '', oc) for _, (m, _), ex, oc in r['amend_calls']}
        self.assertEqual(set(got), {'鈴木花子', '佐藤次郎'})  # 乙法の田中氏は入らない
        self.assertEqual(got['鈴木花子'], ('鈴木花子', '可決'))
        self.assertEqual(got['佐藤次郎'], ('', '否決'))  # 説明者は確かでないので空

    def test_votes_are_limited_to_this_bills_segment(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。'),
            _ch(2, '採決いたします。本案は原案のとおり可決すべきものと決しました。'),
            _ch(3, '乙法の一部を改正する法律案を議題といたします。'),
            _ch(4, '採決いたします。本案は修正議決すべきものと決しました。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([v['speech'] for v in r['votes']], [recs[1]['speech']])

    def test_resolutions_are_limited_to_this_bills_segment(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。'),
            _ch(2, '採決いたします。本案は原案のとおり可決すべきものと決しました。'),
            _ch(3, '乙法の一部を改正する法律案を議題といたします。'),
            _rec(4, '鈴木花子', '○鈴木花子君 附帯決議案につきまして、提出者を代表して案文を朗読し、趣旨を御説明申し上げます。'),
            _ch(5, '採決いたします。本動議のとおり附帯決議を付することに賛成の諸君の起立を求めます。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertFalse(r['resolutions'] or r['reso_decided'])
        r2 = F.analyze_meeting(_meeting(recs), OTSU)
        self.assertEqual((len(r2['resolutions']), len(r2['reso_decided'])), (1, 1))

    def test_segment_continues_over_unnamed_joint_declaration(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。'),
            _ch(2, 'この際、本案及び修正案を一括して議題といたします。田中太郎君外二名から修正案が提出されております。'),
            _ch(3, '田中太郎君外二名提出の修正案について採決いたします。本修正案は可決されました。'),
            _ch(4, '乙法の一部を改正する法律案を議題といたします。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([(F.norm_name(m), oc) for _, (m, _), _, oc in r['amend_calls']], [('田中太郎', '可決')])

    def test_results_before_next_agenda_stay_with_the_original_bill(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。田中太郎君外二名から修正案が提出されております。'),
            _ch(2, '起立多数。よって、本修正案は可決されました。起立多数。よって、本案は修正議決すべきものと決しました。次に、乙法の一部を改正する法律案を議題といたします。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual((len(r['votes']), [oc for *_, oc in r['amend_calls']]), (1, ['可決']))
        r2 = F.analyze_meeting(_meeting(recs), OTSU)
        self.assertFalse(r2['votes'] or r2['amend_calls'])  # 甲の結果が乙に混ざらない

    def test_committee_chairs_amendment_goes_to_the_chair_of_that_day(self) -> None:
        recs = [_ch(1, '甲法の一部を改正する法律案を議題といたします。この際、本案に対し、委員長から修正案を提出いたします。')]
        recs[0]['speaker'] = '翌日花子'
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([m for _, (m, _), _, _ in r['amend_calls']], ['翌日花子'])
        recs[0]['speaker'] = '副委員長 代理太郎'
        recs[0]['speakerPosition'] = '委員長代理'
        r = F.analyze_meeting(_meeting(recs), KOU)  # 代理が宣告したときは、その会議の出席名簿の委員長
        self.assertEqual([m for _, (m, _), _, _ in r['amend_calls']], ['山田一郎'])

    def test_committee_chairs_amendment_result_is_matched(self) -> None:
        recs = [_ch(1, '甲法の一部を改正する法律案を議題といたします。この際、本案に対し、委員長から修正案を提出いたします。'),
                _ch(2, '委員長提出の修正案について採決いたします。本修正案は可決されました。')]
        recs[0]['speaker'] = '山田一郎'
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([(m, oc) for _, (m, _), _, oc in r['amend_calls']], [('山田一郎', '可決')])

    def test_solo_amendment_next_to_joint_one_is_kept(self) -> None:
        recs = [_ch(1, '甲法の一部を改正する法律案を議題といたします。この際、本案に対し、田中太郎君外二名から修正案並びに鈴木花子君から修正案が提出されております。')]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual(sorted(F.norm_name(m) for _, (m, _), _, _ in r['amend_calls']), ['田中太郎', '鈴木花子'])

    def test_representative_motion_is_explanation_of_the_announced_amendment(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。この際、本案に対し、田中太郎君から修正案が提出されております。提出者から趣旨の説明を求めます。佐藤次郎君。'),
            _rec(2, '佐藤次郎', '○佐藤次郎君 修正の動議を提出いたします。その趣旨について御説明申し上げます。'),
            _ch(3, '田中太郎君提出の修正案について採決いたします。本修正案は可決されました。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([(F.norm_name(m), ex['speaker'] if ex else '', oc) for _, (m, _), ex, oc in r['amend_calls']], [('田中太郎', '佐藤次郎', '可決')])

    def test_independent_motion_is_kept_as_separate_amendment(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。この際、本案に対し、田中太郎君から修正案が提出されております。提出者から趣旨の説明を求めます。田中太郎君。'),
            _rec(2, '田中太郎', '○田中太郎君 ただいま議題となりました修正案につきまして、その趣旨を御説明申し上げます。'),
            _rec(3, '佐藤次郎', '○佐藤次郎君 これとは別に、修正の動議を提出いたします。その趣旨について御説明申し上げます。'),
            _ch(4, '佐藤次郎君提出の修正案について採決いたします。本修正案は否決されました。田中太郎君提出の修正案について採決いたします。本修正案は可決されました。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        got = {F.norm_name(m): (ex['speaker'] if ex else '', oc) for _, (m, _), ex, oc in r['amend_calls']}
        self.assertEqual(got, {'田中太郎': ('田中太郎', '可決'), '佐藤次郎': ('佐藤次郎', '否決')})

    def test_vote_method_comes_from_the_bills_own_vote(self) -> None:
        text = '起立少数。よって、本修正案は否決されました。次に、原案について採決いたします。起立多数。よって、本案は原案のとおり可決すべきものと決しました。'
        method, excerpt = F.vote_fields(text, '可決すべきもの')
        self.assertEqual(method, '起立多数')
        self.assertNotIn('修正案', excerpt)

    def test_solo_proposer_of_another_bill_is_not_added(self) -> None:
        recs = [_ch(1, '甲法の一部を改正する法律案を議題といたします。この際、甲法の一部を改正する法律案に対し、田中太郎君外二名から修正案、乙法の一部を改正する法律案に対し、鈴木花子君から修正案が提出されております。')]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([F.norm_name(m) for _, (m, _), _, _ in r['amend_calls']], ['田中太郎'])

    def test_withdrawal_of_amendment_is_not_the_bills_vote_result(self) -> None:
        recs = [_ch(1, '甲法の一部を改正する法律案を議題といたします。'),
                _ch(2, '修正案の撤回を許可することに決しました。次に、原案について採決いたします。起立多数。よって、本案は原案のとおり可決すべきものと決しました。')]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual(len(r['votes']), 1)
        self.assertEqual(F.RESULT_RE.search(r['votes'][0]['speech']).group(1), '可決すべきもの')

    def test_long_hiragana_proposer_name(self) -> None:
        recs = [_ch(1, '甲法の一部を改正する法律案を議題といたします。この際、本案に対し、とかしきなおみ君外五名から、修正案が提出されております。')]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual([F.norm_name(m) for _, (m, _), _, _ in r['amend_calls']], ['とかしきなおみ'])

    def test_bill_resumed_later_in_same_meeting_keeps_both_segments(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。'),
            _ch(2, '乙法の一部を改正する法律案を議題といたします。'),
            _ch(3, '再び、甲法の一部を改正する法律案を議題といたします。田中太郎君外二名から修正案が提出されております。'),
            _ch(4, '起立多数。よって、本修正案は可決されました。起立多数。よって、本案は修正議決すべきものと決しました。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual((len(r['votes']), [oc for *_, oc in r['amend_calls']]), (1, ['可決']))

    def test_resolution_motion_for_this_bill_does_not_end_segment(self) -> None:
        recs = [
            _ch(1, '甲法の一部を改正する法律案を議題といたします。'),
            _ch(2, '採決いたします。本案は原案のとおり可決すべきものと決しました。'),
            _ch(3, 'この際、本案に対する附帯決議案を議題といたします。'),
            _rec(4, '鈴木花子', '○鈴木花子君 附帯決議案につきまして、提出者を代表して案文を朗読し、趣旨を御説明申し上げます。'),
            _ch(5, '採決いたします。本動議のとおり附帯決議を付することに賛成の諸君の起立を求めます。'),
        ]
        r = F.analyze_meeting(_meeting(recs), KOU)
        self.assertEqual((len(r['resolutions']), len(r['reso_decided'])), (1, 1))

    def test_amend_involvements_keep_adopted_row_and_wait_for_confirmation(self) -> None:
        from scripts import build_committee_amend_involvements as B
        from scripts.allocation_involvements import HEADER

        def w(path, header, rows):
            with open(path, 'w', encoding='utf-8', newline='') as f:
                cw = csv.DictWriter(f, header)
                cw.writeheader()
                cw.writerows(rows)
        base = {'法律ID': '閣法-1-1', '題名': 't', '院': '衆議院', '委員会': 'c', '提出者(筆頭)': '山口太郎', '趣旨説明者': '', '宣告のURL': 'https://kokkai.ndl.go.jp/x', '趣旨説明のURL': ''}
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            w(tmp / 'amendments.csv', list(base) + ['日付', '修正案の結果'], [{**base, '日付': '2007-12-04', '修正案の結果': ''}, {**base, '日付': '2007-12-06', '修正案の結果': '可決'}])
            w(tmp / 'inv.csv', HEADER, [{h: '' for h in HEADER} | {'法律ID': '閣法-1-1', '立場の根拠': 'x', '行動': 'other', '氏名': 'a'}])
            w(tmp / 'persons.csv', ['人物ID', '氏名', '別表記'], [])
            with mock.patch.object(B, 'AMENDMENTS', tmp / 'amendments.csv'), mock.patch.object(B, 'SOURCES', [tmp / 'inv.csv']), \
                    mock.patch.object(B, 'PERSONS', tmp / 'persons.csv'), mock.patch.object(B, 'CONFIRMED', tmp / 'confirmed.csv'):
                rows = B.build()
                self.assertEqual((len(rows), rows[0]['日付'], rows[0]['算入']), (1, '2007-12-06', 'いいえ'))  # 可決の行が残り、確認前は数えない
                w(tmp / 'confirmed.csv', ['法律ID', '院', '氏名', '系統A', '系統B'], [{'法律ID': '閣法-1-1', '院': '衆議院', '氏名': '山口太郎', '系統A': '確認', '系統B': '確認'}])
                self.assertEqual(B.build()[0]['算入'], 'はい')


if __name__ == '__main__':
    unittest.main()
