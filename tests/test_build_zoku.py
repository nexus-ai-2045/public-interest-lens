import unittest

from scripts import build_zoku as z

U = 'https://example.org/x'


def chair(name, session, committee='農林水産委員会', url=U):
    return {'氏名': name, '国会回次': str(session), '委員会': committee, '出典URL': url}


def inv(law, name, action='decide', date='2000-01-01', url=U):
    return {'法律ID': law, '氏名': name, '行動': action, '算入': 'はい', '証拠URL': url, '日付': date, '人物ID': name}


BILLS = [{'法律ID': f'閣法-1-{i}', '所管_今': '農林水産省'} for i in range(1, 8)]


def run(chairs=(), involvements=(), leagues=(), positions=(), relations=(), org_fields=None):
    return z.build(list(chairs), list(involvements), [], BILLS, list(leagues), list(positions), org_fields or {}, list(relations))


class ZokuTest(unittest.TestCase):
    def test_two_chair_sessions_is_enough_one_is_not(self):
        rows, _, _ = run(chairs=[chair('甲 太郎', 1), chair('甲 太郎', 2), chair('乙 花子', 1)])
        self.assertEqual([r['氏名'] for r in rows], ['甲太郎'])
        self.assertEqual(rows[0]['分野'], '農林水産省')

    def test_bills_need_count_and_years(self):
        five_one_year = [inv(f'閣法-1-{i}', '丙') for i in range(1, 6)]
        self.assertEqual(run(involvements=five_one_year)[0], [])
        spread = [inv(f'閣法-1-{i}', '丙', date=f'{2000 + i}-01-01') for i in range(1, 6)]
        rows, _, _ = run(involvements=spread)
        self.assertEqual(rows[0]['分野との継続的な関わり'], 'はい')

    def test_vote_alone_never_counts(self):
        votes = [inv(f'閣法-1-{i}', '丁', 'vote', f'{2000 + i}-01-01') for i in range(1, 8)]
        self.assertEqual(run(involvements=votes)[0], [])

    def test_rows_without_url_are_dropped(self):
        rows, _, _ = run(chairs=[chair('戊', 1, url=''), chair('戊', 2, url='')])
        self.assertEqual(rows, [])

    def test_league_needs_field_and_url_and_marks_only_membership(self):
        ok = {'議連名': '甲議連', '氏名': '己', '役職': '会長', '分野': '農林水産省', '出典URL': U}
        rows, _, s = run(leagues=[ok, {**ok, '氏名': '庚', '分野': ''}, {**ok, '氏名': '辛', '出典URL': ''}])
        self.assertEqual([r['氏名'] for r in rows], ['己'])
        self.assertEqual(rows[0]['分野との継続的な関わり'], 'いいえ')
        self.assertEqual(rows[0]['印'], '議員連盟の名簿に載っている')
        self.assertNotIn('議員連盟', s['入力が空の表'])

    def test_money_threshold_and_field_from_shingikai(self):
        rel = {'区分': '受けた寄附', '人物ID': 'p', 'PDF_URL': U, '関係議員名': '壬', '団体名キー': 'X協会', '相手方': 'X協会'}
        rows, _, _ = run(relations=[{**rel, '金額': '1000000'}], org_fields={'X協会': {'農林水産省'}})
        self.assertIn('X協会', rows[0]['同じ分野の団体との金銭の関係'])
        self.assertEqual(rows[0]['金銭の関係の根拠URL'], U)
        self.assertEqual(run(relations=[{**rel, '金額': '999999'}], org_fields={'X協会': {'農林水産省'}})[0], [])
        self.assertEqual(run(relations=[{**rel, '金額': '5000000'}], org_fields={})[0], [])

    def test_corporate_form_is_normalized_on_both_sides(self):
        rel = {'区分': '受けた寄附', '人物ID': 'p', 'PDF_URL': U, '関係議員名': '壬', '団体名キー': '', '相手方': '一般社団法人民泊協会', '金額': '2000000'}
        rows, _, _ = run(relations=[rel], org_fields={'民泊協会': {'農林水産省'}})
        self.assertEqual(len(rows), 1)

    def test_lobby_row_needs_kind_action_and_result(self):
        p = {'団体名': 'Y会', '団体区分': 'メディア', '分野': '総務省', '法律ID': '閣法-1-1', '立場': '反対', '行動種別': '要望', '要旨': '', '出典URL': U, '確度': '原本照合済み（2系統一致）'}
        _, groups, s = run(positions=[p, {**p, '行動種別': '論調'}, {**p, '団体区分': '思想'}, {**p, '立場': '中立'}])
        _, g2, s2 = run(positions=[{**p, '確度': '保留：読み手の判定なし'}])
        self.assertEqual((g2, s2['原本照合済みでなく除いた行']), ([], 1))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['法案の結果'], '成立')
        self.assertEqual(s['行動種別・団体区分が決まりに合わず除いた行'], 2)

    def test_marks_never_say_wrongdoing(self):
        rows, _, _ = run(chairs=[chair('甲', 1), chair('甲', 2)])
        for bad in ('不正', '癒着', '利権'):
            self.assertNotIn(bad, rows[0]['印'])


if __name__ == '__main__':
    unittest.main()
