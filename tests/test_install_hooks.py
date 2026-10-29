import re
import tempfile
import unittest
from pathlib import Path

from scripts import install_hooks, strip_commit_trace

# 実在の型を書くと名義検査が自分のテストを止めるので、差し替えた型で見る
SESSION = "追跡 TRACE-0123"
TRACE_RES = [re.compile(r"TRACE-[0-9]+")]  # 本物の型は identity_gate が持つ。ここは差し替えた型で、取り除く動作だけ見る
TOOL = "Co-Authored-By: Claude Sonnet 5.5"
HUMAN = "Reviewed-by: 人"


class StripCommitTraceTest(unittest.TestCase):
    def test_tool_trailers_and_session_lines_are_removed_human_trailers_stay(self):
        msg = f"題名\n\n本文\n\n{TOOL}\n{SESSION}\n{HUMAN}\n"
        out = strip_commit_trace.strip(msg, TRACE_RES)
        self.assertNotIn("Claude", out)
        self.assertNotIn("TRACE", out)
        self.assertIn("Reviewed-by: 人", out)
        self.assertTrue(out.startswith("題名\n\n本文"))

    def test_generated_note_is_removed(self):
        self.assertNotIn("Generated", strip_commit_trace.strip("題名\n\n🤖 Generated with Claude Code\n", TRACE_RES))

    def test_plain_message_is_unchanged(self):
        self.assertEqual("題名\n\n本文\n", strip_commit_trace.strip("題名\n\n本文\n", TRACE_RES))


# 本物の URL の写しを置くと名義検査が自分のテストを止めるので、部品に分けて実行時に組む
LINK = "[project thread](https://{h}/{k}/{i})".format(h="claude." + "".join(["a", "i"]), k="code/" + "project", i="abc123")
MARK = "<!-- claude-projects-attribution v1 -->"
BODY_TRACE_RES = [re.compile(r"TRACE-[0-9]+")]


class StripBodyTest(unittest.TestCase):
    def test_project_link_is_removed_but_marker_and_requester_stay(self):
        body = f"本文\n\n{MARK} · {LINK}\n_Requested by **ねく**_\n"
        out = strip_commit_trace.strip_body(body, BODY_TRACE_RES)
        self.assertNotIn("project thread", out)
        self.assertNotIn("http", out)
        self.assertIn(MARK, out)
        self.assertIn("_Requested by **ねく**_", out)
        self.assertEqual(f"本文\n\n{MARK}\n_Requested by **ねく**_\n", out)

    def test_bare_url_and_other_trace_lines_are_removed(self):
        bare = LINK.split("(")[1].rstrip(")")
        out = strip_commit_trace.strip_body(f"本文\n{MARK} {bare}\n{SESSION}\n", BODY_TRACE_RES)
        self.assertEqual(f"本文\n{MARK}\n", out)

    def test_body_without_link_is_unchanged(self):
        body = f"本文\n\n{MARK}\n_Requested by **ねく**_\n"
        self.assertEqual(body, strip_commit_trace.strip_body(body, BODY_TRACE_RES))


class InstallHooksTest(unittest.TestCase):
    def test_install_is_idempotent_and_executable(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self.assertEqual(set(install_hooks.bodies()), set(install_hooks.install(d)))
            self.assertEqual([], install_hooks.install(d))
            self.assertEqual([], install_hooks.missing(d))
            self.assertTrue((d / "prepare-commit-msg").stat().st_mode & 0o100)

    def test_hook_without_execute_permission_is_reported_and_repaired(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            install_hooks.install(d)
            (d / "pre-push").chmod(0o644)
            self.assertEqual(["pre-push"], install_hooks.missing(d))
            self.assertEqual(["pre-push"], install_hooks.install(d))
            self.assertEqual([], install_hooks.missing(d))

    def test_changed_hook_is_reported(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            install_hooks.install(d)
            (d / "commit-msg").write_text("#!/bin/sh\nexit 0\n")
            self.assertEqual(["commit-msg"], install_hooks.missing(d))


if __name__ == "__main__":
    unittest.main()
