"""合成対照の小さな入力。公開データにはつながない。損失の名前は、検証が済むまで JSON に置かない。"""
import json
import math
import unittest
from pathlib import Path

import numpy as np

from scripts.synthetic_control import (
    OWN_DEFAULTS,
    REPLICATION_NOT_RUN,
    CountrySeries,
    PolicyCase,
    SynthConfig,
    estimate,
    to_jsonable,
)

ROOT = Path(__file__).resolve().parents[1]
TOL = 1e-8


def cfg(t0, include_catchup, **kwargs):
    return SynthConfig(t0_year=t0, include_catchup=include_catchup, **kwargs)


def panel(values_by_code, years, treated="T0", covariates=None, notes=(), catchup=(), outcome_kind="outcome"):
    """values_by_code: code -> sequence aligned with years. covariates: code -> {name: sequence}."""
    covariates = covariates or {}
    series = []
    for code, values in values_by_code.items():
        cov = tuple(
            (name, tuple(zip(years, seq)))
            for name, seq in covariates.get(code, {}).items()
        )
        series.append(CountrySeries(
            code=code,
            outcome=tuple(zip(years, [float(v) for v in values])),
            covariates=cov,
            catchup=code in catchup,
            notes=tuple(notes) if code == treated else (),
        ))
    return PolicyCase(policy_id="P", treated=treated, series=tuple(series), outcome_kind=outcome_kind)


def factor_panel(delta, years=tuple(range(2000, 2012)), t0=2007):
    """日本は 0.6*D1+0.4*D2。t0 より後から delta を引く。残り 10 か国は乱数で、この凸結合を再現しない。"""
    idx = {y: i for i, y in enumerate(years)}
    a = np.array([float(i) for i in range(len(years))])
    b = 10.0 - a
    japan = 0.6 * a + 0.4 * b
    for y in years:
        if y > t0:
            japan[idx[y]] -= delta
    values = {"T0": japan, "D1": a, "D2": b}
    rng = np.random.default_rng(0)
    for i in range(10):
        values[f"D{i+3}"] = rng.normal(scale=5.0, size=len(years))
    cov = {code: {"人口": np.zeros(len(years))} for code in values}
    return panel(values, years, covariates=cov, notes=("為替",), outcome_kind="sector-productivity")


class SyntheticControlTests(unittest.TestCase):
    def test_T01_factor_model_recovers_weights_and_gap(self):
        delta = 1.5
        case = factor_panel(delta)
        est = estimate(case, cfg(2007, False))
        weights = dict(est.weights)
        self.assertAlmostEqual(weights["D1"], 0.6, delta=TOL)
        self.assertAlmostEqual(weights["D2"], 0.4, delta=TOL)
        for i in range(3, 13):
            self.assertAlmostEqual(weights[f"D{i}"], 0.0, delta=TOL)
        self.assertIsNotNone(est.tau)
        for _year, gap in est.tau:
            self.assertAlmostEqual(gap, -delta, delta=TOL)
        self.assertEqual(len(est.ratios), 13)
        self.assertIsNotNone(est.p_value)
        self.assertIsNotNone(est.leave_one_out)
        self.assertIsNotNone(est.in_time)
        self.assertEqual(est.case_outcome_kind, "sector-productivity")
        self.assertIn("為替", est.contemporaneous_notes)
        self.assertLessEqual(est.rmspe_pre, TOL)

    def test_T02_zero_effect_gap_is_zero_and_p_is_not_small(self):
        est = estimate(factor_panel(0.0), cfg(2007, False))
        self.assertIsNotNone(est.tau)
        for _year, gap in est.tau:
            self.assertAlmostEqual(gap, 0.0, delta=TOL)
        self.assertGreater(est.p_value, 0.5)

    def test_T03_weights_stay_on_the_simplex(self):
        rng = np.random.default_rng(1)
        years = tuple(range(2000, 2010))
        for seed in range(5):
            values = {"T0": rng.normal(size=len(years))}
            for i in range(4):
                values[f"D{i+1}"] = rng.normal(size=len(years))
            est = estimate(panel(values, years), cfg(2006, True, seed=seed))
            ws = np.array([w for _c, w in est.weights])
            self.assertTrue(np.all(ws >= -TOL))
            self.assertAlmostEqual(float(ws.sum()), 1.0, delta=TOL)

    def test_T04_outside_convex_hull_returns_no_amount(self):
        years = tuple(range(2000, 2006))
        values = {"T0": np.full(len(years), 50.0), "D1": np.zeros(len(years)), "D2": np.ones(len(years))}
        est = estimate(panel(values, years), cfg(2003, False))
        self.assertIsNone(est.tau)
        self.assertTrue(any("凸包" in r for r in est.withheld_reasons))

    def test_T05_rmspe_above_cutoff_returns_no_amount(self):
        years = tuple(range(2000, 2008))
        a = np.arange(len(years), dtype=float)
        b = 3.0 - a
        japan = 0.5 * a + 0.5 * b + 1.0
        values = {"T0": japan, "D1": a, "D2": b}
        loose = estimate(panel(values, years), cfg(2005, False, rmspe_pre_limit=100.0))
        tight = estimate(panel(values, years), cfg(2005, False, rmspe_pre_limit=0.1))
        self.assertFalse(any("当てはまり" in r for r in loose.withheld_reasons))
        self.assertIsNone(tight.tau)
        self.assertTrue(any("当てはまり" in r for r in tight.withheld_reasons))

    def test_T06_in_space_rank_matches_hand_calculation(self):
        # 事前は T0 = 0.5*D1 + 0.5*D2。事後は T0=10, D1=0, D2=8。
        # 事前 RMSPE は 0 なので比は inf。D1 の比は 10/sqrt(2)、D2 の比は sqrt(2)。p = 1/3。
        years = (2000, 2001, 2002)
        values = {
            "T0": (0.0, 2.0, 10.0),
            "D1": (0.0, 0.0, 0.0),
            "D2": (0.0, 4.0, 8.0),
        }
        est = estimate(panel(values, years), cfg(2001, False))
        ratios = dict(est.ratios)
        self.assertEqual(len(est.ratios), 3)
        self.assertTrue(math.isinf(ratios["T0"]))
        self.assertAlmostEqual(ratios["D1"], 10.0 / math.sqrt(2.0), delta=TOL)
        self.assertAlmostEqual(ratios["D2"], math.sqrt(2.0), delta=TOL)
        self.assertAlmostEqual(est.p_value, 1.0 / 3.0, delta=TOL)
        self.assertEqual(est.p_value_denominator, 3)

    def test_T07_twelve_donors_cannot_beat_one_thirteenth(self):
        est = estimate(factor_panel(5.0), cfg(2007, False, p_value_line=0.5))
        self.assertAlmostEqual(est.p_value, 1.0 / 13.0, delta=TOL)
        self.assertIn("1/13", est.p_floor_note)
        self.assertIn("0.05", est.p_floor_note)
        self.assertNotIn("有意", est.p_floor_note)
        self.assertIsNotNone(est.tau)

    def test_T08_placebo_exclusion_shrinks_the_denominator(self):
        years = (2000, 2001, 2002)
        values = {"T0": (0.0, 0.0, 10.0), "D1": (0.0, 0.0, 0.0), "D2": (10.0, 10.0, 10.0)}
        full = estimate(panel(values, years), cfg(2001, False))
        cut = estimate(panel(values, years), cfg(2001, False, placebo_mspe_multiple=2.0))
        self.assertEqual(len(full.ratios), 3)
        self.assertEqual(full.p_value_denominator, 3)
        self.assertEqual(len(cut.ratios), 3)
        self.assertEqual(cut.p_value_denominator, 2)

    def test_T09_in_time_placebo_does_not_invent_an_effect(self):
        est = estimate(factor_panel(0.0), cfg(2007, False))
        self.assertIsNotNone(est.in_time)
        for _year, gap in est.in_time:
            self.assertAlmostEqual(gap, 0.0, delta=TOL)

    def test_T10_leave_one_out_runs_once_per_positive_weight(self):
        est = estimate(factor_panel(1.5), cfg(2007, False))
        positive = [code for code, w in est.weights if w > TOL]
        self.assertEqual([code for code, _path in est.leave_one_out], positive)
        self.assertEqual(len(est.leave_one_out), 2)

    def test_T11_basque_california_not_vendored_under_gpl(self):
        self.assertIn("GPL", REPLICATION_NOT_RUN)
        self.assertIn("同梱できない", REPLICATION_NOT_RUN)
        self.assertIn("バスク", REPLICATION_NOT_RUN)
        self.assertIn("カリフォルニア", REPLICATION_NOT_RUN)

    def test_T12_predictor_sign_disagreement_lowers_certainty(self):
        years = (2000, 2001, 2002, 2003)
        values = {
            "T0": (0.0, 3.0, 0.0, -1.0),
            "D1": (1.0, 1.0, 1.0, -4.0),
            "D2": (-1.0, 5.0, -1.0, 4.0),
        }
        cov = {
            "T0": {"景気": (0.0, 0.0, 0.0, 0.0)},
            "D1": {"景気": (0.0, 0.0, 0.0, 0.0)},
            "D2": {"景気": (10.0, 10.0, 10.0, 10.0)},
        }
        est = estimate(panel(values, years, covariates=cov), cfg(2002, False))
        self.assertIsNotNone(est.tau)
        self.assertAlmostEqual(dict(est.tau)[2003], -1.0, delta=TOL)
        self.assertTrue(est.sign_disagreement)
        self.assertEqual(est.certainty, "低")

    def test_T13_same_seed_repeats_the_same_values(self):
        case = factor_panel(1.5)
        config = cfg(2007, False, seed=0)
        first = json.dumps(to_jsonable(estimate(case, config)), ensure_ascii=False, sort_keys=True)
        second = json.dumps(to_jsonable(estimate(case, config)), ensure_ascii=False, sort_keys=True)
        self.assertEqual(first, second)

    def test_T14_missing_years_are_dropped_not_filled_with_zero(self):
        years = (2000, 2001, 2002)
        complete = panel(
            {"T0": (1.0, 1.0, 1.0), "D1": (0.0, 0.0, 0.0), "D2": (2.0, 2.0, 2.0)},
            years,
        )
        # D2 の 2001 が無い。既定は落とす。0 で埋めると D2 がプールに残る。
        series = []
        for s in complete.series:
            if s.code == "D2":
                outcome = tuple((y, v) for y, v in s.outcome if y != 2001)
                series.append(CountrySeries(code=s.code, outcome=outcome))
            else:
                series.append(s)
        case = PolicyCase(policy_id="P", treated="T0", series=tuple(series))
        est = estimate(case, cfg(2001, False, rmspe_pre_limit=100.0))
        self.assertIn("D2", dict(est.dropped))
        self.assertIn("欠損", dict(est.dropped)["D2"])
        self.assertEqual([code for code, _w in est.weights], ["D1"])
        self.assertAlmostEqual(dict(est.weights)["D1"], 1.0, delta=TOL)

    def test_T15_new_estimate_json_does_not_name_a_loss_or_significance(self):
        est = estimate(factor_panel(1.5), cfg(2007, False))
        blob = json.dumps(to_jsonable(est), ensure_ascii=False)
        self.assertNotIn("損失額", blob)
        self.assertNotIn("有意", blob)
        source = (ROOT / "scripts" / "synthetic_control.py").read_text(encoding="utf-8")
        self.assertNotIn("損失額", source)
        self.assertNotIn("有意", source)
        for path in (ROOT / "app" / "src").rglob("*"):
            if not path.is_file():
                continue
            if "synthetic" in path.name:
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("損失額", text)

    def test_V07_catchup_inclusion_is_an_argument(self):
        years = tuple(range(2000, 2006))
        values = {"T0": np.zeros(len(years)), "D1": np.full(len(years), 5.0), "CU1": np.zeros(len(years))}
        kept = estimate(panel(values, years, catchup={"CU1"}), cfg(2003, True))
        dropped = estimate(panel(values, years, catchup={"CU1"}), cfg(2003, False))
        self.assertIn("CU1", dict(kept.weights))
        self.assertAlmostEqual(dict(kept.weights)["CU1"], 1.0, delta=TOL)
        self.assertNotIn("CU1", dict(dropped.weights))
        self.assertIn("キャッチアップ", dict(dropped.dropped)["CU1"])

    def test_required_inputs_and_own_defaults_are_labeled(self):
        with self.assertRaises(TypeError):
            SynthConfig(include_catchup=False)
        with self.assertRaises(TypeError):
            SynthConfig(t0_year=2000)
        labels = []
        for row in OWN_DEFAULTS:
            self.assertIn("独自に決めた値", row["label"])
            labels.append(row["id"])
        for vid in ("V-02", "V-03", "V-04", "V-06", "V-07", "V-08", "V-09", "V-11"):
            self.assertIn(vid, labels)
        self.assertNotIn("V-13", labels)
        names = [n for n in dir(__import__("scripts.synthetic_control", fromlist=["*"])) if "配分" in n or "allocat" in n.lower()]
        self.assertEqual(names, [])

    def test_synthdid_is_not_a_cran_dependency(self):
        source = (ROOT / "scripts" / "synthetic_control.py").read_text(encoding="utf-8")
        self.assertIn("GitHub", source)
        self.assertIn("CRAN", source)
        self.assertNotIn("import synthdid", source)


if __name__ == "__main__":
    unittest.main()
