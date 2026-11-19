"""誤りの型の機械検査（scripts/check_error_types.py）の検査。"""
import unittest

from scripts import check_error_types as ce


def law(**kw):
    o = {"id": "x", "題名": "預金保険法の一部を改正する法律案", "種類": "実質改正", "経路": ""}
    g = {"到達点": "保留", "経済に効くか": "", "分類": "評価対象"}
    o.update({k: v for k, v in kw.items() if k in o})
    g.update({k: v for k, v in kw.items() if k in g})
    return o, g


def types_of(fixed=None, v1=None, **kw):
    o, g = law(**kw)
    return {r["型"] for r in ce.find([o], {"x": g}, v1 or {}, {}, {}, fixed)}


class FindTest(unittest.TestCase):
    def test_the_six_reread_shapes_are_caught(self):
        """読み直しで見つかった6本の形（直す前の値）を拾う。全部改正を新規と置いた形（閣法-213-45）は題名では拾えない。"""
        self.assertIn("K1", types_of(種類=""))  # 衆法-217-19
        self.assertIn("K2", types_of(題名="所得税法等の一部を改正する法律案", 種類="定型改正"))  # 閣法-189-3
        self.assertIn("K2", types_of(題名="地方税法等の一部を改正する法律案", 種類="定型改正"))  # 閣法-221-4
        v1 = {"x": {"A_種類": "定型改正", "B_種類": "実質改正"}}
        self.assertIn("K3", types_of(v1=v1, 題名="特定産業廃棄物に起因する支障の除去等に関する特別措置法の一部を改正する法律案"))
        self.assertIn("C3", types_of(経済に効くか="判定不能（Sonnet）", 到達点="測定できない"))  # 閣法-180-38
        self.assertIn("R1", types_of(分類="評価対象外", 到達点="保留", 経済に効くか="経済に効く（一致）"))  # 閣法-180-72 など

    def test_internal_contradictions(self):
        self.assertIn("C1", types_of(経済に効くか="経済に効く（一致）", 到達点="効果なし（定例）"))
        self.assertIn("C2", types_of(経済に効くか="制度（一致）", 到達点="保留"))
        self.assertEqual(types_of(経済に効くか="制度（一致）", 到達点="評価対象外", 分類="評価対象外"), set())

    def test_corrected_items_are_not_counted(self):
        fixed = {"x": {"類型": {"直した値": "実質改正"}}}
        self.assertNotIn("K1", types_of(fixed=fixed, 種類=""))
        self.assertIn("C3", types_of(fixed=fixed, 種類="", 経済に効くか="判定不能（一致）"))

    def test_committed_output_is_current(self):
        rows, summary = ce.build()
        self.assertEqual((ce.OUT_DIR / "candidates.csv").read_text(encoding="utf-8"), ce.render(rows))
        for code, t in summary["型"].items():
            self.assertEqual(t["本数"], len({r["id"] for r in rows if r["型"] == code}), code)
            self.assertIn(f"{summary['母数']:,}本中", t["表記"])


if __name__ == "__main__":
    unittest.main()
