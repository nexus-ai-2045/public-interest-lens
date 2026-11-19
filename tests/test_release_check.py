"""リリース前の総点検（scripts/release_check.py）の判定の検査。検査そのものは走らせない。"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_design_consistency as design
from scripts import release_check as rc


def _backtest(m0: str, t0: str) -> dict:
    return {"headline_aligned": {"verdict": m0}, "transplant": {"headline": {"verdict": t0}}, "target": 0.8, "min_n": 10}


class ReleaseCheckTest(unittest.TestCase):
    def test_plan_keeps_order_and_skip_verify(self):
        names = [name for name, _ in rc.plan(offline=True, skip_verify=False)]
        self.assertEqual(["ループの点検", "事前チェック（スモーク・E2E）", "CI と同じ検査"], names[:3])
        self.assertIn("ロジック検査（tests/test_evaluation_logic.py）", names)
        self.assertNotIn("CI と同じ検査", [name for name, _ in rc.plan(offline=True, skip_verify=True)])
        self.assertIn("--offline", rc.plan(offline=True, skip_verify=True)[1][1])

    def test_backtest_undecidable_is_warning_not_pass(self):
        self.assertEqual(rc.WARN, rc.backtest_step(_backtest("判定不能", "判定不能"))["status"])
        self.assertEqual(rc.WARN, rc.backtest_step(_backtest("達成", "判定不能"))["status"])
        self.assertEqual(rc.PASS, rc.backtest_step(_backtest("達成", "達成"))["status"])
        self.assertEqual(rc.FAIL, rc.backtest_step(_backtest("未達", "判定不能"))["status"])

    def test_members_step_checks_exposure_ranking(self):
        persons_csv = "人物ID,氏名\n" + "\n".join(f"P{i},人{i}" for i in (1, 2)) + "\n"

        def tree(root: Path, persons: str | None, exposure: dict | None) -> None:
            if persons is not None:
                path = root / "data" / "derived" / "person-ids" / "persons.csv"
                path.parent.mkdir(parents=True)
                path.write_text(persons, encoding="utf-8")
            if exposure is not None:
                path = root / design.EXPOSURE
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(exposure), encoding="utf-8")

        full = {"people": [{"actorId": "P1", "tier": 3}, {"actorId": "P2", "tier": None, "unrankedReason": "関与なし"}],
                "coverage": {"ledger": 2, "ranked": 1, "unrankedWithAmount": 0, "noInvolvement": 1}}
        cases = [
            ("出力が無ければ未測定", persons_csv, None, rc.WARN),
            ("台帳が0人なら未測定（0件を合格にしない）", "人物ID,氏名\n", full, rc.WARN),
            ("台帳が無ければ未測定", None, full, rc.WARN),
            ("全員そろえば合格", persons_csv, full, rc.PASS),
            ("1人欠ければ失敗", persons_csv, {**full, "people": full["people"][:1]}, rc.FAIL),
            ("点なしで理由が空なら失敗", persons_csv, {**full, "people": [full["people"][0], {"actorId": "P2", "tier": None, "unrankedReason": ""}]}, rc.FAIL),
            ("全員そろっても点ありが0人なら未測定", persons_csv,
             {"people": [{"actorId": f"P{i}", "tier": None, "unrankedReason": "関与なし"} for i in (1, 2)],
              "coverage": {"ledger": 2, "ranked": 0, "unrankedWithAmount": 0, "noInvolvement": 2}}, rc.WARN),
        ]
        for label, persons, exposure, want in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                tree(Path(tmp), persons, exposure)
                self.assertEqual(want, rc.members_step(Path(tmp))["status"])

    def test_members_step_imports_when_run_as_a_script(self):
        # python3 scripts/release_check.py で起動すると sys.path[0] は scripts/。そのときも `from scripts import …` が読めること
        import subprocess
        import sys
        code = "import runpy, sys; sys.path[:] = [p for p in sys.path if p not in ('', '.')]; " \
               "g = runpy.run_path('scripts/release_check.py', run_name='not_main'); print(g['members_step']()['status'])"
        out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertNotIn("ModuleNotFoundError", out.stdout + out.stderr)

    def test_exposure_ranking_is_not_in_the_public_directory(self):
        # 曝露ランキング（人別の額）は、表示を解く（設計決定0008 の確認）まで公開ディレクトリに置かない。ビルドに乗ると公開サイトから取れる
        public = Path(__file__).resolve().parents[1] / "app" / "public"
        self.assertNotIn("app/public", str(design.EXPOSURE))
        leaked = [str(p) for p in public.rglob("*.json") if "exposure-ranking" in p.name or '"actorKind"' in p.read_text(encoding="utf-8", errors="ignore")]
        self.assertEqual([], leaked)

    def test_unreadable_result_becomes_failure_and_keeps_going(self):
        from unittest import mock
        with mock.patch.object(rc, "_json_from", side_effect=ValueError("終了コード 1：boom")), \
                mock.patch.object(rc, "members_step", side_effect=AttributeError("x")):
            steps = rc.measured_steps()
        self.assertEqual({rc.FAIL}, {s["status"] for s in steps})
        self.assertEqual(3, len(steps))
        self.assertIn("boom", steps[0]["detail"])

    def test_design_steps_map_completion_states(self):
        report = {"ok": False, "reasons": ["定数の不一致 1 件"], "completion": [
            {"no": 1, "name": "評価台帳", "state": "一部達成", "now": "a"},
            {"no": 2, "name": "ロジック", "state": "達成", "now": "b"},
            {"no": 3, "name": "抜き取り", "state": "未達", "now": "c"},
            {"no": 4, "name": "公開前検査", "state": "未達", "now": "d"},
            {"no": 5, "name": "仮", "state": "未実行", "now": "e"}]}
        steps = rc.design_steps(report)
        self.assertEqual([rc.FAIL, rc.WARN, rc.PASS, rc.FAIL, rc.WARN], [s["status"] for s in steps])
        self.assertFalse(any("条件4" in s["step"] for s in steps))  # 4 は総点検そのもの

    def test_summary_separates_warning_from_pass(self):
        ok = [{"step": "a", "status": rc.PASS}]
        self.assertIn("すべて合格", rc.summary_line(ok))
        warned = rc.summary_line(ok + [{"step": "b", "status": rc.WARN}])
        self.assertNotIn("すべて合格", warned)
        self.assertIn("注意 1 件", warned)
        self.assertIn("配信しない", rc.summary_line(ok + [{"step": "c", "status": rc.FAIL}]))


if __name__ == "__main__":
    unittest.main()
