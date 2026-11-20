"""公開前の安全性が、今のコードで破れる経路の再現。

望む振る舞いで書いてある。今のコードでは失敗する。直すのは別の変更にする。
@unittest.expectedFailure は、失敗が期待どおりである印。通るようになったら外す。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_public_ranking, generate_artifacts, source_check


class PublishGateTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_ranking_cli_holds_out_a_law_the_fresh_check_rejects(self):
        """公開ランキングのコマンドは、今の中身を出典チェックし、不一致の額を書いてから終える。"""
        bad = "衆法-1-1"
        checked = {}

        def fake_build(approve_all, approved_at, held_by_check=None):
            laws = [] if held_by_check and bad in held_by_check else [{"id": bad, "amountMedianYen": 10}]
            return {"laws": laws, "others": []}

        def fake_check(ranking, ctx):
            checked["called"] = True
            return [], {"heldOut": [bad], "mismatch": 1, "items": 1, "match": 0, "notApplicable": 0}

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "ranking.json"
            argv = ["build_public_ranking", "--approve-all-laws", "--approved-at", "2026-10-17", "--output", str(out)]
            with mock.patch.object(build_public_ranking, "build", fake_build), \
                 mock.patch.object(source_check, "check", fake_check), \
                 mock.patch.object(source_check, "context", return_value={}), \
                 mock.patch.object(sys, "argv", argv):
                build_public_ranking.main()
            written = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(checked.get("called"))
        self.assertNotIn(bad, {law["id"] for law in written["laws"]})

    @unittest.expectedFailure
    def test_generate_reruns_source_check_when_ranking_is_newer_than_inputs(self):
        """入力より新しい ranking.json でも、出典チェックの生成を飛ばさない。"""
        commands = []

        def fake_run(command, cwd=None, stdout=None):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as directory:
            ranking = Path(directory) / "ranking.json"
            ranking.write_text("{}\n", encoding="utf-8")
            steps = [("inputs", ranking, [sys.executable, "scripts/source_check.py", "--generate-ranking"])]
            env = os.environ.get("KOKUZOKU_SKIP_GENERATE")
            os.environ.pop("KOKUZOKU_SKIP_GENERATE", None)
            try:
                with mock.patch.object(generate_artifacts, "STEPS", steps), \
                     mock.patch.object(generate_artifacts, "newest_input", return_value=0.0), \
                     mock.patch.object(generate_artifacts.subprocess, "run", fake_run):
                    code = generate_artifacts.main([])
            finally:
                if env is not None:
                    os.environ["KOKUZOKU_SKIP_GENERATE"] = env
        self.assertEqual(code, 0)
        self.assertTrue(any("source_check.py" in part for command in commands for part in command))

    @unittest.expectedFailure
    def test_interrupted_ranking_write_keeps_the_previous_file(self):
        """ranking.json の書き込みが途中で切れても、前の完全なファイルが残る。"""
        previous = {"schema": "public-ranking/v3", "laws": [{"id": "kept", "amountMedianYen": 1}]}
        payload = {"schema": "public-ranking/v3", "laws": [{"id": "new", "amountMedianYen": 2}]}
        summary = {"heldOut": [], "mismatch": 0, "items": 0, "match": 0, "notApplicable": 0}
        original = Path.write_text

        with tempfile.TemporaryDirectory() as directory:
            ranking = Path(directory) / "ranking.json"
            ranking.write_text(json.dumps(previous), encoding="utf-8")

            def crash_write(self, data, encoding=None, errors=None, newline=None):
                if Path(self) == ranking:
                    with open(self, "w", encoding=encoding or "utf-8") as handle:
                        handle.write(data[:12])
                    raise RuntimeError("interrupt")
                return original(self, data, encoding=encoding, errors=errors, newline=newline)

            with mock.patch.object(build_public_ranking, "build", return_value=payload), \
                 mock.patch.object(source_check, "check", return_value=([], summary)), \
                 mock.patch.object(source_check, "context", return_value={}), \
                 mock.patch.object(source_check, "write_report"), \
                 mock.patch.object(Path, "write_text", crash_write):
                with self.assertRaises(RuntimeError):
                    source_check.rebuild(True, "2026-10-17", ranking, write=True)
            self.assertEqual(json.loads(ranking.read_text(encoding="utf-8")), previous)

    @unittest.expectedFailure
    def test_member_page_allowlist_guard_is_present(self):
        """ADR 0008 と R11 が名指しする議員ページの許可リスト検査が、リポジトリにある。"""
        self.assertTrue((ROOT / "tests" / "test_public_members_safety.py").is_file())


if __name__ == "__main__":
    unittest.main()
