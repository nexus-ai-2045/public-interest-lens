"""M4運用訓練（架空データ）を期待状態で検査します。成功はM4の運用証跡ではありません。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.m4_ops_drill import (
    CORRECTED_QUOTE,
    EVIDENCE_KIND,
    MARK,
    ORIGINAL_QUOTE,
    DrillError,
    _expect,
    observed_state,
    run_drill,
    synthetic_case,
)


class M4OpsDrillTests(unittest.TestCase):
    def test_drill_reaches_expected_state_at_every_step(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = run_drill(root)
            self.assertEqual(result["evidenceKind"], EVIDENCE_KIND)
            steps = {step["step"]: step for step in result["steps"]}
            self.assertEqual(
                [step["step"] for step in result["steps"]],
                ["initial", "normal-update-1", "normal-update-2", "correction", "failure-refused", "recovery", "rollback", "rollback-tamper-refused"],
            )
            self.assertEqual([steps[name]["latestYear"] for name in ("initial", "normal-update-1", "normal-update-2")], [2020, 2021, 2022])
            self.assertEqual(len({steps[name]["snapshotId"] for name in ("initial", "normal-update-1", "normal-update-2", "correction", "recovery")}), 5)
            self.assertEqual(steps["correction"]["previousSnapshotId"], steps["normal-update-2"]["snapshotId"])
            self.assertEqual(steps["failure-refused"]["snapshotId"], steps["correction"]["snapshotId"])
            self.assertIn("片側だけ", steps["failure-refused"]["refusal"])
            self.assertEqual(steps["rollback"]["snapshotId"], steps["correction"]["snapshotId"])
            self.assertEqual(steps["rollback"]["rolledBackFrom"], steps["recovery"]["snapshotId"])
            self.assertEqual(result["generations"], 5)

            out = root / "out"
            state = observed_state(out, root / "public")
            self.assertEqual(state["snapshotId"], steps["correction"]["snapshotId"])
            self.assertEqual(state["quote"], CORRECTED_QUOTE)
            # 訂正前の世代は引用を含めて残る
            database = sqlite3.connect(out / "generations" / steps["normal-update-2"]["snapshotId"] / "catalog.sqlite3")
            try:
                self.assertEqual(database.execute("SELECT quote FROM citations WHERE citationId = 'drill-c1'").fetchone()[0], ORIGINAL_QUOTE)
            finally:
                database.close()
            # 途中で壊れた世代は削除せず隔離されている
            self.assertTrue((root / steps["recovery"]["quarantined"] / "economy.json").is_file())
            self.assertFalse((root / steps["recovery"]["quarantined"] / "case.json").exists())

    def test_expectation_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run_drill(root)
            state = observed_state(root / "out", root / "public")
            with self.assertRaises(DrillError):
                _expect("check", state, latest_year=2023, quote=CORRECTED_QUOTE)
            with self.assertRaises(DrillError):
                _expect("check", state, latest_year=2022, quote=ORIGINAL_QUOTE)
            with self.assertRaises(DrillError):
                _expect("check", {**state, "publicCaseMatches": False}, latest_year=2022, quote=CORRECTED_QUOTE)

    def test_fixture_is_marked_synthetic(self):
        case = synthetic_case()
        for citation in case["citations"]:
            self.assertIn("__synthetic-drill-fixture__", citation["url"])
            self.assertTrue(citation["quote"].startswith(MARK))
        self.assertTrue(all(actor["label"].startswith("架空人物") for actor in case["actors"]))
        self.assertNotIn("score", json.dumps(case))


if __name__ == "__main__":
    unittest.main()
