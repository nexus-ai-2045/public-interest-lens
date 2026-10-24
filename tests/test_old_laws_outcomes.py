import csv
import tempfile
import unittest
from pathlib import Path

from scripts import build_all_laws_outcomes as base
from scripts import build_old_laws_outcomes as old

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "derived" / "all-laws-old" / "outcomes.csv"


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class OldLawsOutcomesTest(unittest.TestCase):
    """R1：施行日のある旧法への結果の付与（scripts/build_old_laws_outcomes.py）。"""

    def test_every_dated_law_has_exactly_one_outcome_with_reason(self):
        dated = [r["法令番号"] for r in read(ROOT / "data" / "acquired" / "enforcement-dates-old" / "enforcement_old.csv") if r["施行日"].strip()]
        rows = old.build()
        self.assertEqual([r["id"] for r in rows], dated)
        for r in rows:
            self.assertIn(r["結果"], base.OUTCOMES, r["id"])
            self.assertTrue(r["理由"], r["id"])

    def test_committed_file_matches_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outcomes.csv"
            base.write(old.build(), path)
            self.assertEqual(path.read_bytes(), OUT.read_bytes())

    def test_no_amount_without_loss_stage(self):
        self.assertTrue(all(r["結果"] != "額あり" and not r["損失または便益の額"] for r in old.build()))

    def test_unagreed_triage_is_held_with_reason_unless_routine(self):
        t = {"id": "x", "題名": "例の法律の一部を改正する法律", "結果": "保留", "種類": "", "分野": "", "A_種類": "実質改正", "A_分野": "金融",
             "B_種類": "実質改正", "B_分野": "交通・移動"}
        r = old.decide_old(t, "1990-04-01", {})
        self.assertEqual((r["結果"], r["経路"]), ("保留", "振り分け保留"))
        routine = {**t, "題名": "平成二年度における公債の発行の特例に関する法律"}
        self.assertEqual(old.decide_old(routine, "1990-04-01", {})["結果"], "効果なし（定例）")

    def test_market_law_uses_impact_verdict(self):
        t = {"id": "y", "題名": "例の運送法", "結果": "一致", "種類": "実質改正", "分野": "交通・移動", "A_種類": "実質改正", "A_分野": "交通・移動",
             "B_種類": "実質改正", "B_分野": "交通・移動", "系統2_種類": "実質改正", "系統2_分野": "交通・移動"}
        imp = {"y": {"id": "y", "分野": "交通・移動", "指標": "旅客輸送の付加価値", "判定": "保留", "理由": "国内：期間が足りない"}}
        r = old.decide_old(t, "1993-06-01", imp)
        self.assertEqual((r["結果"], r["指標"]), ("保留", "旅客輸送の付加価値"))
        self.assertIn("期間が足りない", r["理由"])

    def test_agreed_ab_but_line2_disagrees_is_held(self):
        t = {"id": "z", "題名": "例の弁護士資格の法律", "結果": "一致", "種類": "実質改正", "分野": "対応表なし", "A_種類": "実質改正",
             "A_分野": "対応表なし", "B_種類": "実質改正", "B_分野": "対応表なし", "系統2_種類": "実質改正", "系統2_分野": "専門サービス・研究開発"}
        r = old.decide_old(t, "1990-04-01", {})
        self.assertEqual((r["結果"], r["経路"]), ("保留", "振り分け保留"))
        self.assertIn("系統2", r["理由"])

    def test_direct_run_help(self):
        import subprocess
        import sys
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_old_laws_outcomes.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_missing_inputs_are_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(old.build(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
