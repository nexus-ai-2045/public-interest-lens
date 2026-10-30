"""scripts/person_ids.py の人物ID を、架空の名前と架空の名簿で確かめる。実在の人物は使わない。"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import allocation_involvements as ai
from scripts import person_ids as pi

URL = 'https://example.test/minutes/'
ROSTER_HEADER = ['院', '氏名', '本名', '読み', '会派', '選挙区']


def roster_row(house, name, reading, party, district):
    return {'院': house, '氏名': name, '本名': '', '読み': reading, '会派': party, '選挙区': district}


ROSTER = [
    roster_row('衆議院', '高瀬 真琴', 'たかせ まこと', 'ア党', '東京1'),
    roster_row('衆議院', '山川 誠', 'やまかわ まこと', 'ア党', '福島2'),
    roster_row('参議院', '山川 誠', 'やまかわ まこと', 'イ党', '比例'),
    roster_row('参議院', '斉木 花', 'さいき はな', 'ア党', '比例'),
    roster_row('衆議院', '斎木 花', 'さいき はな', 'イ党', '大阪3'),
]
INV_HEADER = ai.HEADER


def inv(law, name, house, action='decide', counted='はい', reason='', pos='other', why='', date='2020-01-01'):
    return {'法律ID': law, '題名': '架空法', '氏名': name, '氏名_原表記': name, '院': house, '行動': action, '当時の肩書': '', '立場区分': pos,
            '立場の根拠': why, '日付': date, '証拠URL': URL + '1', '系統A': '', '系統B': '', '参院本会議の賛否': '', '算入': counted, '除外理由': reason, '人物ID': ''}


class PersonIdsTest(unittest.TestCase):
    def setUp(self):
        self.cabinet = [{'内閣名簿': '', '内閣名': '架空内閣', '区分': '大臣政務官', '氏名': '髙瀬 真琴', '役職': '架空政務官',
                         '就任日_西暦': '2019-01-01', '退任日_西暦': '2021-01-01'}]
        self.ledger = pi.build_ledger(ROSTER, self.cabinet)

    def test_canonical_merges_only_font_variants_of_the_same_person(self):
        self.assertEqual(pi.canonical('髙瀬 真琴君'), '高瀬真琴')
        self.assertEqual(pi.canonical('田中和德'), pi.canonical('田中和徳'))
        self.assertEqual(pi.canonical('宮﨑一郎'), pi.canonical('宮崎一郎'))

    def test_different_characters_are_not_merged(self):
        # 斉・斎・齋・齊は別の姓なので寄せない。
        names = ['斉木花', '斎木花', '齋木花', '齊木花']
        self.assertEqual(len({pi.canonical(n) for n in names}), 4)
        self.assertEqual(self.ledger.resolve('斉木花')[0], '斉木花')
        self.assertEqual(self.ledger.resolve('斎木花')[0], '斎木花')
        self.assertFalse(self.ledger.is_split('斉木花'))

    def test_same_name_in_both_houses_is_split_and_only_primary_sources_decide(self):
        self.assertTrue(self.ledger.is_split('山川誠'))
        # 行の院（発言した会議の院）では決めない。
        self.assertEqual(self.ledger.resolve('山川 誠', 'L1', URL + '1'), ('', pi.UNRESOLVED))
        # 参議院の投票記録の行も、台帳の院は今の院だけ（院を移った人がいる）なので、院では決めない。
        self.assertEqual(self.ledger.resolve('山川誠', sangiin_vote=True), ('', pi.UNRESOLVED))
        # 明示の対応表に載った行だけが、その人物IDに結ばれる。
        self.ledger.overrides = {('L1', URL + '1'): '山川誠（衆・福島2）', ('L1', URL + '2'): '別人（衆・x）'}
        self.assertEqual(self.ledger.resolve('山川誠', 'L1', URL + '1'), ('山川誠（衆・福島2）', ''))
        self.assertEqual(self.ledger.resolve('山川誠', 'L1', URL + '2'), ('', pi.UNRESOLVED))
        # 台帳に無い名前は寄せた氏名がそのまま人物ID。
        self.assertEqual(self.ledger.resolve('架空 太郎'), ('架空太郎', ''))

    def test_resolving_the_person_does_not_restore_rows_excluded_for_stance(self):
        row = dict(inv('L1', '山川誠', '衆議院', action='question'), 算入='いいえ', 除外理由='2系統の立場が一致しない（A:支持、B:反対。ADR 0007）')
        self.ledger.overrides = {('L1', URL + '1'): '山川誠（衆・福島2）'}
        _, out = ai.annotate([row], self.ledger, ai.Cabinet(self.cabinet))
        self.assertEqual((out[0]['人物ID'], out[0]['算入']), ('山川誠（衆・福島2）', 'いいえ'))
        self.assertIn('一致しない', out[0]['除外理由'])
        self.ledger.overrides = {}

    def test_ledger_ids_are_unique_and_aliases_gathered(self):
        self.assertEqual(self.ledger.persons['高瀬真琴'].aliases, {'髙瀬真琴'})
        self.assertEqual(self.ledger.undecided, [])
        ids = [p.id for p in self.ledger.persons.values()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_cabinet_position_matches_across_font_variants(self):
        cabinet = ai.Cabinet(self.cabinet)
        self.assertEqual(cabinet.position_at(pi.canonical('高瀬真琴'), '2020-06-01')[0], 'vice_minister_or_chair')

    def test_annotate_sets_person_id_and_excludes_undecidable_rows(self):
        vote = dict(inv('L1', '山川誠', '参議院', action='vote'), 証拠URL='https://www.sangiin.go.jp/vote/1')
        rows = [inv('L1', '山川誠', '衆議院'), inv('L1', '山川誠', ''), inv('L1', '高瀬真琴', '衆議院'), vote]
        # 院が衆議院でも参議院でも、会議の院では決めない。
        _, out = ai.annotate(rows, self.ledger, ai.Cabinet(self.cabinet))
        self.assertEqual([r['人物ID'] for r in out], ['', '', '高瀬真琴', ''])
        self.assertEqual(out[0]['除外理由'], '同姓同名で人物を決められない')
        self.assertEqual([r['算入'] for r in out], ['いいえ', 'いいえ', 'はい', 'いいえ'])
        # 対応表に載せた行は決まり、算入に戻る（流し直しても同じ）。
        self.ledger.overrides = {('L1', URL + '1'): '山川誠（衆・福島2）'}
        _, out = ai.annotate(out, self.ledger, ai.Cabinet(self.cabinet))
        self.assertEqual([r['人物ID'] for r in out], ['山川誠（衆・福島2）', '山川誠（衆・福島2）', '高瀬真琴', ''])
        self.assertEqual([r['算入'] for r in out], ['はい', 'はい', 'はい', 'いいえ'])
        out[1]['算入'], out[1]['除外理由'] = 'いいえ', '同姓同名で人物を決められない'
        self.ledger.overrides = {}
        _, out = ai.annotate(rows, self.ledger, ai.Cabinet(self.cabinet))
        # 旧字の髙で載っている内閣名簿の役職が、高の行にも付く。
        self.assertEqual(out[2]['立場区分'], 'vice_minister_or_chair')
        # 分けた名前には内閣名簿の役職を付けない。
        cab = self.cabinet + [dict(self.cabinet[0], 氏名='山川 誠', 役職='架空副大臣', 区分='副大臣')]
        _, out2 = ai.annotate([vote], self.ledger, ai.Cabinet(cab))
        self.assertEqual(out2[0]['立場区分'], 'other')
        # 流し直しても同じ結果。
        again, out3 = ai.annotate(out, self.ledger, ai.Cabinet(self.cabinet))
        self.assertEqual(again, 0)
        self.assertEqual(out3, out)

    def test_build_uses_roster_and_marks_undecidable_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'collect').mkdir()
            (root / 'stance').mkdir()
            (root / 'votes' / 'ballots').mkdir(parents=True)
            invs = [
                {'氏名': '山川 誠', '院': '衆議院', 'ordinal': 0, '行動': 'decide', '当時の肩書': '', '日付': '2020-01-01', '証拠URL': URL + '1'},
                {'氏名': '山川 誠', '院': '', '行動': 'decide', '当時の肩書': '', '日付': '2020-01-01', '証拠URL': URL + '2'},
                {'氏名': '髙瀬 真琴', '院': '衆議院', '行動': 'decide', '当時の肩書': '', '日付': '2020-02-01', '証拠URL': URL + '3'},
            ]
            (root / 'collect' / '閣法-151-9.json').write_text(json.dumps({'id': '閣法-151-9', 'title': '架空法', 'involvements': invs}, ensure_ascii=False), encoding='utf-8')

            def write(path, header, rows):
                with path.open('w', encoding='utf-8', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    w.writerows(rows)

            write(root / 'votes' / 'votes_index.csv', ['投票ID', '回次', '投票日', '議案名', '集計_賛成', '集計_反対', '集計_投票なし', '出典URL'], [])
            write(root / 'votes' / 'members.csv', ['議員ID', '回次', '議員名', '会派'], [])
            write(root / 'cabinet.csv', ['内閣名', '区分', '氏名', '役職', '就任日_西暦', '退任日_西暦'], [['架空内閣', '大臣政務官', '髙瀬 真琴', '架空政務官', '2019-01-01', '2021-01-01']])
            write(root / 'roster.csv', ROSTER_HEADER, [[r[h] for h in ROSTER_HEADER] for r in ROSTER])
            write(root / 'overrides.csv', pi.OVERRIDES_HEADER, [['閣法-151-9', URL + '1', '山川誠（衆・福島2）', 'https://example.test/member/1']])
            rows, _ = ai.build(root / 'collect', root / 'stance', root / 'votes', root / 'cabinet.csv', roster_csv=root / 'roster.csv', overrides_csv=root / 'overrides.csv')
            plain, _ = ai.build(root / 'collect', root / 'stance', root / 'votes', root / 'cabinet.csv', roster_csv=root / 'roster.csv')
        # 会議の院が衆議院でも、対応表に載せた行だけが人物IDに結ばれる。
        self.assertEqual([r['人物ID'] for r in plain], ['', '', '高瀬真琴'])
        self.assertEqual([r['人物ID'] for r in rows], ['山川誠（衆・福島2）', '', '高瀬真琴'])
        self.assertEqual([r['算入'] for r in rows], ['はい', 'いいえ', 'はい'])
        self.assertEqual(rows[1]['除外理由'], '同姓同名で人物を決められない')
        # 髙/高で内閣名簿と一致して、役職が付く。氏名は同じ人物IDで1つにそろう。
        self.assertEqual(rows[2]['立場区分'], 'vice_minister_or_chair')
        self.assertEqual(rows[2]['氏名'], '高瀬真琴')

    def test_build_restores_namesake_vote_from_overrides(self):
        vote_url = 'https://example.test/vote/1'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'collect').mkdir()
            (root / 'stance').mkdir()
            (root / 'votes' / 'ballots').mkdir(parents=True)
            (root / 'collect' / '閣法-151-9.json').write_text(json.dumps({'id': '閣法-151-9', 'title': '架空法', 'involvements': []}, ensure_ascii=False), encoding='utf-8')

            def write(path, header, rows):
                with path.open('w', encoding='utf-8', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    w.writerows(rows)

            write(root / 'votes' / 'votes_index.csv', ['投票ID', '回次', '投票日', '議案名', '集計_賛成', '集計_反対', '集計_投票なし', '出典URL'],
                  [['V1', '151', '2020-03-01', '架空法', '1', '0', '0', vote_url]])
            write(root / 'votes' / 'members.csv', ['議員ID', '回次', '議員名', '会派'], [['S1', '151', '山川 誠', 'イ党']])
            write(root / 'votes' / 'ballots' / 'ballots_151.csv', ['投票ID', '議員ID', '賛否'], [['V1', 'S1', 'Y']])
            write(root / 'cabinet.csv', ['内閣名', '区分', '氏名', '役職', '就任日_西暦', '退任日_西暦'], [])
            write(root / 'roster.csv', ROSTER_HEADER, [[r[h] for h in ROSTER_HEADER] for r in ROSTER])
            write(root / 'overrides.csv', pi.OVERRIDES_HEADER, [['閣法-151-9', vote_url, '山川誠（参・比例）', 'https://example.test/member/2']])
            plain, _ = ai.build(root / 'collect', root / 'stance', root / 'votes', root / 'cabinet.csv', roster_csv=root / 'roster.csv')
            rows, _ = ai.build(root / 'collect', root / 'stance', root / 'votes', root / 'cabinet.csv', roster_csv=root / 'roster.csv', overrides_csv=root / 'overrides.csv')
            # 同じ回次に同じ氏名の議員IDが2つあると、対応表がどちらの票を指すか分からないので作らない。
            write(root / 'votes' / 'members.csv', ['議員ID', '回次', '議員名', '会派'], [['S1', '151', '山川 誠', 'イ党'], ['S2', '151', '山川 誠', 'ウ党']])
            write(root / 'votes' / 'ballots' / 'ballots_151.csv', ['投票ID', '議員ID', '賛否'], [['V1', 'S2', 'Y']])
            two, _ = ai.build(root / 'collect', root / 'stance', root / 'votes', root / 'cabinet.csv', roster_csv=root / 'roster.csv', overrides_csv=root / 'overrides.csv')
        self.assertEqual(two, [])
        # 同姓同名の賛成票は、対応表に (法律ID, 投票の出典URL) があるときだけ、その人の投票として作る。
        self.assertEqual([r for r in plain if r['行動'] == 'vote'], [])
        self.assertEqual([(r['行動'], r['人物ID'], r['算入']) for r in rows], [('vote', '山川誠（参・比例）', 'はい')])


class StablePersonIdsTest(unittest.TestCase):
    def previous_of(self, ledger):
        return [{'人物ID': q.id, '氏名': q.name, '読み': q.reading, '院': q.house, '選挙区': q.district, '別表記': ''} for q in ledger.persons.values()]

    def test_ids_and_split_survive_one_side_leaving_the_roster(self):
        first = pi.build_ledger(ROSTER)
        previous = self.previous_of(first)
        # 参議院の山川誠が名簿から消えた次の台帳。
        later_roster = [r for r in ROSTER if not (r['氏名'] == '山川 誠' and r['院'] == '参議院')]
        later = pi.build_ledger(later_roster, previous=previous)
        self.assertEqual(sorted(p.id for p in later.persons.values() if p.id.startswith('山川誠')), ['山川誠（参・比例）', '山川誠（衆・福島2）'])
        self.assertEqual(later.resolve('山川誠', sangiin_vote=True), ('', pi.UNRESOLVED))
        # 一次資料で決まらない行は決めきれないまま。
        self.assertEqual(later.resolve('山川誠', 'L1', URL + '1'), ('', pi.UNRESOLVED))
        self.assertTrue(later.is_split('山川誠'))
        # 名簿だけから作ると分離が消える（だから前の台帳を引き継ぐ）。
        alone = pi.build_ledger(later_roster)
        self.assertEqual(alone.resolve('山川誠', 'L1', URL + '1')[0], '山川誠')

    def test_existing_id_is_kept_and_new_namesake_gets_a_qualified_id(self):
        first = pi.build_ledger([ROSTER[0]])
        later_roster = [ROSTER[0], roster_row('参議院', '高瀬 真琴', 'たかせ まこと', 'イ党', '比例')]
        later = pi.build_ledger(later_roster, previous=self.previous_of(first))
        self.assertEqual(sorted(p.id for p in later.persons.values()), ['高瀬真琴', '高瀬真琴（参・比例）'])
        self.assertEqual(later.resolve('高瀬真琴', sangiin_vote=True), ('', pi.UNRESOLVED))
        self.assertEqual(later.resolve('高瀬真琴', 'L1', URL + '1')[1], pi.UNRESOLVED)

    def test_same_house_namesakes_get_district_ids_and_are_unresolved_by_house(self):
        roster = [roster_row('衆議院', '森田 草', 'もりた そう', 'ア党', '北海道1'), roster_row('衆議院', '森田 草', 'もりた そう', 'イ党', '沖縄2')]
        ledger = pi.build_ledger(roster)
        self.assertEqual(sorted(p.id for p in ledger.persons.values()), ['森田草（衆・北海道1）', '森田草（衆・沖縄2）'])
        # 院だけでは決まらない。
        self.assertEqual(ledger.resolve('森田草', 'L1', URL + '1', sangiin_vote=True), ('', pi.UNRESOLVED))
        _, out = ai.annotate([inv('L1', '森田草', '衆議院')], ledger, ai.Cabinet([]))
        self.assertEqual((out[0]['人物ID'], out[0]['算入'], out[0]['除外理由']), ('', 'いいえ', '同姓同名で人物を決められない'))
        # 前の台帳を引き継いでも同じ（選挙区で前の人と結ぶ）。
        again = pi.build_ledger(roster, previous=self.previous_of(ledger))
        self.assertEqual(sorted(p.id for p in again.persons.values()), sorted(p.id for p in ledger.persons.values()))

    def test_footnote_marks_are_dropped_from_cabinet_names(self):
        self.assertEqual(pi.canonical('藤村 修*'), pi.canonical('藤村修'))
        self.assertEqual(pi.canonical('小川 平二＊'), '小川平二')
        self.assertEqual(pi.canonical('架空 太郎※'), '架空太郎')
        cab = [{'氏名': '藤村 修', '内閣名': 'あ', '区分': '閣僚', '役職': 'x'}, {'氏名': '藤村 修*', '内閣名': 'い', '区分': '閣僚', '役職': 'y'}]
        ledger = pi.build_ledger([], cab)
        self.assertEqual([p.id for p in ledger.persons.values()], ['藤村修'])
        self.assertEqual(ledger.persons['藤村修'].aliases, set())


    def test_same_name_reading_party_in_both_houses_is_still_two_people(self):
        # 同時に両院の議員にはなれないので、同じ時点の名簿に両院で同じ氏名・読み・会派がいれば別人。
        roster = [roster_row('衆議院', '森川 空', 'もりかわ そら', 'ア党', '東京3'), roster_row('参議院', '森川 空', 'もりかわ そら', 'ア党', '比例')]
        ledger = pi.build_ledger(roster)
        self.assertEqual(sorted(p.id for p in ledger.persons.values()), ['森川空（参・比例）', '森川空（衆・東京3）'])
        self.assertEqual(ledger.resolve('森川空', 'L1', URL + '1'), ('', pi.UNRESOLVED))

    def test_person_who_moved_houses_keeps_the_existing_id(self):
        first = pi.build_ledger([roster_row('衆議院', '森川 空', 'もりかわ そら', 'ア党', '東京3')])
        previous = [{'人物ID': q.id, '氏名': q.name, '読み': q.reading, '院': q.house, '選挙区': q.district, '別表記': ''} for q in first.persons.values()]
        moved = pi.build_ledger([roster_row('参議院', '森川 空', 'もりかわ そら', 'ア党', '比例')], previous=previous)
        self.assertEqual([(p.id, p.house, p.district) for p in moved.persons.values()], [('森川空', '参議院', '比例')])
        # 読みが違えば別人（既存IDは変えず、新しい方に院と選挙区を付ける）。
        other = pi.build_ledger([roster_row('参議院', '森川 空', 'もりかわ くう', 'ア党', '比例')], previous=previous)
        self.assertEqual(sorted(p.id for p in other.persons.values()), ['森川空', '森川空（参・比例）'])

    def test_successor_with_other_reading_in_same_district_is_another_person(self):
        first = pi.build_ledger([roster_row('衆議院', '森川 空', 'もりかわ そら', 'ア党', '東京3')])
        # 同じ選挙区に読みの違う同姓同名が入った。前の人のIDと読みはそのまま、後任は別のIDになる。
        later = pi.build_ledger([roster_row('衆議院', '森川 空', 'もりかわ くう', 'イ党', '東京3')], previous=self.previous_of(first))
        self.assertEqual(sorted((p.id, p.reading) for p in later.persons.values()), [('森川空', 'もりかわ そら'), ('森川空（衆・東京3）', 'もりかわ くう')])
        self.assertEqual(later.resolve('森川空', 'L1', URL + '1'), ('', pi.UNRESOLVED))

    def test_two_candidates_with_same_house_and_reading_are_not_picked_by_order(self):
        previous = [{'人物ID': '森川空（衆・東京3）', '氏名': '森川空', '読み': 'もりかわ そら', '院': '衆議院', '選挙区': '東京3', '別表記': ''},
                    {'人物ID': '森川空（衆・大阪1）', '氏名': '森川空', '読み': 'もりかわ そら', '院': '衆議院', '選挙区': '大阪1', '別表記': ''}]
        # 区割り変更などで、どちらとも選挙区が合わない。並び順で決めず、未決定にする。
        ledger = pi.build_ledger([roster_row('衆議院', '森川 空', 'もりかわ そら', 'ア党', '東京30')], previous=previous)
        self.assertEqual({p.id: p.district for p in ledger.persons.values()}, {'森川空（衆・東京3）': '東京3', '森川空（衆・大阪1）': '大阪1'})
        self.assertTrue(any(u['氏名'] == '森川空' and '結べない' in u['理由'] for u in ledger.undecided))

    def test_proportional_namesakes_with_other_readings_get_distinct_ids(self):
        roster = [roster_row('参議院', '森川 空', 'もりかわ そら', 'ア党', '比例'), roster_row('参議院', '森川 空', 'もりかわ くう', 'イ党', '比例')]
        ledger = pi.build_ledger(roster)
        self.assertEqual(sorted(p.id for p in ledger.persons.values()), sorted(['森川空（参・比例）', '森川空（参・比例・もりかわくう）']))
        self.assertTrue(ledger.is_split('森川空'))
        self.assertEqual(ledger.resolve('森川空', sangiin_vote=True), ('', pi.UNRESOLVED))

    def test_historical_people_from_reference_stay_and_are_not_given_to_a_new_namesake(self):
        reference = [{'id': '森川空', 'name': '森川 空', 'lastSangiinParty': ''}]
        first = pi.build_ledger([], reference=reference)
        self.assertEqual([(p.id, p.house) for p in first.persons.values()], [('森川空', '')])
        # 次の名簿に同じ氏名の人が初めて載った。歴代の人とは結ばず、新しい人は院と選挙区付きのID。
        later = pi.build_ledger([roster_row('参議院', '森川 空', 'もりかわ そら', 'ア党', '比例')], previous=self.previous_of(first))
        self.assertEqual(sorted(p.id for p in later.persons.values()), ['森川空', '森川空（参・比例）'])
        # 院の分からない歴代の人がいるので、参議院の投票記録でも決めない。
        self.assertEqual(later.resolve('森川空', sangiin_vote=True), ('', pi.UNRESOLVED))

    def test_two_roster_rows_wanting_the_same_previous_person_are_not_picked_by_order(self):
        first = pi.build_ledger([roster_row('衆議院', '森川 空', 'もりかわ そら', 'ア党', '東京3')])
        later_roster = [roster_row('衆議院', '森川 空', 'もりかわ そら', 'ア党', '東京4'), roster_row('衆議院', '森川 空', 'もりかわ そら', 'イ党', '大阪1')]
        for roster in (later_roster, list(reversed(later_roster))):
            later = pi.build_ledger(roster, previous=self.previous_of(first))
            # 前の人（東京3）は動かさず、2行とも新しいIDにする。並べ替えても同じ。
            self.assertEqual(later.persons['森川空'].district, '東京3')
            self.assertEqual(sorted(p.id for p in later.persons.values()), ['森川空', '森川空（衆・大阪1）', '森川空（衆・東京4）'])
            self.assertTrue(any('決められない' in u['理由'] for u in later.undecided))

    def test_new_namesake_with_a_reading_unlike_all_previous_people_is_added(self):
        previous = [{'人物ID': '森川空（衆・東京3）', '氏名': '森川空', '読み': 'もりかわ そら', '院': '衆議院', '選挙区': '東京3', '別表記': ''},
                    {'人物ID': '森川空（衆・大阪1）', '氏名': '森川空', '読み': 'もりかわ そら', '院': '衆議院', '選挙区': '大阪1', '別表記': ''}]
        ledger = pi.build_ledger([roster_row('参議院', '森川 空', 'もりかわ くう', 'ア党', '比例')], previous=previous)
        self.assertIn('森川空（参・比例）', ledger.persons)

    def test_ambiguous_move_makes_no_new_id_and_is_listed(self):
        previous = [{'人物ID': '森川空（衆・東京3）', '氏名': '森川空', '読み': 'もりかわ そら', '院': '衆議院', '選挙区': '東京3', '別表記': ''},
                    {'人物ID': '森川空（衆・大阪1）', '氏名': '森川空', '読み': 'もりかわ そら', '院': '衆議院', '選挙区': '大阪1', '別表記': ''}]
        # 前の台帳に同じ氏名が2人いて、参議院の1人がどちらの移った先か決められない。
        ledger = pi.build_ledger([roster_row('参議院', '森川 空', 'もりかわ そら', 'ア党', '比例')], previous=previous)
        self.assertEqual(sorted(p.id for p in ledger.persons.values()), ['森川空（衆・大阪1）', '森川空（衆・東京3）'])
        self.assertTrue(any(u['氏名'] == '森川空' and '結べない' in u['理由'] for u in ledger.undecided))
        self.assertEqual(ledger.resolve('森川空', sangiin_vote=True), ('', pi.UNRESOLVED))


class TypeScriptParityTest(unittest.TestCase):
    """app/src/person-id.ts の canonical が、この台帳と同じ表・同じ規則であること。"""

    def test_variant_table_and_marks_match(self):
        import re
        ts = (pi.ROOT / 'app' / 'src' / 'person-id.ts').read_text(encoding='utf-8')
        table = re.search(r"VARIANTS: Record<string, string> = \{(.*?)\}", ts, re.S).group(1)
        pairs = dict(re.findall(r"(\S)\s*:\s*'(.)'", table))
        self.assertEqual(pairs, pi.VARIANTS)
        self.assertIn(pi.FOOTNOTE_MARKS.pattern, ts)
        self.assertEqual(re.search(r"HONORIFICS = \[(.*?)\]", ts).group(1).replace("'", '').replace(' ', '').split(','), list(ai.HONORIFICS))


if __name__ == '__main__':
    unittest.main()


class HistoricalRosterTest(unittest.TestCase):
    """元職の名簿（会議録の発言者から確かめた人）を台帳に足す決まり。"""

    def test_adds_new_name_but_not_same_name_or_suspected_namesake(self) -> None:
        from scripts.person_ids import build_ledger

        roster = [{"院": "衆議院", "氏名": "山田 太郎", "本名": "", "読み": "やまだ たろう", "会派": "自民", "選挙区": "東京1"}]
        hist = [
            {"氏名": "鈴木一郎", "読み": "すずき いちろう", "院": "参議院", "会派（最多）": "民主党", "同姓同名の疑い": ""},
            {"氏名": "山田太郎", "読み": "やまだ たろう", "院": "衆議院", "会派（最多）": "自民", "同姓同名の疑い": ""},
            {"氏名": "佐藤次郎", "読み": "さとう じろう", "院": "衆議院", "会派（最多）": "自民", "同姓同名の疑い": "はい"},
        ]
        ledger = build_ledger(roster, historical=hist)
        self.assertEqual(ledger.persons["鈴木一郎"].house, "参議院")
        self.assertEqual(len(ledger.by_canonical["山田太郎"]), 1)  # 名簿にいる人と混ぜない
        self.assertNotIn("佐藤次郎", ledger.persons)
        self.assertTrue(any(u["氏名"] == "佐藤次郎" for u in ledger.undecided))
