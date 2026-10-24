"""全議員の表の配り先の照合（scripts/check_reference_members.py）。"""
import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_reference_members as crm  # noqa: E402


def _rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@unittest.skipUnless(shutil.which("node") and (ROOT / "app" / "node_modules" / "vite").exists(), "node か app の依存が無い")
class CheckReferenceMembersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.attributions = Path(cls.tmp.name) / "attributions.csv"
        crm.build_attributions(cls.attributions)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_committed_reference_matches_sources(self):
        self.assertEqual(crm.check(self.attributions), [])

    def test_every_attribution_is_checked_not_only_top(self):
        rows = _rows(self.attributions)
        # 合計に入るが top に出ない小さい配り先を、別人に差し替える。
        reference = crm.json.loads(crm.REFERENCE.read_text(encoding="utf-8"))
        tops = {(m["id"], t["lawId"], t["role"]) for m in reference["members"] for t in m["top"]}
        for role in ("proposer", "vote"):
            r = next(r for r in rows if r["role"] == role and (r["member"], r["lawId"], r["role"]) not in tops)
            r["name"] = "存在しない議員"
        bad = Path(self.tmp.name) / "bad.csv"
        _write(bad, rows)
        errors = crm.check(bad)
        self.assertTrue(any("提出" in e for e in errors))
        self.assertTrue(any("賛成" in e for e in errors))

    def test_totals_must_match_published(self):
        rows = _rows(self.attributions)
        rows = [r for r in rows if r["member"] != rows[0]["member"] or r["lawId"] != rows[0]["lawId"]]
        bad = Path(self.tmp.name) / "bad_totals.csv"
        _write(bad, rows)
        self.assertTrue(any("合計が公開ファイルと合わない" in e or "配り先が無い" in e for e in crm.check(bad)))


    def test_person_id_must_match_source_name(self):
        rows = _rows(self.attributions)
        other = next(r["member"] for r in rows if r["member"] != rows[0]["member"] and crm.canonical(r["name"]) != crm.canonical(rows[0]["name"]))
        rows[0]["member"] = other  # 出典の氏名と無関係な、台帳にある別人のID
        bad = Path(self.tmp.name) / "bad_person.csv"
        _write(bad, rows)
        self.assertTrue(any("人物IDの氏名が出典の氏名と合わない" in e for e in crm.check(bad)))

if __name__ == "__main__":
    unittest.main()
