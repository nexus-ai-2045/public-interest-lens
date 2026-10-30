"""小さい架空入力で、npm buildの生成後検査と停止順序を確かめる。"""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "node/npm が無い")
class MemberBuildGateTests(unittest.TestCase):
    def test_generated_members_are_checked_before_build(self):
        ranking = {"laws": [{"id": "fixture", "certainty": "高", "amountLowYen": 100,
                             "amountMedianYen": 100, "amountHighYen": 100}], "others": []}
        primary = {"laws": [{"id": "fixture", "amount": {"low": 100, "median": 100, "high": 100},
                             "observationLaws": 1, "game": {"party": {"median": 100},
                             "unidentified": {"median": 0}}, "source": "https://www.shugiin.go.jp/"}],
                   "members": [{"id": "架空検査人物", "name": "架空検査人物", "laws": []}]}
        reference = {"members": [{"id": "架空検査人物", "loss": {"median": 0}, "credit": {"median": 0}}]}
        with tempfile.TemporaryDirectory(prefix="member-gate-") as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            (root / "tests").mkdir()
            shutil.copy2(ROOT / "tests/test_public_members_safety.py", root / "tests")
            dist = root / "app/public/distribution"
            dist.mkdir(parents=True)
            (root / "app/node_modules").mkdir()
            (dist / "ranking.json").write_text(json.dumps(ranking), encoding="utf-8")
            # 物価・賛否・グラフ用の集計はこの検査の対象外。架空の空ファイルを置き、generate_artifacts.py は走らせない
            for unused in ("price-index.json", "votes.json", "charts.json"):
                (dist / unused).write_text("{}", encoding="utf-8")
            package = json.loads((ROOT / "app/package.json").read_text(encoding="utf-8"))
            package["scripts"]["build"] = 'node -e "require(\'fs\').writeFileSync(\'build-reached\', \'yes\')"'
            (root / "app/package.json").write_text(json.dumps(package), encoding="utf-8")
            for generator, output in (("build_public_members.mjs", "members.json"),
                                      ("build_reference_members.mjs", "members-reference.json")):
                (root / "scripts" / generator).write_text('''
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
const out = new URL('../app/public/distribution/OUTPUT', import.meta.url);
if (out.pathname.endsWith("members-reference.json")) appendFileSync(new URL("../app/reference-generator-runs", import.meta.url), "generated" + String.fromCharCode(10));
if (!process.argv.includes('--no-write')) writeFileSync(out, readFileSync(new URL('OUTPUT.fixture', import.meta.url)));
if (process.argv.includes('--attributions')) writeFileSync(process.argv[process.argv.indexOf('--attributions') + 1], 'member,name,house,lawId,role,side,median\\n');
'''.replace("OUTPUT", output), encoding="utf-8")
            for relative in ("acquired/bill-census-full/enacted.csv", "acquired/office-holders/cabinet.csv",
                             "acquired/sangiin-votes/votes_index.csv", "acquired/sangiin-votes/members.csv",
                             "derived/person-ids/persons.csv"):
                path = root / "data" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unused\n", encoding="utf-8")
            bad_amount = copy.deepcopy(primary)
            bad_amount["laws"][0]["amount"]["median"] = 101
            private_field = copy.deepcopy(primary)
            private_field["members"][0]["privateFixture"] = "架空項目"
            bad_reference = copy.deepcopy(reference)
            bad_reference["members"][0]["loss"]["median"] = 1
            cases = [(primary, reference, None), (bad_amount, reference, "議員ページの額"),
                     (private_field, reference, "許可していない項目が増えた"),
                     (primary, bad_reference, "配り先が無い")]
            marker = root / "app/build-reached"
            generation_calls = root / "app/reference-generator-runs"
            for member, ref, diagnostic in cases:
                with self.subTest(diagnostic=diagnostic):
                    marker.unlink(missing_ok=True)
                    generation_calls.unlink(missing_ok=True)
                    for name, payload in (("members.json", member), ("members-reference.json", ref)):
                        (root / "scripts" / (name + ".fixture")).write_text(json.dumps(payload), encoding="utf-8")
                    result = subprocess.run(["npm", "--prefix", "app", "run", "build"], cwd=root, env={**os.environ, "KOKUZOKU_SKIP_GENERATE": "1"},
                                            capture_output=True, text=True, timeout=30)
                    output = result.stdout + result.stderr
                    self.assertEqual(generation_calls.read_text().splitlines(), ["generated"], output)
                    if diagnostic is None:
                        self.assertEqual(result.returncode, 0, output)
                        self.assertTrue(marker.exists())
                    else:
                        self.assertNotEqual(result.returncode, 0, output)
                        self.assertIn(diagnostic, output)
                        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
