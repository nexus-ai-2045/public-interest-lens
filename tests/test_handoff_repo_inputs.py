"""当て直し手順と測定台本が、リポジトリに無い入力を前提にしないこと。

原因: 手順と測定台本が、リポジトリに無い共有フォルダ上の入力を前提にしていた。
見るのは、手順のコマンドが通るか、作業フォルダが無いときに台本が止めるか、
手順書と台本がリポジトリ外の絶対パスや共有フォルダを参照していないか。
"""
import csv
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs/reports/handoff-2026-11-20"
PROCEDURE = HANDOFF / "当て直し_外部実行の手順_2026-11-20.md"
EGOV = HANDOFF / "e-Gov結び付き率"
ALL_DIR = ROOT / "data/derived/primary-triage-v1/all"

MISSING = "EGOV_WORKDIR が無い"
NO_EMPTY = "空の結果"
ABS_PATH = re.compile(
    r"(?<![A-Za-z0-9_.:])/(?:mnt|Users|home|Volumes|opt|private|var|tmp)(?:/[0-9A-Za-z._+\-]+)+"
)
SHARED_FILE = re.compile(r"共有フォルダ[^\n]{0,80}?`([^`\n]+)`")
QUOTED_DATA = re.compile(r"""['\"]([^'\"]+\.(?:csv|jsonl|json))['\"]""")
PATH_TOKEN = re.compile(r"(?<![\w./])((?:[\w.\-]+/)+[\w.\-]+\.(?:py|md|csv))")


def procedure_commands(text: str) -> list[str]:
    commands = []
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.S):
        for line in block.splitlines():
            body = line.split(" #", 1)[0].strip()
            if body and not body.startswith("#"):
                commands.append(body)
    return commands


def path_tokens(command: str) -> list[str]:
    found = []
    for raw in command.replace("&&", " ").split():
        if raw.startswith("-") or raw in {"python3", "python"}:
            continue
        if raw.startswith("/") or "/" in raw or raw.endswith((".csv", ".py", ".md", ".json")):
            found.append(raw)
    return found


def outside_refs(text: str) -> list[str]:
    hits = ABS_PATH.findall(text)
    for match in SHARED_FILE.finditer(text):
        inner = match.group(1).strip()
        if "/" in inner or inner.endswith((".md", ".csv", ".py", ".json")):
            hits.append(match.group(0))
    return hits


def unbundled_scripts(directory: Path) -> list[Path]:
    """台本の隣にもリポジトリの直下にも無いデータを開く台本。"""
    found = []
    for path in sorted(directory.glob("*.py")):
        missing = []
        for name in QUOTED_DATA.findall(path.read_text(encoding="utf-8")):
            if name.startswith("http"):
                continue
            if (directory / name).exists() or (ROOT / name).exists():
                continue
            missing.append(name)
        if missing:
            found.append(path)
    return found


def run_script(path: Path, env: dict) -> subprocess.CompletedProcess[str]:
    clean = env.copy()
    # 実行時のバイトコードは測定結果ではない。結果ファイルの有無をそれと分けて見る。
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        env=clean,
        capture_output=True,
        text=True,
        timeout=30,
    )


def result_names(directory: Path) -> set[str]:
    """測定結果の名前。Python が作る __pycache__ は結果ではない。"""
    return {p.name for p in directory.iterdir() if p.name != "__pycache__"}


class BundledListProcedureTest(unittest.TestCase):
    def test_commands_that_take_the_bundled_list_use_only_repo_files(self):
        commands = procedure_commands(PROCEDURE.read_text(encoding="utf-8"))
        taken = [c for c in commands if "--extra" in c or "--ids" in c]
        self.assertGreaterEqual(len(taken), 2)
        for command in commands:
            for token in path_tokens(command):
                self.assertFalse(token.startswith("/"), token)
                self.assertNotIn("共有フォルダ", token)
                path = (ROOT / token).resolve()
                self.assertTrue(ROOT == path or ROOT in path.parents, token)
                self.assertTrue(path.is_file(), token)
        snapshot = (ALL_DIR / "targets.csv").read_bytes()
        before = {p.name for p in ALL_DIR.iterdir()}
        try:
            for command in taken:
                proc = subprocess.run(
                    command.split(),
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                self.assertNotIn("Traceback", proc.stderr)
        finally:
            (ALL_DIR / "targets.csv").write_bytes(snapshot)
            for path in ALL_DIR.iterdir():
                if path.name not in before:
                    path.unlink()

    def test_compare_lists_every_id_in_the_bundled_file(self):
        text = PROCEDURE.read_text(encoding="utf-8")
        compare = next(c for c in procedure_commands(text) if "--ids" in c)
        ids_path = next(ROOT / token for token in path_tokens(compare) if token.endswith(".csv"))
        with ids_path.open(encoding="utf-8", newline="") as handle:
            ids = list(csv.DictReader(handle))
        self.assertIn("id", ids[0])
        before = {p.name for p in ALL_DIR.iterdir()}
        try:
            proc = subprocess.run(
                compare.split(),
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(f"{len(ids)} 本", proc.stdout)
        finally:
            for path in ALL_DIR.iterdir():
                if path.name not in before:
                    path.unlink()


class MissingWorkdirTest(unittest.TestCase):
    def test_scripts_that_need_unbundled_inputs_stop_clearly(self):
        scripts = unbundled_scripts(EGOV)
        self.assertGreaterEqual(len(scripts), 3)
        before = result_names(EGOV)
        for label, raw in (("unset", None), ("empty", "")):
            env = os.environ.copy()
            if raw is None:
                env.pop("EGOV_WORKDIR", None)
            else:
                env["EGOV_WORKDIR"] = raw
            for path in scripts:
                with self.subTest(script=path.name, workdir=label):
                    proc = run_script(path, env)
                    self.assertEqual(proc.returncode, 2, proc.stderr)
                    self.assertIn(MISSING, proc.stderr)
                    self.assertIn(NO_EMPTY, proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)
                    self.assertNotIn("Traceback", proc.stdout)
                    self.assertEqual(proc.stdout, "")
        self.assertEqual(result_names(EGOV), before)

    def test_present_workdir_is_not_reported_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "cache.jsonl").write_text('{"v":{"laws":[]}}\n', encoding="utf-8")
            (folder / "result.csv").write_text("id,改正元_law_id,e-Govに本体,題名\n", encoding="utf-8")
            (folder / "fallback.csv").write_text("id,一致数,名前,category\n", encoding="utf-8")
            env = os.environ.copy()
            env["EGOV_WORKDIR"] = str(folder)
            proc = run_script(EGOV / "bridgelib.py", env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(MISSING, proc.stderr + proc.stdout)


class OutsidePathTest(unittest.TestCase):
    def test_procedure_and_scripts_do_not_point_outside_the_repo(self):
        text = PROCEDURE.read_text(encoding="utf-8")
        paths = [PROCEDURE]
        for token in PATH_TOKEN.findall(text):
            path = ROOT / token
            if path.is_file() and path.suffix in {".py", ".md"}:
                paths.append(path)
        paths.extend(HANDOFF.rglob("*.py"))
        seen = set()
        offenders = []
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            hits = outside_refs(path.read_text(encoding="utf-8"))
            if hits:
                offenders.append(f"{path.relative_to(ROOT)}: {hits}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
