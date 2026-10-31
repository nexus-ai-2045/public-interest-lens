"""産業連関の古い表（平成7-12-17年、io_ripple_old）の検査。原本や numpy・xlrd が無い環境では、原本に頼る検査だけ飛ばす。"""
import csv
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
OUT = ROOT / 'data/derived/io-ripple-v1'
try:
    import io_ripple as base
    import io_ripple_old as old
    HAVE_LIBS = True
except ImportError:  # CI の標準環境には numpy・openpyxl・xlrd が無い
    HAVE_LIBS = False
HAVE_RAW = HAVE_LIBS and (old.RAW / old.FILE).exists()


@unittest.skipUnless(HAVE_LIBS, 'numpy・openpyxl・xlrd が無い')
class TestRules(unittest.TestCase):
    def test_half_width_old(self):
        self.assertEqual(base.half_width(5, 'old'), 0.60)
        self.assertIsNone(base.half_width(6, 'old'))

    def test_same_industries_as_current_mapping(self):
        # 古い表の対応は、2011年以降の表の対応と同じ産業（A〜S）を同じ割り切りで引き直したもの
        self.assertEqual(set(old.OLD_ISIC_TO_IO), set(base.ISIC_TO_IO))

    def test_no_code_reuse_from_new_mapping(self):
        # 符号をそのまま流用していない（例：D 電力・ガスは新しい表で 46、古い表で 51。G 商業は新 51、古い 61）
        self.assertNotEqual(old.OLD_ISIC_TO_IO['D'], base.ISIC_TO_IO['D'])
        self.assertEqual(old.OLD_ISIC_TO_IO['G'], ['61'])

    def test_consistency_detects_imbalance(self):
        import numpy as np
        Z = np.array([[0.0, 50.0], [0.0, 0.0]])
        X = np.array([100.0, 100.0])
        D = np.array([100.0, 100.0])  # 国内需要合計（中間需要を含む）：部門1は 中間50＋最終50、部門2は 最終100
        E = np.zeros(2)
        M = np.zeros(2)
        VA = np.array([100.0, 50.0])
        ok = old.consistency(['a', 'b'], Z, D, E, M, X, VA)
        self.assertEqual(ok['行の収支_最大絶対誤差_百万円'], 0.0)
        self.assertEqual(ok['列の収支_最大絶対誤差_百万円'], 0.0)
        bad = old.consistency(['a', 'b'], Z, D, E, M, X, VA + np.array([0.0, 7.0]))
        self.assertEqual(bad['列の収支_最大絶対誤差_百万円'], 7.0)


@unittest.skipUnless(HAVE_RAW, '古い表の原本が無い（python3 scripts/io_ripple_old.py fetch）')
class TestOldTables(unittest.TestCase):
    def test_tables_balance(self):
        for y in old.OLD_YEARS:
            t = old.load_old(y)
            c = old.consistency(*t, other=old.other_inputs(y, t[0]))
            self.assertEqual(c['行の収支_最大絶対誤差_百万円'], 0.0, y)
            self.assertEqual(c['列の収支_最大絶対誤差_百万円'], 0.0, y)

    def test_value_added_is_gdp_scale(self):
        # 2005年の粗付加価値は約506兆円（名目 GDP は約503兆円。統計上の不突合や関税などで少し違う）
        va = old.load_old(2005)[6].sum() / 1e6
        self.assertGreater(va, 495)
        self.assertLess(va, 515)

    def test_row_and_column_share_four_digit_sectors(self):
        secs = old.load_old(2005)[0]
        self.assertEqual(len(secs), 185)
        self.assertIn('0113', secs)  # 行は「野菜」1本、列は露地・施設の2本に分かれる産業が、4桁で1本にそろう


class TestPublished(unittest.TestCase):
    def test_backtest_supports_half_width(self):
        p = OUT / 'backtest_old.json'
        if not p.exists():
            self.skipTest('backtest_old.json が無い')
        bt = json.loads(p.read_text(encoding='utf-8'))
        # 同じ符号の中の5年の動き（産業ごと）の最大と、改訂をまたぐ差の最大が、半幅 0.60 に収まる
        self.assertLessEqual(max(bt['5年の動き_産業ごと_最大'].values()), 0.40)
        self.assertLessEqual(bt['改訂をまたぐ_2005→2011_最大'], 0.60)
        for y in bt['表の整合'].values():
            self.assertEqual(y['行の収支_最大絶対誤差_百万円'], 0.0)
            self.assertEqual(y['列の収支_最大絶対誤差_百万円'], 0.0)
        # 補正が定まらない産業（D 電力・ガス・熱供給）と、対応の無い産業は、古い表を使わない
        self.assertNotIn('D', bt['補正に使う産業'])

    def test_laws_with_old_table_use_wide_interval(self):
        p = OUT / 'laws_ripple.csv'
        if not p.exists():
            self.skipTest('laws_ripple.csv が無い')
        n = 0
        for r in csv.DictReader(p.read_text(encoding='utf-8').splitlines()):
            if r['表の粒度'].startswith('基本分類（平成17年基準'):
                n += 1
                rr, lo, hi = float(r['波及比率r']), float(r['波及比率_下限']), float(r['波及比率_上限'])
                self.assertAlmostEqual(math.log(rr / lo), 0.60, delta=0.01)
                self.assertAlmostEqual(math.log(hi / rr), 0.60, delta=0.01)
                self.assertLessEqual(abs(int(r['施行年']) - int(r['使った表'])), 5)
        self.assertGreater(n, 0)


if __name__ == '__main__':
    unittest.main()
