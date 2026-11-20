"""合成コントロール試作の収束と、本番の中央値との一致。入力は架空の系列だけ。"""
import importlib.util
import math
import statistics
import sys
import unittest
from pathlib import Path

from scripts import source_check

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/reports/handoff-2026-11-20/e-Gov結び付き率/合成コントロール試作.py"


def load():
    spec = importlib.util.spec_from_file_location("synthetic_control_proto", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def squared_error(weights, donors, target):
    k = len(donors)
    return sum((sum(weights[j] * donors[j][t] for j in range(k)) - target[t]) ** 2 for t in range(len(target)))


def fictional_oecd():
    """開始前の伸びが大きい架空の系列。未補正の期末対数差は日本の方が高く、本番の累積は伸び損ね。"""
    oecd = source_check.Oecd(Path("/nonexistent-oecd.csv"))
    oecd.series[("JPN", "A", "LR")] = {
        1996: 100.0, 1997: 160.0, 1998: 250.0, 1999: 400.0, 2000: 430.0, 2001: 460.0, 2002: 500.0,
    }
    oecd.series[("JPN", "A", "V")] = {1999: 800.0}
    donors = {
        "B": {1996: 100.0, 1997: 100.0, 1998: 101.0, 1999: 102.0, 2000: 105.0, 2001: 108.0, 2002: 112.0},
        "C": {1996: 100.0, 1997: 101.0, 1998: 102.0, 1999: 103.0, 2000: 106.0, 2001: 110.0, 2002: 114.0},
        "D": {1996: 90.0, 1997: 91.0, 1998: 92.0, 1999: 93.0, 2000: 96.0, 2001: 100.0, 2002: 104.0},
    }
    for country, series in donors.items():
        oecd.series[(country, "A", "LR")] = series
    return oecd


def uncorrected_end_log(oecd):
    """直す前の比較式。期末の対数差から、比較国の対数差の中央値を引く。"""
    base, end = 1999, 2002

    def gap(country):
        series = oecd.get(country, "A", "LR")
        return math.log(series[end] / series[base])

    return gap("JPN") - statistics.median(gap(c) for c in ("B", "C", "D"))


class SyntheticControlPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proto = load()

    def test_more_iterations_reduce_error_toward_the_known_weights(self):
        # 0*w0 + 1*w1 = 0.55 かつ w0+w1=1、w≥0 の解は (0.45, 0.55)。二乗誤差は 0。
        donors = [[0.0], [1.0]]
        target = [0.55]
        # it=0 は更新前の均等重み。旧式は反復2と3の間で二乗誤差が増え、既知の重みに届かない。
        budgets = (0, 1, 2, 3, 4, 8, 16)
        errors = [squared_error(self.proto.fit(donors, target, it=n), donors, target) for n in budgets]
        for prev, nxt in zip(errors, errors[1:]):
            self.assertLessEqual(nxt, prev + 1e-12)
        self.assertLess(errors[-1], errors[0])
        self.assertLess(errors[-1], 1e-10)
        weights = self.proto.fit(donors, target, it=budgets[-1])
        self.assertAlmostEqual(sum(weights), 1.0, places=12)
        self.assertTrue(all(value >= -1e-12 for value in weights))
        self.assertAlmostEqual(weights[0], 0.45, places=6)
        self.assertAlmostEqual(weights[1], 0.55, places=6)

    def test_median_gap_matches_source_check_recompute(self):
        oecd = fictional_oecd()
        countries = ["B", "C", "D"]
        start, end_year = "2000-01-01", 2002
        got = self.proto.production_median_yen(oecd, "A", start, end_year, countries)
        expected = source_check.recompute(oecd, "A", start, end_year, countries)["median"]
        self.assertEqual(got, expected)
        # 未補正の期末対数差は日本の方が高い。本番の円は正で伸び損ねなので、向きは一致しない。
        old = uncorrected_end_log(oecd)
        self.assertGreater(old, 0)
        self.assertGreater(expected, 0)
        self.assertFalse(self.proto.same_direction(old, expected))

    def test_pre_rmse_at_or_below_floor_is_undetermined_for_target_and_placebo(self):
        # 下限は float64 の eps の平方根。値ごとの特別扱いではない。
        floor = self.proto.PRE_RMSE_FLOOR
        self.assertEqual(floor, math.sqrt(sys.float_info.epsilon))
        # 0 と、下限ちょうどと、その直前は、比を計算しない。
        for pre in (0.0, floor, math.nextafter(floor, 0.0), 1e-18):
            judged = self.proto.rmspe_ratio(pre, 0.4)
            self.assertEqual(judged.status, "判定できない")
            self.assertIsNone(judged.ratio)
            self.assertIn("処置前のRMSE", judged.reason)
        # 同じ関数をプラセボ側の事前 RMSE にも使う。戻り方は同じ。
        target = self.proto.rmspe_ratio(0.0, 0.2)
        placebo = self.proto.rmspe_ratio(1e-18, 5.0)
        self.assertEqual(placebo.status, target.status)
        self.assertEqual(placebo.reason, target.reason)
        self.assertIsNone(placebo.ratio)
        # 下限のすぐ上は、事後/事前の比になる。
        above = math.nextafter(floor, math.inf)
        finite = self.proto.rmspe_ratio(above, above * 3)
        self.assertEqual(finite.status, "計算した")
        self.assertEqual(finite.reason, "")
        self.assertAlmostEqual(finite.ratio, 3.0)
        # 実測の桁（1e-4）は下限より大きく、比は出る。
        real_fit = self.proto.rmspe_ratio(1e-4, 2e-4)
        self.assertEqual(real_fit.status, "計算した")
        self.assertAlmostEqual(real_fit.ratio, 2.0)

    def test_undetermined_pre_rmse_is_not_a_small_permutation_p(self):
        # 比較国12。事前が下限以下のとき、旧式は比を巨大数にして p=1/13 を返す。
        # 1/13 は 0.1 より小さいが、比が決まらないので p 値にしない。
        placebos = [(0.2, 0.02)] * 12
        judged = self.proto.permutation_p(0.0, 0.5, placebos)
        self.assertEqual(judged["比の判定"], "判定できない")
        self.assertEqual(judged["置換のp値"], "判定できない")
        self.assertNotIsInstance(judged["置換のp値"], (int, float))
        self.assertIn("処置前のRMSE", judged["判定の理由"])
        for item in judged["プラセボ"]:
            self.assertEqual(item["比の判定"], "計算した")
        # プラセボ側の事前が下限以下のときも比は無い。無限大として分子へ入れ、
        # 分母からは落とさない（落とすと p が 1/12 に小さくなる）。
        mixed = [(0.0, 5.0)] + [(0.2, 0.02)] * 11
        mixed_p = self.proto.permutation_p(0.2, 0.2, mixed)
        self.assertEqual(mixed_p["比の判定"], "計算した")
        self.assertEqual(mixed_p["プラセボ"][0]["比の判定"], "判定できない")
        self.assertIsNone(mixed_p["プラセボ"][0]["比"])
        self.assertEqual(mixed_p["プラセボ"][0]["判定の理由"], judged["判定の理由"])
        self.assertAlmostEqual(mixed_p["置換のp値"], 2 / 13)
        self.assertGreater(mixed_p["置換のp値"], 1 / 12)
