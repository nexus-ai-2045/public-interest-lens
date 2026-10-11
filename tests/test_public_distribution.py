import json
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.build_public_distribution import build_public_distribution, read_edition, select_years


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data" / "distribution" / "case-source.json"
WORLD_BANK = ROOT / "data" / "distribution" / "sources" / "world-bank"


class PublicDistributionTests(unittest.TestCase):
    def _build(self, folder: Path, case: Path = CASE, source: Path = WORLD_BANK):
        return build_public_distribution(source, case, folder / "out")

    def test_interrupted_database_build_recovers_before_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("scripts.build_public_distribution._write_database", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    self._build(root)
            self.assertFalse((root / "out" / "current.json").exists())
            manifest = self._build(root)
            database_path = root / "out" / manifest["databasePath"]
            self.assertTrue(database_path.is_file())
            database = sqlite3.connect(database_path)
            try:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(database.execute("SELECT releaseId FROM distribution_releases").fetchone(), (manifest["snapshotId"],))
            finally:
                database.close()

    def test_corrupt_database_stops_without_replacing_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self._build(root)
            current_path = root / "out" / "current.json"
            current = current_path.read_bytes()
            (root / "out" / manifest["databasePath"]).write_bytes(b"corrupt fixture")
            with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                self._build(root)
            self.assertEqual(current_path.read_bytes(), current)

    def test_interrupted_new_release_preserves_previous_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._build(root)
            current_path = root / "out" / "current.json"
            current = current_path.read_bytes()
            case = json.loads(CASE.read_text(encoding="utf-8"))
            case["holdReason"] += "訂正後も未確定です。"
            case_path = root / "corrected.json"
            case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            with patch("scripts.build_public_distribution._write_database", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    self._build(root, case=case_path)
            self.assertEqual(current_path.read_bytes(), current)
            manifest = self._build(root, case=case_path)
            self.assertTrue((root / "out" / manifest["databasePath"]).is_file())

    def test_immutable_json_mismatch_still_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self._build(root)
            path = root / "out" / manifest["economyPath"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["note"] = "異なる内容"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "一致しません"):
                self._build(root)

    def test_database_row_deletion_stops_without_replacing_current(self):
        self._assert_database_row_change_rejected("DELETE FROM statistic_points")

    def test_database_numeric_change_stops_without_replacing_current(self):
        self._assert_database_row_change_rejected("UPDATE statistic_points SET value = value + 1 WHERE value IS NOT NULL")

    def test_database_extra_row_stops_without_replacing_current(self):
        self._assert_database_row_change_rejected("INSERT INTO statistic_points SELECT releaseId, seriesId, 1800, 1 FROM statistic_series LIMIT 1")

    def _assert_database_row_change_rejected(self, statement):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self._build(root)
            current_path = root / "out" / "current.json"
            current = current_path.read_bytes()
            database_path = root / "out" / manifest["databasePath"]
            database = sqlite3.connect(database_path)
            try:
                database.execute(statement)
                database.commit()
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                database.close()
            modified_database = database_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "内容が一致しません"):
                self._build(root)
            self.assertEqual(current_path.read_bytes(), current)
            self.assertEqual(database_path.read_bytes(), modified_database)

    def test_periods_keep_gaps_and_do_not_zero_fill(self):
        points = [{"year": 2021, "value": 3}, {"year": 2023, "value": None}, {"year": 2025, "value": 4}]
        selected = select_years(points, 4)
        self.assertEqual([item["year"] for item in selected], [2022, 2023, 2024, 2025])
        self.assertEqual([item["value"] for item in selected], [None, None, None, 4])
        self.assertNotIn(0, [item["value"] for item in selected])
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "out"
            self._build(Path(folder))
            economy = json.loads(next((out / "generations").glob("*/economy.json")).read_text(encoding="utf-8"))
            real = next(series for series in economy["series"] if series["id"] == "real_gdp")
            self.assertEqual(len(select_years(real["points"], 40)), 40)
            self.assertEqual(select_years(real["points"], 30)[0]["year"], real["points"][-1]["year"] - 29)
            self.assertEqual(len(select_years(real["points"], 4)), 4)

    def test_case_is_held_and_links_people_without_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = self._build(Path(folder))
            self.assertEqual(manifest["personScores"], 0)
            self.assertEqual(manifest["scoringStatus"], "held")
            out = Path(folder) / "out"
            published = json.loads((out / manifest["casePath"]).read_text(encoding="utf-8"))
            self.assertIsNone(published["impactScale"])
            self.assertIsNone(published["gdpLoss"])
            self.assertIsNone(published["responsibilityShare"])
            self.assertGreaterEqual(len({actor["label"] for actor in published["actors"]}), 3)
            database = sqlite3.connect(out / manifest["databasePath"])
            try:
                self.assertEqual(database.execute("SELECT COUNT(*), SUM(score) FROM actor_actions").fetchone(), (5, None))
                self.assertEqual(database.execute("SELECT relationKind FROM series_case_links").fetchone()[0], "temporal_overlap_not_attribution")
                self.assertEqual(database.execute("SELECT COUNT(*) FROM cause_candidates WHERE status != 'unestablished'").fetchone()[0], 0)
                self.assertIsNone(database.execute("SELECT impactScale FROM policy_cases").fetchone()[0])
            finally:
                database.close()
            schema = sqlite3.connect(":memory:")
            generated = sqlite3.connect(out / manifest["databasePath"])
            try:
                schema.executescript((ROOT / "data" / "distribution-schema.sql").read_text(encoding="utf-8"))
                tables = sorted(row[0] for row in generated.execute("SELECT name FROM sqlite_master WHERE type='table'"))
                self.assertEqual(tables, sorted(row[0] for row in schema.execute("SELECT name FROM sqlite_master WHERE type='table'")))
                for table in tables:
                    self.assertEqual(generated.execute(f"PRAGMA table_info({table})").fetchall(), schema.execute(f"PRAGMA table_info({table})").fetchall())
            finally:
                schema.close()
                generated.close()

    def test_unknown_edition_stops_without_reading_current(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = self._build(Path(folder))
            out = Path(folder) / "out"
            self.assertEqual(read_edition(out, manifest["snapshotId"])["snapshotId"], manifest["snapshotId"])
            with self.assertRaises(ValueError):
                read_edition(out, "0" * 64)
            with self.assertRaises(ValueError):
                read_edition(out, "not-an-edition")

    def test_correction_keeps_previous_release_and_failed_rebuild_keeps_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self._build(root)
            old_economy = (root / "out" / first["economyPath"]).read_bytes()
            case = json.loads(CASE.read_text(encoding="utf-8"))
            case["holdReason"] = case["holdReason"] + "訂正後も影響規模は未確定です。"
            corrected = root / "case.json"
            corrected.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            second = build_public_distribution(WORLD_BANK, corrected, root / "out")
            self.assertNotEqual(first["snapshotId"], second["snapshotId"])
            self.assertEqual((root / "out" / first["economyPath"]).read_bytes(), old_economy)
            current = (root / "out" / "current.json").read_bytes()
            broken = json.loads(CASE.read_text(encoding="utf-8"))
            broken["actors"].append(broken["actors"][0])
            rejected = root / "broken.json"
            rejected.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_public_distribution(WORLD_BANK, rejected, root / "out")
            self.assertEqual((root / "out" / "current.json").read_bytes(), current)

    def test_missing_statistic_stays_null_and_checked_in_sources_match(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "wb"
            shutil.copytree(WORLD_BANK, source)
            payload = json.loads((source / "NY.GDP.MKTP.KN.json").read_text(encoding="utf-8"))
            payload[1][0]["value"] = None
            (source / "NY.GDP.MKTP.KN.json").write_text(json.dumps(payload), encoding="utf-8")
            manifest = build_public_distribution(source, CASE, Path(folder) / "out")
            economy = json.loads((Path(folder) / "out" / manifest["economyPath"]).read_text(encoding="utf-8"))
            real = next(series for series in economy["series"] if series["id"] == "real_gdp")
            self.assertIn(None, [point["value"] for point in real["points"]])
            self.assertNotIn(0, [point["value"] for point in real["points"] if point["value"] is None])
        self._assert_checked_in_distribution(ROOT)

    def _assert_checked_in_distribution(self, artifact_root):
        committed = json.loads((artifact_root / "data" / "distribution" / "generated" / "current.json").read_text(encoding="utf-8"))
        for key in ("economyPath", "casePath", "databasePath"):
            self.assertTrue((artifact_root / "data" / "distribution" / "generated" / committed[key]).is_file(), key)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(artifact_root / "data" / "distribution" / "generated", root / "out")
            rebuilt = build_public_distribution(WORLD_BANK, CASE, root / "out", root / "public")
            self.assertEqual(rebuilt, committed)
            for expected_path in sorted((root / "public").rglob("*.json")):
                relative = expected_path.relative_to(root / "public")
                shipped_path = artifact_root / "app" / "public" / "distribution" / relative
                self.assertEqual(json.loads(shipped_path.read_text(encoding="utf-8")), json.loads(expected_path.read_text(encoding="utf-8")), str(relative))

    def test_checked_in_artifact_corruption_is_detected_without_writes(self):
        committed = json.loads((ROOT / "data" / "distribution" / "generated" / "current.json").read_text(encoding="utf-8"))
        paths = [
            "data/distribution/generated/" + committed["databasePath"],
            "data/distribution/generated/" + committed["economyPath"],
            "data/distribution/generated/" + committed["casePath"],
            "app/public/distribution/economy.json",
            "app/public/distribution/case.json",
            f'app/public/distribution/releases/{committed["snapshotId"]}.json',
            f'app/public/distribution/cases/{committed["snapshotId"]}.json',
            "data/distribution/generated/current.json",
        ]
        for relative, change in ((path, change) for path in paths for change in ("modified", "missing")):
            with self.subTest(artifact=relative, change=change), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                shutil.copytree(ROOT / "data" / "distribution" / "generated", root / "data" / "distribution" / "generated")
                shutil.copytree(ROOT / "app" / "public" / "distribution", root / "app" / "public" / "distribution")
                target = root / relative
                if change == "missing":
                    target.unlink()
                elif target.suffix == ".sqlite3":
                    database = sqlite3.connect(target)
                    try:
                        database.execute("UPDATE statistic_points SET value = value + 1 WHERE value IS NOT NULL")
                        database.commit()
                    finally:
                        database.close()
                else:
                    payload = json.loads(target.read_text(encoding="utf-8"))
                    payload["unexpectedFixtureField"] = True
                    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
                with self.assertRaises((AssertionError, ValueError, sqlite3.DatabaseError, FileNotFoundError)):
                    self._assert_checked_in_distribution(root)
                self.assertEqual(before, {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
