"""産業連関による波及（io-ripple-v1）の検査。原本が手元に無い環境では飛ばす。"""
import csv
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import io_ripple as m  # noqa: E402

HAVE_RAW = (m.RAW / 'link20.xlsx').exists() and (m.RAW / 'official2020_large.xlsx').exists()


class TestFormula(unittest.TestCase):
    def test_two_sector_hand_calc(self):
        # 2部門、輸入なし。A=[[0,.5],[0,0]]（部門2が1円作るのに部門1から0.5円仕入れる）
        Z = np.array([[0, 50.0], [0, 0]])
        X = np.array([100.0, 100.0])
        D = np.array([50.0, 100.0])
        M = np.zeros(2)
        _, _, B = m.leontief(Z, D, M, X)
        self.assertAlmostEqual(B[0, 1], 0.5)
        VA = np.array([50.0, 50.0])  # v=0.5
        r = m.ripple_ratio(B, VA, X)
        # 部門2が縮むと部門1も縮む：r_2 = v1*B12 / (v2*B22) = 0.5*0.5/(0.5*1)=0.5。部門1は川下なので r_1=0
        self.assertAlmostEqual(r[1], 0.5)
        self.assertAlmostEqual(r[0], 0.0)

    def test_half_width(self):
        self.assertEqual(m.half_width(3), 0.40)
        self.assertEqual(m.half_width(8), 0.50)
        self.assertIsNone(m.half_width(11))


@unittest.skipUnless(HAVE_RAW, '産業連関表の原本が無い（python3 scripts/io_ripple.py fetch）')
class TestAgainstOfficial(unittest.TestCase):
    def test_matches_official_inverse(self):
        mx, n = m.check()
        self.assertEqual(n, 37)
        self.assertLess(mx, 1e-9)


class TestPublishedTables(unittest.TestCase):
    def test_laws_ripple_consistent(self):
        p = m.OUT / 'laws_ripple.csv'
        if not p.exists():
            self.skipTest('laws_ripple.csv が無い')
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r['波及比率r']:
                lo, rr, hi = float(r['波及比率_下限']), float(r['波及比率r']), float(r['波及比率_上限'])
                self.assertLessEqual(lo, rr)
                self.assertLessEqual(rr, hi)
                self.assertGreaterEqual(int(r['波及を含む上限_円']) / int(r['額_中央値_円']), 1 if int(r['額_中央値_円']) > 0 else -1e9)
            else:
                self.assertTrue(r['理由'], r['id'])  # 出さないときは理由を書く


if __name__ == '__main__':
    unittest.main()
