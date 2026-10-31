"""原因の軸の計算（scripts/build_cause_axis.py）。手で解ける小さな入力で、式・比べる国の基準・置換順位・相殺を確かめる。"""
import csv
import math
import tempfile
import unittest
from pathlib import Path

from scripts import build_cause_axis as ca

YEARS = range(1995, 2024)


def write(path: Path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def make_inputs(root: Path, spreads: dict[str, float], industries=("X",), nominal=1_000_000.0):
    """国ごとに、全体の実質は毎年 2% 増え、産業は (2% + spread) 増える。名目は一定。単位は百万円なので 1,000,000 = 1兆円。"""
    va, emp = [], []
    for c, spread in spreads.items():
        for t in YEARS:
            va.append([c, "_T", "L", t, 100 * math.exp(0.02 * (t - 1995)), "XDC"])
            va.append([c, "_T", "V", t, nominal, "XDC"])
            emp.append([c, t, 1000.0])
            for ind in industries:
                va.append([c, ind, "L", t, 10 * math.exp((0.02 + spread) * (t - 1995)), "XDC"])
                va.append([c, ind, "V", t, nominal, "XDC"])
    write(root / "stan_va.csv", ["国", "産業", "価格", "年", "値", "単位"], va)
    write(root / "employment.csv", ["国", "年", "就業者_千人"], emp)
    gdp = {c: 1_000_000.0 for c in spreads}
    gdp["LOW"] = 100_000.0  # 追い上げの国（日本の8割未満）
    write(root / "gdp2000.csv", ["国", "GDP2000_PPP_百万米ドル"], list(gdp.items()))
    write(root / "factors2020.csv", ["国", "産業", "指標", "価格", "単位", "年", "値"], [])


class IndustryGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        spreads = {"JPN": -0.01, "AAA": 0.02, "BBB": 0.03, "CCC": 0.04, "DDD": 0.05, "LOW": 0.5, "IRL": 0.5}
        make_inputs(self.root, spreads)
        # LOW・IRL は産業の系列を持たせて、基準で外れることを確かめる
        self.inputs = ca.Inputs(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_catchup_country_and_ireland_are_not_compared(self):
        self.assertEqual(self.inputs.eligible(), ["AAA", "BBB", "CCC", "DDD"])

    def test_cumulative_gap_matches_closed_form(self):
        donors = ca.donors_for(self.inputs, "X", self.inputs.eligible())
        total, rows = ca.cumulative_gap(self.inputs, "X", donors)
        # 中央値は (0.03 + 0.04) / 2 = 0.035、日本は -0.01 → 年 k の差は 1兆円 × (exp(0.045 k) − 1)
        want = sum(1_000_000 * (math.exp(0.045 * k) - 1) for k in range(1, 24))
        self.assertAlmostEqual(total, want, places=3)
        self.assertEqual(len(rows), 23)

    def test_japan_behind_every_peer_ranks_first_and_is_a_loss(self):
        donors = ca.donors_for(self.inputs, "X", self.inputs.eligible())
        rank, n, direction = ca.placebo_rank(self.inputs, "X", donors)
        self.assertEqual((rank, n, direction), (1, 5, "損失"))

    def test_japan_ahead_of_every_peer_is_a_benefit_ranked_from_the_negative_side(self):
        make_inputs(self.root, {"JPN": 0.2, "AAA": 0.02, "BBB": 0.03, "CCC": 0.04, "DDD": 0.05, "LOW": 0.5})
        inputs = ca.Inputs(self.root)
        donors = ca.donors_for(inputs, "X", inputs.eligible())
        total, _ = ca.cumulative_gap(inputs, "X", donors)
        self.assertLess(total, 0)
        self.assertEqual(ca.placebo_rank(inputs, "X", donors), (1, 5, "便益"))

    def test_japan_in_the_middle_ranks_in_the_middle(self):
        make_inputs(self.root, {"JPN": 0.035, "AAA": 0.02, "BBB": 0.03, "CCC": 0.04, "DDD": 0.05, "LOW": 0.5})
        inputs = ca.Inputs(self.root)
        donors = ca.donors_for(inputs, "X", inputs.eligible())
        rank, n, _ = ca.placebo_rank(inputs, "X", donors)
        self.assertEqual((rank, n), (3, 5))

    def test_donor_with_a_missing_year_is_left_out(self):
        rows = [r for r in ca.read(self.root / "stan_va.csv") if not (r["国"] == "AAA" and r["産業"] == "X" and r["年"] == "2010")]
        write(self.root / "stan_va.csv", ["国", "産業", "価格", "年", "値", "単位"], [[r[k] for k in ("国", "産業", "価格", "年", "値", "単位")] for r in rows])
        inputs = ca.Inputs(self.root)
        self.assertNotIn("AAA", ca.donors_for(inputs, "X", inputs.eligible()))

    def test_japan_sub_industry_without_real_series_is_deflated_by_its_parent(self):
        make_inputs(self.root, {"JPN": -0.01, "AAA": 0.02, "BBB": 0.03}, industries=("J", "J61"))
        rows = [r for r in ca.read(self.root / "stan_va.csv") if not (r["国"] == "JPN" and r["産業"] == "J61" and r["価格"] == "L")]
        write(self.root / "stan_va.csv", ["国", "産業", "価格", "年", "値", "単位"], [[r[k] for k in ("国", "産業", "価格", "年", "値", "単位")] for r in rows])
        inputs = ca.Inputs(self.root)
        self.assertTrue(inputs.deflated("J61"))
        self.assertFalse(inputs.deflated("J"))
        self.assertIsNotNone(inputs.y("JPN", "J61"))


class AxisTests(unittest.TestCase):
    def result(self, trillion, certainty):
        return {"累計_兆円": trillion, "確かさ": certainty}

    def test_loss_and_benefit_on_one_axis_are_netted_and_shared_observation_is_split(self):
        results = {i: self.result(0.0, "誤差の範囲") for i in ca.INDUSTRY_NAMES}
        results["J62_63"] = self.result(90.0, "参考")
        results["J61"] = self.result(64.7, "参考")
        results["C26"] = self.result(-97.3, "参考")
        rows = {r["軸"]: r for r in ca.axis_rows(results)}
        # IT・情報サービスは E1・F1・G1 の3軸で共有 → 各 30 兆円
        self.assertAlmostEqual(rows["F1"]["額_兆円"], 30.0)
        self.assertAlmostEqual(rows["C2"]["額_兆円"], 64.7 - 97.3)
        self.assertIn("便益", rows["C2"]["扱い"])

    def test_observation_within_noise_is_recorded_only(self):
        results = {i: self.result(50.0, "誤差の範囲") for i in ca.INDUSTRY_NAMES}
        rows = {r["軸"]: r for r in ca.axis_rows(results)}
        self.assertIsNone(rows["R1"]["額_兆円"])
        self.assertEqual(rows["R1"]["記録だけの観測"], "J58T60")
        self.assertIn("記録だけ", rows["R1"]["扱い"])


class GrowthAccountingTests(unittest.TestCase):
    def rows(self, country, industry, y_growth, l_growth, k_growth, share=0.6):
        out = []
        for t in range(2000, 2020):
            k = t - 2000
            out += [[country, industry, "B1G", "L", "XDC", t, 100 * math.exp(y_growth * k)],
                    [country, industry, "B1G", "V", "XDC", t, 100.0],
                    [country, industry, "D1", "V", "XDC", t, 100.0 * share],
                    [country, industry, "EMP", "_Z", "PS", t, 10 * math.exp(l_growth * k)],
                    [country, industry, "N11NA", "L", "XDC", t, 50 * math.exp(k_growth * k)]]
        return out

    def test_the_three_parts_add_up_to_the_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_inputs(root, {"JPN": 0.0, "AAA": 0.0})
            rows = []  # 産業コード X は公開の FACTOR_INDUSTRIES に無いので、分解の関数 decompose を直接呼ぶ
            for c, (y, l, k) in {"JPN": (0.01, 0.0, 0.01), "AAA": (0.03, 0.005, 0.02)}.items():
                rows += self.rows(c, "X", y, l, k) + self.rows(c, "_T", 0.02, 0.0, 0.01)
            write(root / "factors2020.csv", ["国", "産業", "指標", "価格", "単位", "年", "値"], rows)
            inputs = ca.Inputs(root)
            d = ca.decompose(inputs, "AAA", "X", 2019)
            self.assertAlmostEqual(d["Y"], d["L"] + d["K"] + d["TFP"])
            self.assertAlmostEqual(d["L"], 0.6 * 0.005 * 19, places=6)
            self.assertAlmostEqual(d["K"], 0.4 * 0.02 * 19, places=6)

    def test_missing_labor_or_capital_series_gives_no_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_inputs(root, {"JPN": 0.0})
            write(root / "factors2020.csv", ["国", "産業", "指標", "価格", "単位", "年", "値"], [r for r in self.rows("JPN", "X", 0.01, 0.0, 0.01) if r[2] != "N11NA"])
            self.assertIsNone(ca.decompose(ca.Inputs(root), "JPN", "X", 2019)["TFP"])


class CommittedOutputTests(unittest.TestCase):
    def test_committed_outputs_are_current(self):
        """固定入力から作り直した結果が、Git にある出力と一致する（手で直した数字を残さない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            ca.build(dst=dst, app_json=None)
            for name in ("industry_gap.csv", "yearly.csv", "peers.csv", "growth_accounting.csv", "axes.csv", "summary.json"):
                self.assertEqual((dst / name).read_text(encoding="utf-8"), (ca.DST / name).read_text(encoding="utf-8"), name)
            self.assertEqual((dst / "summary.json").read_text(encoding="utf-8"), ca.APP_JSON.read_text(encoding="utf-8"))

    def test_published_amounts_stay_inside_the_total(self):
        """情報通信の内訳（IT・出版・通信）の合計が、情報通信全体の差を超えない（超えたら配り直しが要る。2-3章）。"""
        with ca.DST.joinpath("industry_gap.csv").open(encoding="utf-8", newline="") as f:
            gaps = {r["産業"]: float(r["累計_兆円"]) for r in csv.DictReader(f)}
        self.assertLessEqual(gaps["J62_63"] + gaps["J58T60"] + gaps["J61"], gaps["J"] + 1e-6)


if __name__ == "__main__":
    unittest.main()
