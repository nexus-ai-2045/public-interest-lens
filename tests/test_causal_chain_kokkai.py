"""因果の鎖（会議録の賛否）と e-Gov の条文照合の判定を、架空の名前と架空の資料で確かめる。実在の人物・会議録は使わない。"""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import fetch_blocking_articles_egov as egov
from scripts import merge_causal_chain_stance as merge
from scripts import stance_rule_causal_chain as rule

URL = 'https://example.test/minutes/'


def speech_file(name, kubun, speeches):
    head = f'氏名: {name}\n院: 衆議院\n会派: 架空会派\n区分: {kubun}\n法案: 架空法案\n'
    body = ''.join(f'■ 2020-01-0{i + 1} 衆議院 架空委員会 第1号 発言番号{i + 1}\nspeechURL: {URL}{i + 1}\n\n{s}\n\n'
                   for i, s in enumerate(speeches))
    return head + '\n' + body


class StanceRuleTest(unittest.TestCase):
    def judge(self, kubun, speeches):
        return rule.judge(kubun, rule.blocks(speech_file('架空太郎', kubun, speeches)))

    def test_blocks_split_each_speech(self):
        self.assertEqual(len(rule.blocks(speech_file('架空太郎', '議員', ['○甲君 一つ目', '○甲君 二つ目']))), 2)

    def test_opposition_debate(self):
        k, q, u = self.judge('議員', ['○甲君 私は、本案に反対の立場から討論いたします。'])
        self.assertEqual(k, '反対')
        self.assertIn('反対の立場', q)
        self.assertEqual(u, URL + '1')

    def test_support_and_chair_ignored(self):
        k, _, _ = self.judge('議員', ['○委員長（甲君） 賛成の諸君の起立を求めます。', '○甲君 御賛同をお願い申し上げます。'])
        self.assertEqual(k, '支持')

    def test_mixed_is_neutral(self):
        k, _, _ = self.judge('議員', ['○甲君 修正案に反対します。', '○甲君 原案に賛成します。'])
        self.assertEqual(k, '中立')

    def test_official_is_unrelated(self):
        k, _, _ = self.judge('政府参考人', ['○政府参考人（甲君） 賛成いたします。'])
        self.assertEqual(k, '無関係')


class MergeTest(unittest.TestCase):
    def test_only_agreement_is_adopted(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / 'stance').mkdir()
            meta = {'id': '架空-1-1', 'title': '架空法案', 'speakers': [
                {'氏名': '甲', '院': '衆議院', '会派': 'A', '発言数': 1},
                {'氏名': '乙', '院': '衆議院', '会派': 'B', '発言数': 2}]}
            (d / '架空-1-1.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            a = [{'氏名': '甲', '立場': '反対'}, {'氏名': '乙', '立場': '中立'}]
            b1 = [{'氏名': '甲', '立場': '反対'}]
            b2 = [{'氏名': '乙', '立場': '支持'}]
            (d / 'stance' / '架空-1-1.lineA.json').write_text(json.dumps(a, ensure_ascii=False), encoding='utf-8')
            (d / 'stance' / '架空-1-1.lineB.part1.json').write_text(json.dumps(b1, ensure_ascii=False), encoding='utf-8')
            (d / 'stance' / '架空-1-1.lineB.part2.json').write_text(json.dumps(b2, ensure_ascii=False), encoding='utf-8')
            import sys
            argv, sys.argv = sys.argv, ['x', '--dir', t]
            try:
                merge.main()
            finally:
                sys.argv = argv
            rows = (d / 'stance-merged.csv').read_text(encoding='utf-8')
            self.assertIn('甲', rows)
            self.assertIn('採用', rows)
            self.assertIn('系統A=中立・系統B=支持', rows)


class EgovArticleTest(unittest.TestCase):
    def test_find_article_and_text(self):
        tree = {'tag': 'Law', 'children': [{'tag': 'Article', 'attr': {'Num': '3'}, 'children': [
            {'tag': 'ArticleCaption', 'children': ['（架空の見出し）']}, {'tag': 'Sentence', 'children': ['架空の条文。']}]}]}
        art = egov.find_article(tree, '3')
        self.assertEqual(egov.text(art), '（架空の見出し）架空の条文。')
        self.assertIsNone(egov.find_article(tree, '4'))


if __name__ == '__main__':
    unittest.main()
