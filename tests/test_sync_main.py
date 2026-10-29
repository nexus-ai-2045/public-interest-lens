import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import sync_main


def git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)


class SyncMainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "w"
        remote = Path(self.tmp.name) / "r.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        # 名義は一時リポジトリのローカル設定に置く（実行環境の git 設定に頼らない。rebase --continue も同じ設定を読む）
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "remote", "add", "origin", str(remote))
        (self.root / "gen.txt").write_text("base\n")
        (self.root / "other.txt").write_text("base\n")
        git(self.root, "add", "-A"); git(self.root, "commit", "-q", "-m", "base"); git(self.root, "push", "-q", "origin", "main")
        self._old = (sync_main.ROOT, sync_main.GENERATED)
        sync_main.ROOT = self.root
        sync_main.GENERATED = [("gen.txt", [[sys.executable, "-c", "import pathlib; pathlib.Path('gen.txt').write_text('regenerated\\n')"]])]
        self.argv = sys.argv
        sys.argv = ["sync_main"]

    def tearDown(self):
        sync_main.ROOT, sync_main.GENERATED = self._old
        sys.argv = self.argv
        self.tmp.cleanup()

    def advance_main(self, name):
        git(self.root, "checkout", "-q", "-b", "tmp-main", "main")
        (self.root / name).write_text("main moved\n")
        git(self.root, "commit", "-qam", "main moved"); git(self.root, "push", "-q", "origin", "tmp-main:main")
        git(self.root, "checkout", "-q", "work"); git(self.root, "branch", "-q", "-D", "tmp-main")

    def test_generated_only_conflict_is_regenerated(self):
        git(self.root, "checkout", "-q", "-b", "work")
        (self.root / "gen.txt").write_text("work\n"); git(self.root, "commit", "-qam", "work")
        self.advance_main("gen.txt")
        self.assertEqual(0, sync_main.main())
        self.assertEqual("regenerated\n", (self.root / "gen.txt").read_text())

    def test_other_conflict_aborts_without_half_state(self):
        git(self.root, "checkout", "-q", "-b", "work")
        (self.root / "other.txt").write_text("work\n"); git(self.root, "commit", "-qam", "work")
        self.advance_main("other.txt")
        self.assertEqual(1, sync_main.main())
        self.assertFalse((self.root / ".git" / "rebase-merge").exists())


if __name__ == "__main__":
    unittest.main()
