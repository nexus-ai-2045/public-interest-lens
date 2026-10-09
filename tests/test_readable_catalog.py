import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts.build_readable_catalog import build_catalog


class ReadableCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.release = self.root / "release.json"
        self.metadata = self.root / "metadata.json"
        self.output = self.root / "output"
        self.candidates = []
        for index in (1, 2):
            directory = self.root / str(index)
            directory.mkdir()
            original = directory / "original.html"
            original.write_bytes((f'<html><meta charset="UTF-8"><table>'
                                  f'<tr><th>件名</th><td>政策{index}</td></tr>'
                                  f'<tr><th>提出回次</th><td>221回</td></tr>'
                                  f'<tr><th>提出番号</th><td>{index}</td></tr>'
                                  '<tr><th>提出日</th><td>令和8年3月1日</td></tr></table>'
                                  '<nav>非公開ナビ</nav><table summary="議案要旨情報">'
                                  '<tr><th>議案要旨</th></tr><tr><td>'
                                  '<script>危険なscript</script><style>危険なstyle</style>'
                                  '<nav>危険なnav</nav>'
                                  f'原文要旨{index}。事業の認定制度を創設する。'
                                  '</td></tr></table></html>').encode())
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            url = ("https://www.sangiin.go.jp/japanese/joho1/kousei/gian/221/meisai/"
                   f"m22108022100{index}.htm")
            record = directory / "record.json"
            record.write_text(json.dumps({
                "schema_version": "external-material/v1",
                "saved_filename": original.name, "sha256": digest,
                "source_url": url, "bytes": original.stat().st_size,
            }), encoding="utf-8")
            self.candidates.append({
                "policyId": f"221-{index}", "formalTitle": f"政策{index}",
                "summary": f"要約{index}", "officialUrl": url,
                "originalSha256": digest, "recordPath": str(record),
                "rawText": "非公開本文",
            })
        self.write_metadata()
        release = {
            "schemaVersion": "evidence-release/v1", "engineHash": "c" * 64,
            "publicationStatus": "requires_human_review",
            "input": {"evidenceEvaluation": {
                "mode": "real", "assessments": [],
                "options": {"weights": {"economy": 1, "technology": 1}},
                "people": [{"id": "person-1", "name": "試験人物"}],
                "actions": [{
                    "actionId": f"action-{index}", "personId": "person-1",
                    "policyId": f"221-{index}", "actionDate": "2026-10-01",
                    "description": "試験行動", "position": "for",
                    "quotes": [{"materialId": "material-1", "text": "試験引用", "start": 0, "end": 4}],
                } for index in (1, 2)],
                "materials": [{"id": "material-1", "url": "https://www.sangiin.go.jp/vote",
                               "originalHash": "a" * 64, "contentHash": "b" * 64}],
            }},
            "result": {"mode": "real", "rows": [], "held": [],
                       "coverage": {"inputActions": 2, "assessedActions": 0, "readableMaterials": 1}},
        }
        self.write_release(release)

    def write_release(self, release):
        release.pop("releaseId", None)
        release["releaseId"] = hashlib.sha256(json.dumps(
            release, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        self.release.write_text(json.dumps(release), encoding="utf-8")

    def read_context(self):
        manifest = json.loads((self.output / "current.json").read_text(encoding="utf-8"))
        return json.loads((self.output / manifest["contextPath"]).read_text(encoding="utf-8"))

    def write_metadata(self):
        self.metadata.write_text(json.dumps({"metadataCandidates": self.candidates}),
                                 encoding="utf-8")

    def test_build_sanitized_context_and_relation_query(self):
        result = build_catalog(self.release, self.metadata, self.output)
        context = self.read_context()
        self.assertEqual(set(context), {"schemaVersion", "releaseId", "policies"})
        self.assertEqual(context["schemaVersion"], "policy-context/v1")
        self.assertEqual(context["releaseId"], json.loads(self.release.read_text())["releaseId"])
        self.assertEqual(len(context["policies"]), 2)
        self.assertEqual(set(context["policies"][0]), {
            "policyId", "formalTitle", "summary", "officialUrl", "originalSha256",
            "summaryStatus", "sourceExcerpt",
        })
        self.assertEqual(context["policies"][0]["sourceExcerpt"],
                         "原文要旨1。事業の認定制度を創設する。")
        self.assertEqual(context["policies"][0]["summaryStatus"], "unverified_explanation")
        with closing(sqlite3.connect(result["databasePath"])) as connection:
            rows = connection.execute(
                "SELECT p.formalTitle, pe.name, a.position FROM actions a "
                "JOIN policies p USING (policyId) JOIN people pe USING (personId) "
                "JOIN releases r USING (releaseId) ORDER BY p.policyId"
            ).fetchall()
            self.assertEqual(rows, [("政策1", "試験人物", "for"),
                                    ("政策2", "試験人物", "for")])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT count(*) FROM action_sources").fetchone()[0], 2)

    def test_repeated_build_has_no_duplicates(self):
        build_catalog(self.release, self.metadata, self.output)
        before = (self.output / "current.json").read_bytes()
        result = build_catalog(self.release, self.metadata, self.output)
        self.assertEqual(before, (self.output / "current.json").read_bytes())
        with closing(sqlite3.connect(result["databasePath"])) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM actions").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT count(*) FROM releases").fetchone()[0], 1)

    def test_wrong_hash_preserves_both_good_outputs(self):
        result = build_catalog(self.release, self.metadata, self.output)
        paths = [self.output / "current.json", Path(result["databasePath"]), Path(result["contextPath"])]
        before = {path: path.read_bytes() for path in paths}
        self.candidates[0]["originalSha256"] = "0" * 64
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "hash"):
            build_catalog(self.release, self.metadata, self.output)
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes())

    def test_tampered_original_fails_before_creating_outputs(self):
        (self.root / "1" / "original.html").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash"):
            build_catalog(self.release, self.metadata, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_policy_or_unknown_person_fails_closed(self):
        release = json.loads(self.release.read_text(encoding="utf-8"))
        release["input"]["evidenceEvaluation"]["actions"][0]["personId"] = "unknown"
        self.write_release(release)
        with self.assertRaises(ValueError):
            build_catalog(self.release, self.metadata, self.output)
        self.assertFalse(self.output.exists())

    def test_forged_release_body_preserves_current(self):
        build_catalog(self.release, self.metadata, self.output)
        before = (self.output / "current.json").read_bytes()
        release = json.loads(self.release.read_text())
        release["input"]["evidenceEvaluation"]["people"][0]["name"] = "改竄人物"
        self.release.write_text(json.dumps(release), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "release"):
            build_catalog(self.release, self.metadata, self.output)
        self.assertEqual(before, (self.output / "current.json").read_bytes())

    def test_forged_formal_title_or_policy_identifier_fails(self):
        self.candidates[0]["formalTitle"] = "存在しない正式名"
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "title"):
            build_catalog(self.release, self.metadata, self.output)
        self.candidates[0]["formalTitle"] = "政策1"
        self.candidates[0]["policyId"] = "200-1"
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "identifier"):
            build_catalog(self.release, self.metadata, self.output)

    def test_manifest_replace_failure_retains_previous_generation(self):
        first = build_catalog(self.release, self.metadata, self.output)
        paths = [self.output / "current.json", Path(first["databasePath"]), Path(first["contextPath"])]
        before = {path: path.read_bytes() for path in paths}
        self.candidates[0]["summary"] = "別の説明候補"
        self.write_metadata()
        from scripts import build_readable_catalog as module
        original_replace = module.os.replace

        def fail_current(source, destination):
            if Path(destination).name == "current.json":
                raise OSError("injected manifest replace failure")
            return original_replace(source, destination)

        with patch.object(module.os, "replace", side_effect=fail_current):
            with self.assertRaisesRegex(OSError, "injected"):
                build_catalog(self.release, self.metadata, self.output)
        for path, content in before.items():
            self.assertEqual(content, path.read_bytes())

    def test_excerpt_bounds_and_missing_excerpt_not_disguised(self):
        for index, candidate in enumerate(self.candidates, 1):
            record_path = Path(candidate["recordPath"])
            original = record_path.parent / "original.html"
            source = original.read_text(encoding="utf-8")
            if index == 1:
                source = source.replace("原文要旨1。事業の認定制度を創設する。", "本文" * 4000)
            else:
                source = source.replace('summary="議案要旨情報"', 'summary="別の表"')
            original.write_bytes(source.encode("shift_jis"))
            payload = original.read_bytes().replace(b'charset="UTF-8"', b'charset="Shift_JIS"')
            original.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            record = json.loads(record_path.read_text())
            record.update(sha256=digest, bytes=len(payload))
            record_path.write_text(json.dumps(record), encoding="utf-8")
            candidate["originalSha256"] = digest
        self.write_metadata()
        build_catalog(self.release, self.metadata, self.output)
        context = self.read_context()
        self.assertEqual(len(context["policies"][0]["sourceExcerpt"]), 6000)
        self.assertNotIn("sourceExcerpt", context["policies"][1])


if __name__ == "__main__":
    unittest.main()
