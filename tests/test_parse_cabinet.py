"""scripts/parse_cabinet.py の外字画像の扱いと、閣僚名簿の氏名が空でないことを確かめる。

官邸の歴代内閣ページは、氏名を文字ではなく外字の画像で出す行がある。画像を捨てると氏名が空になり、
その人が「名前の無い人」として配分に乗る（2026-11-19 に22行で起きた）。架空の名前で直し方を確かめ、
リポジトリに入っている名簿と対応表は実物で検査する。
"""
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import parse_cabinet as pc

ROOT = Path(__file__).resolve().parents[1]
CABINET = ROOT / 'data' / 'acquired' / 'office-holders' / 'cabinet.csv'
GAIJI = ROOT / 'data' / 'acquired' / 'office-holders' / 'cabinet-gaiji.csv'

TABLE = {'takase_makoto.png': {'画像': 'takase_makoto.png', '氏名': '髙瀬 真琴', '読み': 'たかせ まこと'}}
IMG = '<img class="externalCharacter gaiji size-reg" src="./img/gaiji/%s" alt="%s">'


def read(path):
    with open(path, encoding='utf-8', newline='') as fp:
        return list(csv.DictReader(fp))


class GaijiCell(unittest.TestCase):
    def test_image_becomes_the_name_in_the_table(self):
        for alt in ('髙瀬　真琴', 'たかせ　まこと', ''):  # alt は漢字・読みだけ・空のどれでも、対応表の氏名にする
            cell = IMG % ('takase_makoto.png', alt) + '（たかせ まこと）'
            self.assertEqual(pc.nf(pc.resolve_gaiji(cell, TABLE)), '髙瀬 真琴(たかせ まこと)')

    def test_cell_without_image_is_unchanged(self):
        self.assertEqual(pc.resolve_gaiji('山川 誠（やまかわ まこと）', TABLE), '山川 誠（やまかわ まこと）')

    def test_unknown_image_stops(self):
        with self.assertRaises(SystemExit):
            pc.resolve_gaiji(IMG % ('yamakawa_makoto.png', 'やまかわ　まこと') + '（やまかわ まこと）', TABLE)

    def test_reading_mismatch_stops(self):
        cell = IMG % ('takase_makoto.png', '')
        pc.check_gaiji_kana(cell, 'たかせ　まこと', TABLE)  # 空白の幅の違いは同じ読み
        with self.assertRaises(SystemExit):
            pc.check_gaiji_kana(cell, 'やまかわ まこと', TABLE)

    def test_row_without_reading_is_not_compared(self):
        pc.check_gaiji_kana(IMG % ('takase_makoto.png', ''), '', TABLE)  # 古い代のページや「（兼）」の行は読みが無い

    def test_single_quoted_src_is_read(self):
        cell = "<img class='gaiji' src='../img/gaiji/takase_makoto.png'>"
        self.assertEqual(pc.resolve_gaiji(cell, TABLE), '髙瀬 真琴')
        pc.check_gaiji_kana(cell, 'たかせ まこと', TABLE)

    def test_image_without_src_stops(self):
        with self.assertRaises(SystemExit):
            pc.check_gaiji_kana('<img class="gaiji">', 'たかせ まこと', TABLE)

    def test_replaced_image_stops(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'takase_makoto.png').write_bytes(b'png')
            ok = {'takase_makoto.png': dict(TABLE['takase_makoto.png'], 画像のsha256=hashlib.sha256(b'png').hexdigest())}
            self.assertEqual(pc.check_gaiji_images(ok, d), 1)
            Path(d, 'takase_makoto.png').write_bytes(b'other')
            with self.assertRaises(SystemExit):
                pc.check_gaiji_images(ok, d)
        self.assertEqual(pc.check_gaiji_images(ok, '/nonexistent'), 0)  # 画像を取っていない環境では確かめない

    def test_empty_names_are_reported(self):
        rows = [['架空内閣', '閣僚', '山川 誠'], ['架空内閣', '閣僚', ''], ['架空内閣', '副大臣', ' ']]
        self.assertEqual([i for i, _ in pc.empty_name_rows(rows)], [2, 3])


class CommittedData(unittest.TestCase):
    def test_no_row_has_an_empty_name(self):
        empty = [(i, r['内閣名'], r['役職'], r['読み']) for i, r in enumerate(read(CABINET), 2) if not r['氏名'].strip()]
        self.assertEqual(empty, [], '閣僚名簿に氏名が空の行がある（行番号・内閣名・役職・読み）')

    def test_no_name_is_a_leftover_tag_or_reading(self):
        bad = [(i, r['氏名']) for i, r in enumerate(read(CABINET), 2) if '<' in r['氏名'] or '(' in r['氏名'] or '（' in r['氏名']]
        self.assertEqual(bad, [])

    def test_gaiji_table_is_complete_and_used(self):
        table = read(GAIJI)
        self.assertEqual(len({r['画像'] for r in table}), len(table), '同じ画像が2行ある')
        names = {(r['氏名'], pc.kana_key(r['読み'])) for r in read(CABINET)}
        for r in table:
            for col in ('画像', '氏名', '読み', '画像URL', '画像のsha256', '確かめ方'):
                self.assertTrue(r[col].strip(), f'{r["画像"]} の {col} が空')
            self.assertTrue(r['画像URL'].startswith('https://www.kantei.go.jp/') and r['画像URL'].endswith('/' + r['画像']))
            self.assertRegex(r['画像のsha256'], r'^[0-9a-f]{64}$')
            self.assertIn((r['氏名'], pc.kana_key(r['読み'])), names, f'{r["氏名"]} が名簿に無い')


if __name__ == '__main__':
    unittest.main()
