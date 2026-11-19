import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_data_shrink as guard


def table(rows: int, filled: bool = True) -> bytes:
    return ("id,値\n" + "".join(f"{i},{'x' if filled else ''}\n" for i in range(rows))).encode("utf-8")


class JudgeTests(unittest.TestCase):
    def test_large_row_drop_is_found(self):
        finding = guard.judge("data/a.csv", table(12720), table(581))
        self.assertEqual(finding.reason, "行数 12,720 → 581")

    def test_growth_and_small_drop_pass(self):
        self.assertIsNone(guard.judge("data/a.csv", table(100), table(120)))
        self.assertIsNone(guard.judge("data/a.csv", table(100), table(90)))  # ちょうど1割は通す
        self.assertIsNotNone(guard.judge("data/a.csv", table(100), table(89)))

    def test_small_tables_are_not_judged_by_ratio(self):
        self.assertIsNone(guard.judge("data/a.csv", table(49), table(1)))

    def test_rows_kept_but_cells_blanked_is_found(self):
        finding = guard.judge("data/a.csv", table(100), table(100, filled=False))
        self.assertIn("中身のあるセル 200 → 100", finding.reason)

    def test_deleted_and_emptied_files_are_found(self):
        self.assertEqual(guard.judge("data/a.csv", table(3), None).reason, "ファイルが消えた")
        self.assertEqual(guard.judge("app/public/a.json", b"{}", b"\n").reason, "ファイルが空になった")

    def test_other_files_are_judged_by_size(self):
        self.assertIsNotNone(guard.judge("app/public/a.json", b"x" * 20000, b"x" * 13000))
        self.assertIsNone(guard.judge("app/public/a.json", b"x" * 20000, b"x" * 15000))
        self.assertIsNone(guard.judge("app/public/a.json", b"x" * 5000, b"x" * 10))


class CheckTests(unittest.TestCase):
    def test_compares_tracked_files_with_the_base_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args: str) -> None:
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                                "-c", "core.hooksPath=/dev/null", *args], cwd=root, check=True, capture_output=True)

            (root / "data").mkdir()
            (root / "other").mkdir()
            for name in ("shrunk.csv", "grown.csv", "gone.csv", "日本語 の名前.csv"):
                (root / "data" / name).write_bytes(table(100))
            (root / "other" / "outside.csv").write_bytes(table(100))
            git("init", "-q")
            git("add", ".")
            git("commit", "-q", "-m", "base")
            (root / "data" / "shrunk.csv").write_bytes(table(10))
            (root / "data" / "grown.csv").write_bytes(table(200))
            (root / "data" / "gone.csv").unlink()
            (root / "data" / "日本語 の名前.csv").write_bytes(table(5))
            (root / "data" / "new.csv").write_bytes(table(1))  # 追っていない新しいファイルは見ない
            (root / "other" / "outside.csv").write_bytes(table(1))  # 対象の場所の外は見ない
            findings = guard.check(root, "HEAD", ["data"])
            self.assertEqual(sorted(f.path for f in findings), ["data/gone.csv", "data/shrunk.csv", "data/日本語 の名前.csv"])


if __name__ == "__main__":
    unittest.main()
