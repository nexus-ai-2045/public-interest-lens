"""バックテスト（scripts/backtest.py）の検査。CI は毎回、今のデータで測り直してログに出す。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest as bt  # noqa: E402


class BacktestCasesTest(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(bt.CASES.read_text(encoding="utf-8"))["cases"]
        self.mapping = json.loads(bt.MAPPING.read_text(encoding="utf-8"))

    def test_all_forty_nine_verified_rows_are_present(self):
        self.assertEqual(len(self.cases), 49)
        self.assertEqual(len({c["id"] for c in self.cases}), 49)
        for c in self.cases:
            self.assertEqual(c["source"]["verified"], "一致")

    def test_agreed_label_is_kept_only_when_the_two_lines_match(self):
        for c in self.cases:
            l = c["labels"]
            for field, k2 in (("design", "design"), ("outcome_class", "outcome_class"), ("benefit_sign", "benefit_sign"), ("country", "country")):
                if field == "benefit_sign" and l["line1"]["benefit_sign"] is None:
                    self.assertIsNone(l["agreed"][field])
                    continue
                one, two = l["line1"][field], l["line2"][field]
                if one == two:
                    self.assertEqual(l["agreed"][field], one)
                else:
                    self.assertIsNone(l["agreed"][field])
                    self.assertIn(field, l["held"])

    def test_every_group_has_a_mapping(self):
        for c in self.cases:
            if c["group"] is not None:
                self.assertIn(c["group"], self.mapping["groups"])


class BacktestRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = bt.run()
        print("\n" + bt.render(cls.result))

    def test_levels_are_nested(self):
        ids = [{c["id"] for c in lv["cases"]} for lv in self.result["levels"]]
        self.assertTrue(ids[0] <= ids[1] <= ids[2])

    def test_verdict_never_claims_without_enough_cases(self):
        for lv in self.result["levels"]:
            if lv["n"] < bt.MIN_N:
                self.assertEqual(lv["verdict"], "判定不能")
            elif lv["rate"] >= bt.TARGET:
                self.assertEqual(lv["verdict"], "達成")
            else:
                self.assertEqual(lv["verdict"], "未達")

    def test_every_case_is_scored_or_has_a_reason(self):
        scored = {c["id"] for c in self.result["levels"][2]["cases"]}
        excluded = {e["id"] for e in self.result["excluded"]}
        self.assertEqual(scored | excluded, {c["id"] for c in json.loads(bt.CASES.read_text(encoding="utf-8"))["cases"]})
        self.assertFalse(scored & excluded)

    def test_wilson_interval_contains_the_rate(self):
        for lv in self.result["levels"]:
            if lv["n"]:
                low, high = lv["wilson95"]
                self.assertLessEqual(low, lv["rate"])
                self.assertGreaterEqual(high, lv["rate"])

    def test_frozen_snapshot_is_reproducible_when_inputs_are_unchanged(self):
        checked = 0
        for path in bt.snapshot_files():
            snap = json.loads(path.read_text(encoding="utf-8"))
            if any(self.result["inputs"].get(k) != v for k, v in snap["inputs"].items()) or snap["spec_version"] != self.result["spec_version"]:
                continue  # 入力（法律の配布データなど）が更新された。固定した結果はその時点の値として残す
            checked += 1
            for key, value in snap.items():
                if key in ("label", "date", "note", "version", "inputs"):
                    continue
                self.assertEqual(value, self.result[key], f"{path.name} の {key} が、同じ入力での再計算と違う")
        print(f"\n固定した結果のうち、入力が同じで再現を確かめたもの: {checked}")

class BacktestPublishedFilesTest(unittest.TestCase):
    def test_public_json_and_doc_are_built_from_the_snapshots(self):
        runs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in bt.snapshot_files()), key=lambda r: (r["date"], r["label"]))
        self.assertTrue(runs, "固定した結果が無い")
        public = json.loads(bt.PUBLIC.read_text(encoding="utf-8"))
        self.assertEqual(public, {"schema": "backtest-runs/v1", "runs": runs}, "python3 scripts/backtest.py --publish で作り直す")
        self.assertEqual(bt.DOC.read_text(encoding="utf-8"), bt.render_doc(runs), "python3 scripts/backtest.py --publish で作り直す")

    def test_v1_is_recorded_as_the_first_measurement(self):
        v1 = json.loads((bt.SNAP_DIR / "v1.json").read_text(encoding="utf-8"))
        self.assertIn("v1 時点", v1["note"])


class BacktestSnapshotGuardTest(unittest.TestCase):
    def test_existing_snapshot_name_is_refused(self):
        import subprocess
        before = (bt.SNAP_DIR / "v1.json").read_bytes()
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "backtest.py"), "--snapshot", "v1", "--date", "2030-01-01"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertEqual((bt.SNAP_DIR / "v1.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
