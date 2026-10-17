"""実runnerを隔離したfixtureで動かし、版保存と欠落・保留の伝播を検査する。"""
import csv
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("impact", "loss", "benefit", "publish")


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path, data):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(data)


class VersionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "app").mkdir()
        for folder in ("src", "scripts"):
            shutil.copytree(ROOT / "app" / folder, self.root / "app" / folder)
        shutil.copyfile(ROOT / "app/package.json", self.root / "app/package.json")
        (self.root / "data").mkdir()
        (self.root / "data/acquired").symlink_to(ROOT / "data/acquired", target_is_directory=True)
        shutil.copytree(ROOT / "data/derived", self.root / "data/derived")

    def run_stage(self, stage, version):
        result = subprocess.run(["node", f"scripts/run-{stage}-v1.mjs", "--triage", version],
                                cwd=self.root / "app", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def snapshot(self, version):
        dirs = [f"{s}-v1" + ("-triage-v2" if version == "v2" else "") for s in STAGES]
        dirs.append(f"bill-triage-{version}")
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for d in dirs
                for p in (self.root / "data/derived" / d).glob("*.csv")}

    def test_v1_v2_v1_preserves_other_edition_even_between_stages(self):
        for stage in ("impact", "loss", "benefit"):
            self.run_stage(stage, "v1")
        v1 = self.snapshot("v1")
        for stage in ("impact", "loss", "benefit"):
            self.run_stage(stage, "v2")
            self.assertEqual(self.snapshot("v1"), v1, stage)
        v2 = self.snapshot("v2")
        self.assertTrue(any("impact-v1-triage-v2" in p for p in v2))
        for stage in ("impact", "loss", "benefit"):
            self.run_stage(stage, "v1")
            self.assertEqual(self.snapshot("v2"), v2, stage)
        self.assertEqual(self.snapshot("v1"), v1)

    def test_partial_v2_run_never_falls_back_to_v1(self):
        v1 = self.snapshot("v1")
        target = self.root / "data/derived/impact-v1-triage-v2"
        if target.exists():
            shutil.rmtree(target)
        for stage in ("loss", "benefit"):
            result = subprocess.run(["node", f"scripts/run-{stage}-v1.mjs", "--triage", "v2"],
                                    cwd=self.root / "app", capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("impact-v1-triage-v2/impact.csv", result.stderr)
            self.assertEqual(self.snapshot("v1"), v1)

    def test_missing_and_held_rows_survive_as_non_publishable(self):
        base = self.root / "data/derived"
        l1path, l2path = (base / "bill-triage-v2" / f"labels-line{n}.csv" for n in (1, 2))
        l1, l2 = rows(l1path), rows(l2path)
        ids = [r["id"] for r in l1[:5]]
        l1 = [r for r in l1 if r["id"] not in (ids[0], ids[4])]
        for r in l1:
            if r["id"] in ids[1:]:
                r.update({"結果": "保留", "分野": "", "指標": ""})
        for r in l2:
            if r["id"] == ids[0]:
                r.update({"系統2_判定": "評価対象", "系統2_分野": "金融", "系統2_指標": "貸出残高"})
            if r["id"] == ids[1]:
                r.update({"系統2_判定": "保留", "系統2_分野": "", "系統2_指標": ""})
            if r["id"] == ids[2]:
                r.update({"系統2_判定": "評価対象外", "系統2_分野": "対応表なし", "系統2_指標": ""})
        l2 = [r for r in l2 if r["id"] not in (ids[3], ids[4])]
        write_rows(l1path, l1)
        write_rows(l2path, l2)
        self.run_stage("impact", "v2")
        impact = {r["id"]: r for r in rows(base / "impact-v1-triage-v2/impact.csv")}
        ag = {r["id"]: r for r in rows(base / "bill-triage-v2/agreement.csv")}
        self.assertIn("参考：系統2の分野・指標", impact[ids[0]]["理由"])
        self.assertIn("参考計算なし：両系統の分野・指標が無い", impact[ids[4]]["理由"])
        for id_ in ids:
            self.assertIn(id_, impact)
            self.assertTrue(impact[id_]["判定"].startswith("保留"))
            self.assertEqual(impact[id_]["向き"], "")
            self.assertEqual(ag[id_]["結果"], "保留")
        self.run_stage("loss", "v2")
        self.run_stage("benefit", "v2")
        self.assertFalse(set(ids) & {r["id"] for r in rows(base / "loss-v1-triage-v2/loss.csv")})
        self.assertFalse(set(ids) & {r["id"] for r in rows(base / "publish-v1-triage-v2/publish.csv")})
