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

    def test_one_column_blanked_in_a_wide_table_is_found(self):
        # 12列の表で1列だけ空になっても、全体のセル数は 1/12 しか減らない。列ごとに見て拾う（2026-11-19 の変異テスト）
        def wide(url: bool) -> bytes:
            head = ",".join([f"c{i}" for i in range(11)] + ["証拠URL"]) + "\n"
            return (head + "".join(",".join(["x"] * 11 + ["https://a" if url else ""]) + "\n" for _ in range(100))).encode("utf-8")
        finding = guard.judge("data/a.csv", wide(True), wide(False))
        self.assertEqual(finding.reason, "列「証拠URL」の中身のあるセル 100 → 0")

    def test_dropped_column_is_found_and_sparse_columns_are_not_judged(self):
        before = ("id,値,備考\n" + "".join(f"{i},x,{'m' if i < 10 else ''}\n" for i in range(100))).encode("utf-8")
        self.assertIsNone(guard.judge("data/a.csv", before, before.replace(b",m\n", b",\n")))  # 備考は 10 セルだけなので見ない
        wide = ",".join(f"c{i}" for i in range(12)) + "\n" + ("x," * 11 + "x\n") * 100
        narrow = ",".join(f"c{i}" for i in range(11)) + "\n" + ("x," * 10 + "x\n") * 100
        self.assertEqual(guard.judge("data/a.csv", wide.encode(), narrow.encode()).reason, "列「c11」が消えた（中身のあるセル 100）")

    def test_blank_rows_do_not_count_as_rows(self):
        blanked = "id,値\n".encode("utf-8") + b"\n" * 60 + b",\n" * 40
        self.assertEqual(guard.judge("data/a.csv", table(100), blanked).reason, "行数 100 → 0")

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
