import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import install_hooks


class InstallHooksTest(unittest.TestCase):
    def test_install_is_idempotent_and_executable(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            self.assertEqual(set(install_hooks.bodies()), set(install_hooks.install(d)))
            self.assertEqual([], install_hooks.install(d))
            self.assertEqual([], install_hooks.missing(d))
            self.assertTrue((d / "pre-push").stat().st_mode & 0o100)

    def test_obsolete_hook_written_by_this_script_is_removed_but_human_hook_stays(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "prepare-commit-msg").write_text(install_hooks.HEADER + "python3 old.py\n")
            # 古いフックが残っていると、検査（--check）は「足りない」と言い、install は消したことを返す
            self.assertIn("prepare-commit-msg", install_hooks.missing(d))
            self.assertIn("prepare-commit-msg", install_hooks.install(d))
            self.assertNotIn("prepare-commit-msg", install_hooks.missing(d))
            self.assertFalse((d / "prepare-commit-msg").exists())
            (d / "prepare-commit-msg").write_text("#!/bin/sh\n# 人が書いたフック\n")
            install_hooks.install(d)
            self.assertTrue((d / "prepare-commit-msg").exists())

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


class SharedHooksPathTest(unittest.TestCase):
    def test_hooks_dir_outside_the_repo_is_not_repo_local(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(install_hooks.is_repo_local(Path(t)))

    def test_main_refuses_and_writes_nothing_when_hooks_path_is_shared(self):
        with tempfile.TemporaryDirectory() as t:
            shared = Path(t)
            real = install_hooks.hooks_dir
            install_hooks.hooks_dir = lambda: shared
            try:
                with mock.patch("sys.argv", ["install_hooks.py"]):
                    self.assertEqual(2, install_hooks.main())
            finally:
                install_hooks.hooks_dir = real
            self.assertEqual([], list(shared.iterdir()))


if __name__ == "__main__":
    unittest.main()
