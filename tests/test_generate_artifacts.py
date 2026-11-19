"""生成の入口（scripts/generate_artifacts.py）の鮮度判定の検査。生成そのものは走らせない。"""

import os
import unittest

from scripts import generate_artifacts as ga


class NewestInputTest(unittest.TestCase):
    def test_own_outputs_are_not_counted_as_inputs(self):
        # data/ の下に置く出力（曝露ランキング）が入力に数えられると、毎回全段を作り直してしまう
        inside = [out for _, out, _ in ga.STEPS if any(root in out.parents for root in ga.INPUT_ROOTS)]
        self.assertTrue(inside, "data/ の下に置く出力が無い（前提が変わった）")
        for out in inside:
            if not out.is_file():
                self.skipTest(f"{out} がまだ無い")
            before = ga.newest_input()
            stat = out.stat()
            try:
                os.utime(out, (stat.st_atime, before + 3600))
                self.assertEqual(before, ga.newest_input())
            finally:
                os.utime(out, (stat.st_atime, stat.st_mtime))


if __name__ == "__main__":
    unittest.main()
