"""python -m scripts.X --help の守り（scripts/__init__.py）と、入口の雛形（scripts/new_script.py）。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.new_script import create
from tests.test_scripts_parse_help import ignores_help

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class HelpGuardTest(unittest.TestCase):
    def run_m(self, name: str, *args: str, joined: bool = False) -> subprocess.CompletedProcess:
        head = [f"-mscripts.{name}"] if joined else ["-m", f"scripts.{name}"]
        return subprocess.run([sys.executable, *head, *args], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)

    def test_entry_without_parser_does_not_run_on_help(self):
        # #234 の直前の parse_cabinet.py と同じ形：argparse なしで、実行すると書き込む入口
        # scripts/ 直下に置くと、並行して走る入口の検査（*.py の一覧）に拾われるので、使い捨ての下位の場所に置く
        sub = Path(tempfile.mkdtemp(dir=SCRIPTS, prefix="_probe_"))
        probe = sub / "entry.py"
        name = f"{sub.name}.entry"
        marker = sub / "書かれた.txt"
        # 説明に ArgumentParser と書いてあるだけの入口も守る（文字列ではなく、実際の呼び出しを見る）
        probe.write_text(f'"""試験用の入口。ArgumentParser は使わない。"""\nfrom pathlib import Path\n\nif __name__ == "__main__":\n    Path({str(marker)!r}).write_text("x")\n', encoding="utf-8")
        try:
            p = self.run_m(name, "--help")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("試験用の入口", p.stdout)
            self.assertFalse(marker.exists(), "--help で本番の処理が走った")
            p = self.run_m(name, "--help", joined=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertFalse(marker.exists(), "-mscripts.X（間を空けない形）の --help で本番の処理が走った")
            self.run_m(name)
            self.assertTrue(marker.exists(), "--help の無いときは普通に走る")
        finally:
            shutil.rmtree(sub)

    def test_entry_with_parser_keeps_its_own_help(self):
        p = self.run_m("new_script", "--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("usage:", p.stdout)


class NewScriptTest(unittest.TestCase):
    def test_template_parses_help_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = create("build_example", "例の入口。", Path(d))
            text = path.read_text(encoding="utf-8")
            self.assertFalse(ignores_help(text))
            p = subprocess.run([sys.executable, str(path), "--help"], capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("例の入口。", p.stdout)
            with self.assertRaises(FileExistsError):
                create("build_example", "例の入口。", Path(d))
        with self.assertRaises(ValueError):
            create("Build-Foo", "x", Path(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
