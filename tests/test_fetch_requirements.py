"""週2回の自動更新が使う外部の部品が、scripts/requirements-fetch.txt と workflow にそろっているか。

取得のスクリプトが一覧に無い部品を使い始めると、Actions では段が ModuleNotFoundError で落ちる
（2026-11：openpyxl・pdftotext・pypdf が1つずつ見つかった）。ここで先に落とす。
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REQUIREMENTS = SCRIPTS / "requirements-fetch.txt"
WORKFLOW = ROOT / ".github/workflows/weekly-update.yml"
# 週2回の自動更新が回す入口（daily_update.py の取得の段と再計算の入口）
ENTRIES = ["daily_update", "rebuild_public", "check_data_shrink", "roadmap_check", "fetch_shugiin_bill_census",
           "fetch_enforcement_dates", "fetch_oecd_industry", "fetch_intl_stats", "fetch_diet_minutes", "fetch_bill_speeches",
           "split_shared_speeches", "fetch_fiscal", "fetch_fiscal_more", "fetch_monetary", "fetch_target_series"]
# pip の名前と import の名前が違うもの
IMPORT_NAMES = {}
# OS ごとの分岐で片方しか使わない標準の部品
PLATFORM_ONLY = {"msvcrt", "winreg", "_winapi"}
COMMANDS = {"pdftotext": "poppler-utils", "pdfinfo": "poppler-utils", "pdftoppm": "poppler-utils"}


def closure() -> tuple[set[str], set[str]]:
    """入口から scripts の中の import をたどり、外部の部品の名前と、呼ぶコマンドの名前を返す。"""
    local = {p.stem for p in SCRIPTS.glob("*.py")}
    seen, external, commands = set(), set(), set()
    todo = list(ENTRIES)
    while todo:
        name = todo.pop()
        path = SCRIPTS / f"{name}.py"
        if name in seen or not path.exists():
            continue
        seen.add(name)
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module] + ([f"scripts.{a.name}" for a in node.names] if node.module == "scripts" else [])
            for module in modules:
                parts = module.split(".")
                if parts[0] == "scripts":
                    todo += parts[1:2]
                elif parts[0] in local:
                    todo.append(parts[0])
                elif parts[0] not in sys.stdlib_module_names and parts[0] not in PLATFORM_ONLY:
                    external.add(parts[0])
        commands |= {c for c in COMMANDS if re.search(rf"[\"']{c}[\"']", source)}
    return external, commands


class FetchRequirementsTest(unittest.TestCase):
    def test_every_external_module_is_listed(self):
        listed = {line.split("==")[0].strip().lower() for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")}
        external, _ = closure()
        missing = sorted(m for m in external if IMPORT_NAMES.get(m, m).lower() not in listed)
        self.assertEqual(missing, [], "scripts/requirements-fetch.txt に足す")
        self.assertTrue(all("==" in line for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
                            if line.strip() and not line.startswith("#")), "版を固定する")

    def test_workflow_installs_the_list_and_the_commands(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("pip install --disable-pip-version-check -r scripts/requirements-fetch.txt", workflow)
        _, commands = closure()
        apt = next(line for line in workflow.splitlines() if "apt-get install" in line)
        for command in commands:
            self.assertIn(COMMANDS[command], apt, command)
        self.assertIn("poppler-data", apt)  # 埋め込みの無い日本語フォントの PDF（骨太 2018・2020）を読むのに要る


if __name__ == "__main__":
    unittest.main()
