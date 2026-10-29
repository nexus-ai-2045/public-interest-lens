import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_evidence_ledger as c  # noqa: E402


def sample(**over):
    e = {
        "id": "x-1", "mechanism": "m", "quantity": "q",
        "estimate": {"central": 1.0, "low": 0.5, "high": 1.5, "unit": "倍", "interval_type": "範囲"},
        "source": {"authors": "A", "year": 2000, "title": "T", "venue": "V", "doi": "10.1000/abc", "url": "https://x", "study_type": "meta-analysis", "n_studies": 3},
        "scope": {"countries": "OECD", "period": "1990-2000", "population_or_sector": "全体"},
        "locator": "表1", "japan_application": {"method": "そのまま", "caveat": "なし"}, "used_for": ["財政"],
        "confidence": "中",
        "verification": {"status": "verified", "crossref_title_match": True, "crossref_author_match": True, "crossref_year_match": True, "checks": [
            {"role": "collector", "central": 1.0}, {"role": "check1", "central": 1.0, "low": 0.5, "high": 1.5, "unit": "倍", "scope_match": True},
            {"role": "check2", "central": 1.0, "low": 0.5, "high": 1.5, "unit": "倍", "scope_match": True}]},
    }
    e.update(over)
    return e


class LedgerCheck(unittest.TestCase):
    def test_good_entry_passes(self):
        self.assertEqual(c.check_entry(sample()), [])

    def test_verified_needs_three_agreeing(self):
        e = sample()
        e["verification"]["checks"][2]["central"] = 2.0
        self.assertTrue(any("一致しない" in x for x in c.check_entry(e)))
        e = copy.deepcopy(sample())
        e["verification"]["checks"].pop()
        self.assertTrue(any("3者" in x for x in c.check_entry(e)))

    def test_small_values_need_same_sign_and_scale(self):
        e = sample()
        e["estimate"].update(central=0.001, low=None, high=None)
        for chk, v in zip(e["verification"]["checks"], (0.001, -0.001, 0.004)):
            chk.update(central=v, low=None, high=None)
        self.assertTrue(any("一致しない" in x for x in c.check_entry(e)))

    def test_interval_unit_scope_must_match_ledger(self):
        e = sample()
        e["verification"]["checks"][1].update(low=-100, high=100)
        self.assertTrue(any("区間" in x for x in c.check_entry(e)))
        e = sample()
        e["verification"]["checks"][2]["unit"] = "円"
        self.assertTrue(any("単位" in x for x in c.check_entry(e)))
        e = sample()
        e["verification"]["checks"][1]["scope_match"] = False
        self.assertTrue(any("対象" in x for x in c.check_entry(e)))

    def test_empty_required_content_rejected(self):
        e = sample(scope={}, locator="", japan_application={})
        errs = c.check_entry(e)
        self.assertTrue(any("scope" in x for x in errs) and any("locator" in x for x in errs) and any("japan_application" in x for x in errs))
        e = sample()
        del e["source"]["authors"]
        self.assertTrue(any("source" in x for x in c.check_entry(e)))

    def test_non_finite_values_rejected(self):
        e = sample()
        e["verification"]["checks"][1]["central"] = float("inf")
        self.assertTrue(c.check_entry(e))
        e = sample()
        e["estimate"]["central"] = float("nan")
        self.assertTrue(any("central" in x for x in c.check_entry(e)))

    def test_doi_requires_crossref(self):
        e = sample()
        e["verification"]["crossref_title_match"] = None
        self.assertTrue(any("Crossref" in x for x in c.check_entry(e)))

    def test_doi_requires_crossref_author_and_year(self):
        for k in ("crossref_author_match", "crossref_year_match"):
            e = sample()
            e["verification"][k] = False
            self.assertTrue(any("Crossref" in x for x in c.check_entry(e)), k)

    def test_held_needs_reason(self):
        e = sample(verification={"status": "held"})
        self.assertTrue(any("held_reason" in x for x in c.check_entry(e)))

    def test_duplicate_and_mapping(self):
        led = {"entries": [sample(), sample()]}
        self.assertTrue(any("重複" in x for x in c.check(led)))
        led = {"entries": [sample()]}
        self.assertTrue(any("mapping" in x for x in c.check(led, {"mechanisms": [{"id": "m", "ledger_ids": ["nope"]}]})))

    def test_committed_ledger_is_green(self):
        if not c.LEDGER.exists():
            self.skipTest("ledger なし")
        mapping = json.loads(c.MAPPING.read_text(encoding="utf-8")) if c.MAPPING.exists() else None
        self.assertEqual(c.check(json.loads(c.LEDGER.read_text(encoding="utf-8")), mapping), [])


if __name__ == "__main__":
    unittest.main()
