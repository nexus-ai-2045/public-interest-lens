import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "public" / "distribution" / "unenacted.json"


class PublicUnenactedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess, sys
        subprocess.run([sys.executable, "scripts/build_public_unenacted.py"], cwd=ROOT, check=True, capture_output=True)
        cls.data = json.loads(OUT.read_text(encoding="utf-8"))

    def test_only_scored_bills_without_amount_or_direction(self):
        self.assertEqual(self.data["schema"], "public-unenacted/v1")
        self.assertEqual(self.data["counts"]["scored"], len(self.data["bills"]))
        for b in self.data["bills"]:
            self.assertGreaterEqual(b["scale"], 0)
            self.assertEqual(b["certainty"], "参考")
            self.assertNotIn("amount", b)
            self.assertNotIn("direction", b)

    def test_sorted_by_scale_desc(self):
        scales = [b["scale"] for b in self.data["bills"]]
        self.assertEqual(scales, sorted(scales, reverse=True))


if __name__ == "__main__":
    unittest.main()
