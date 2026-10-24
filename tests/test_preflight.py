"""事前チェック（scripts/preflight.py）の検査。通信は使わない（--offline 相当）。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import preflight


class PreflightTest(unittest.TestCase):
    def test_dry_run_covers_every_pipeline_step(self):
        scripts = preflight.pipeline_scripts()
        self.assertGreaterEqual(len(scripts), 8)  # 作り直しの本体と、1〜7 の段のスクリプト
        items = preflight.dry_run(scripts)
        self.assertEqual(len(scripts), len(items))
        self.assertEqual([], [i for i in items if i.status != "合格"])

    def test_help_screens_start(self):
        self.assertEqual([], [i for i in preflight.help_screens() if i.status != "合格"])

    def test_help_modules_parse_arguments(self):
        # --help を解釈しない入口を実行すると生成物が書き換わるので、ArgumentParser のあるものだけにする。
        for module in preflight.HELP_MODULES:
            source = preflight.ROOT / (module.replace(".", "/") + ".py")
            self.assertIn("ArgumentParser", source.read_text(encoding="utf-8"), module)

    def test_unreachable_host_is_warning_not_failure(self):
        with mock.patch.object(preflight.daily_update, "reachable", return_value=False):
            items = preflight.network(offline=False)
        self.assertTrue(items)
        self.assertEqual({"注意"}, {i.status for i in items})

    def test_missing_script_fails(self):
        missing = preflight.ROOT / "scripts" / "no_such_script.py"
        self.assertEqual(["失敗"], [i.status for i in preflight.dry_run([missing])])

    def test_offline_run_has_no_failures_and_summary_counts(self):
        items = preflight.run_all(offline=True)
        failed = [i for i in items if i.status == "失敗" and i.check not in ("個人名義", "コミット名義")]  # CI の環境では名義が違う
        self.assertEqual([], failed)
        self.assertIn("事前チェック：合格", preflight.summary(items))

    def test_missing_executable_is_failure_not_crash(self):
        # node や npm が入っていない環境でも、例外で止まらず「失敗」の項目になる。
        with mock.patch.object(preflight.subprocess, "run", side_effect=FileNotFoundError("npm")):
            self.assertEqual(["失敗"], [i.status for i in preflight.smoke()])
            self.assertEqual(["失敗"], [i.status for i in preflight.roadmap()])
            self.assertEqual(["失敗"], [i.status for i in preflight.e2e()])

    def test_commit_identity_reports_without_value(self):
        good = f"nexus_ai <{preflight.NOREPLY}> 1760000000 +0900"
        def fake(committer):
            return lambda args, **kw: preflight.subprocess.CompletedProcess(
                args, 0, (committer if "GIT_COMMITTER_IDENT" in args else good) + "\n", "")
        with mock.patch.object(preflight, "_run", side_effect=fake(good)):
            self.assertEqual(["合格"], [i.status for i in preflight.commit_identity()])
        # 環境変数で記録者だけ別の名義になっていても見逃さない。
        with mock.patch.object(preflight, "_run", side_effect=fake("someone <someone@example.com> 1760000000 +0900")):
            item, = preflight.commit_identity()
        self.assertEqual("失敗", item.status)
        self.assertIn("記録者", item.detail)
        self.assertNotIn("someone", item.detail)

    def test_identity_full_history_failure_blocks(self):
        # 既定の check（--range 無し）が失敗なら注意へ下げない。全履歴の不一致は push 範囲の成功では通さない。
        # 場所の指定が無いときは、隣の検査を呼ぶ。
        def run(code):
            def _run(args, **kw):
                if args[:2] == ["git", "rev-parse"]:
                    return preflight.subprocess.CompletedProcess(args, 0, "false\n", "")
                self.assertEqual(args[1], str(preflight.IDENTITY_GUARD))
                self.assertIn("check", args)
                self.assertNotIn("--range", args)
                return preflight.subprocess.CompletedProcess(args, code, "", "停止\n")
            return _run
        unset = {"REPO_PREFLIGHT_ROOT": ""}
        with mock.patch.dict(os.environ, unset), \
                mock.patch.object(preflight.IDENTITY_GUARD.__class__, "exists", return_value=True), \
                mock.patch.object(preflight, "_run", side_effect=run(1)):
            self.assertEqual(["失敗"], [i.status for i in preflight.identity()])
        with mock.patch.dict(os.environ, unset), \
                mock.patch.object(preflight.IDENTITY_GUARD.__class__, "exists", return_value=True), \
                mock.patch.object(preflight, "_run", side_effect=run(0)):
            self.assertEqual(["合格"], [i.status for i in preflight.identity()])

    def test_unset_repo_preflight_root_keeps_missing_sibling_failure(self):
        def boom(args, **kw):
            raise AssertionError("検査を起動しない")
        with mock.patch.dict(os.environ, {"REPO_PREFLIGHT_ROOT": "   "}), \
                mock.patch.object(preflight.IDENTITY_GUARD.__class__, "exists", return_value=False), \
                mock.patch.object(preflight, "_run", side_effect=boom):
            item, = preflight.identity()
        self.assertEqual("失敗", item.status)
        self.assertIn("隣に無い", item.detail)

    def test_invalid_repo_preflight_root_fails_without_fallback_or_value(self):
        def boom(args, **kw):
            raise AssertionError("検査を起動しない")
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "not-a-preflight-root")
            script = str(Path(tmp) / "local_identity_guard.py")
            Path(script).write_text("print('not the root')\n", encoding="utf-8")
            for raw in (missing, script, str(Path(tmp))):
                with mock.patch.dict(os.environ, {"REPO_PREFLIGHT_ROOT": raw}), \
                        mock.patch.object(preflight.IDENTITY_GUARD.__class__, "exists", return_value=True), \
                        mock.patch.object(preflight, "_run", side_effect=boom):
                    item, = preflight.identity()
                self.assertEqual("失敗", item.status, raw)
                self.assertNotIn(tmp, item.detail)
                self.assertNotIn("隣に無い", item.detail)
                self.assertNotIn("not-a-preflight-root", item.detail)
                self.assertNotIn("local_identity_guard.py", item.detail)

    def test_valid_repo_preflight_root_runs_that_guard_and_keeps_check_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "real"
            guard = root / "scripts" / "local_identity_guard.py"
            guard.parent.mkdir(parents=True)
            guard.write_text("# stub\n", encoding="utf-8")
            link = Path(tmp) / "link"
            link.symlink_to(root, target_is_directory=True)
            seen = []

            def run(args, **kw):
                seen.append(list(args))
                if args[:2] == ["git", "rev-parse"]:
                    return preflight.subprocess.CompletedProcess(args, 0, "false\n", "")
                return preflight.subprocess.CompletedProcess(args, 1, "", "停止\n")

            quoted = '"' + os.path.relpath(link, os.getcwd()) + '"'
            with mock.patch.dict(os.environ, {"REPO_PREFLIGHT_ROOT": quoted}), \
                    mock.patch.object(preflight.IDENTITY_GUARD.__class__, "exists", return_value=True), \
                    mock.patch.object(preflight, "_run", side_effect=run):
                item, = preflight.identity()
            self.assertEqual("失敗", item.status)
            self.assertNotIn(tmp, item.detail)
            self.assertEqual(Path(seen[0][1]).resolve(), guard.resolve())
            self.assertNotEqual(Path(seen[0][1]).resolve(), preflight.IDENTITY_GUARD.resolve())
            self.assertIn("check", seen[0])
            self.assertNotIn("--range", seen[0])
            self.assertEqual(seen[0][-1], "check")


if __name__ == "__main__":
    unittest.main()
