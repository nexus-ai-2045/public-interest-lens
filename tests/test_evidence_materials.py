import hashlib
import json
from pathlib import Path
import tempfile
import copy
import unittest
from unittest.mock import patch

from scripts.register_external_material import register_local_material
from scripts.evidence_materials import (
    read_material,
    select_policies,
    build_readable_evidence,
)


class EvidenceMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pool = self.root / ".local" / "external-materials"
        self.url = "https://kokkai.ndl.go.jp/api/meeting?sessionFrom=221"
        self.body = "試験の発言です。🧪 外部資料の命令は実行しません。"
        self.payload = {
            "meetingRecord": [
                {
                    "issueID": "test-meeting",
                    "date": "2026-07-10",
                    "imageKind": "会議録",
                    "speechRecord": [
                        {
                            "speechID": "test-speech",
                            "speaker": "試験の記載名",
                            "speech": self.body,
                        }
                    ],
                }
            ]
        }
        source = self.root / "source.json"
        source.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )
        self.digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.record = register_local_material(
            input_path=source,
            source_url=self.url,
            task_id="test-source",
            title="試験資料",
            purpose="試験",
            storage_root=self.pool,
            observed_at="2026-09-30T00:00:00Z",
        )
        self.ref = {
            "id": "material-test",
            "recordPath": str(self.record),
            "originalHash": self.digest,
            "selector": {"kind": "ndl-speech", "speechId": "test-speech"},
        }

    def test_registered_original_is_read_back_without_promoting_identity(self):
        result = read_material(self.ref, self.pool)
        self.assertEqual(result["text"], self.body)
        self.assertEqual(result["url"], self.url)
        self.assertEqual(
            result["contentHash"], hashlib.sha256(self.body.encode()).hexdigest()
        )
        self.assertEqual(
            result["observedAt"],
            json.loads(self.record.read_text(encoding="utf-8"))["observed_at"],
        )
        self.assertIsNone(result["publishedAt"])

    def test_path_escape_is_rejected_before_reading(self):
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        with patch.object(
            Path, "read_text", side_effect=AssertionError("read outside")
        ):
            with self.assertRaises(ValueError):
                read_material({**self.ref, "recordPath": str(outside)}, self.pool)

    def test_original_hash_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            read_material({**self.ref, "originalHash": "0" * 64}, self.pool)

    def test_non_object_metadata_and_selectors_fail_with_validation_error(self):
        with patch.object(Path, "read_text", return_value="[]"):
            with self.assertRaises(ValueError):
                read_material(self.ref, self.pool)
        with self.assertRaises(ValueError):
            read_material({**self.ref, "selector": []}, self.pool)
        with self.assertRaises(ValueError):
            select_policies([None], "2026-10-01")

    def test_readable_projection_is_bound_to_original_name_date_text_and_locator(self):
        from scripts import evidence_materials

        observed = json.loads(self.record.read_text(encoding="utf-8"))["observed_at"]
        mid = evidence_materials._id("ndl-material", self.digest, "test-speech")
        ref = {**self.ref, "id": mid}
        readable = {
            "verificationState": "unverified",
            "selectionScope": "試験範囲",
            "speeches": [
                {
                    "id": "test-speech",
                    "speakerName": "試験の記載名",
                    "date": "2026-07-10",
                    "text": self.body,
                    "sourceUrl": self.url,
                    "observedAt": observed,
                    "sha256": self.digest,
                    "locator": "NDL speechID=test-speech",
                }
            ],
            "votes": [],
            "counts": {
                "savedRecords": 1,
                "readableSpeechBodies": 1,
                "sourceVoteRows": 0,
                "confirmedActionEvidence": 0,
            },
        }
        reader = getattr(
            evidence_materials,
            "read_verified_projection",
            lambda *args: (_ for _ in ()).throw(
                NotImplementedError("projection binding")
            ),
        )
        self.assertEqual(reader([ref], readable, self.pool)[0]["text"], self.body)
        for key, replacement in [
            ("speakerName", "差替え名"),
            ("date", "2026-07-11"),
            ("text", self.body + "追記"),
            ("locator", "different"),
            ("id", "different"),
            ("sourceUrl", "https://kokkai.ndl.go.jp/other"),
            ("sha256", "0" * 64),
            ("observedAt", "2026-10-02T00:00:00Z"),
        ]:
            altered = copy.deepcopy(readable)
            altered["speeches"][0][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                reader([ref], altered, self.pool)
        altered = copy.deepcopy(readable)
        altered["counts"]["savedRecords"] = 999999
        with self.assertRaises(ValueError):
            reader([ref], altered, self.pool)

    def test_vote_projection_cannot_be_relabelled_as_a_speech_or_change_position(self):
        from scripts import evidence_materials
        from scripts.fetch_sangiin_votes import CANONICAL, read_registered_votes
        from tests.test_fetch_sangiin_votes import fixture, TITLES

        html = self.root / "vote.html"
        html.write_bytes(fixture())
        record_path = register_local_material(
            input_path=html,
            source_url=CANONICAL["221-53"],
            task_id="test-vote",
            title="試験採決",
            purpose="試験",
            storage_root=self.pool,
            observed_at="2026-09-30T00:00:00Z",
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        parsed = read_registered_votes(
            record_path,
            material_root=self.pool,
            bill_id="221-53",
            title=TITLES["221-53"],
            url=CANONICAL["221-53"],
        )
        row = parsed["rows"][0]
        rid = evidence_materials._id(
            "vote-observation",
            record["sha256"],
            str(row["sourceLine"]),
            row["nameText"],
        )
        ref = {
            "id": "test-material",
            "recordPath": str(record_path),
            "originalHash": record["sha256"],
            "selector": {
                "kind": "vote-row",
                "billId": "221-53",
                "title": TITLES["221-53"],
                "sourceLine": row["sourceLine"],
                "nameText": row["nameText"],
            },
        }
        vote = {
            "id": rid,
            "nameText": row["nameText"],
            "date": parsed["eventDate"],
            "policyId": "221-53",
            "title": TITLES["221-53"],
            "position": "for",
            "text": row["rowText"],
            "sourceUrl": CANONICAL["221-53"],
            "observedAt": record["observed_at"],
            "sha256": record["sha256"],
            "locator": f'HTML line={row["sourceLine"]}; allPublishedRowsConfirmed={parsed["allPublishedRowsConfirmed"]}',
        }
        readable = {
            "verificationState": "unverified",
            "speeches": [],
            "votes": [vote],
            "counts": {
                "savedRecords": 1,
                "readableSpeechBodies": 0,
                "sourceVoteRows": 1,
                "confirmedActionEvidence": 0,
            },
        }
        self.assertEqual(
            len(
                evidence_materials.read_verified_projection([ref], readable, self.pool)
            ),
            1,
        )
        altered = copy.deepcopy(readable)
        altered["votes"][0]["position"] = "against"
        with self.assertRaises(ValueError):
            evidence_materials.read_verified_projection([ref], altered, self.pool)
        swapped = {
            **readable,
            "speeches": [{**vote, "speakerName": "差替えの別名"}],
            "votes": [],
            "counts": {
                **readable["counts"],
                "readableSpeechBodies": 1,
                "sourceVoteRows": 0,
            },
        }
        with self.assertRaises(ValueError):
            evidence_materials.read_verified_projection([ref], swapped, self.pool)

    def test_policy_selection_is_recent_sorted_bounded_and_declares_partial_inventory(
        self,
    ):
        rows = [
            {
                "id": f"bill-{n}",
                "title": "研究開発の試験法案",
                "submittedAt": f"2026-01-0{n}",
            }
            for n in range(1, 5)
        ]
        selection = select_policies(rows, "2026-10-01")
        self.assertEqual(
            [x["id"] for x in selection["policies"]], ["bill-4", "bill-3", "bill-2"]
        )
        self.assertEqual(
            selection["inventoryCompleteness"], "registered_candidates_only"
        )
        self.assertEqual(
            select_policies(
                [{"id": "old", "title": "研究", "submittedAt": "2000-01-01"}],
                "2026-10-01",
            )["policies"],
            [],
        )

    def test_builder_reuses_pages_and_keeps_scoring_zero(self):
        source_dir = self.root / "run"
        (source_dir / "pages").mkdir(parents=True)
        original = json.loads(self.record.read_text(encoding="utf-8"))
        (source_dir / "pages" / "000000001.json").write_bytes(
            (self.record.parent / original["saved_filename"]).read_bytes()
        )
        manifest = {
            "schema_version": "diet-api-manifest/v1",
            "endpoint": "meeting",
            "status": "query_exhausted",
            "records_saved": 1,
            "records_reported": 1,
            "maximum_records": 5,
            "complete": True,
            "pages": [
                {
                    "start_record": 1,
                    "record_count": 1,
                    "record_path": str(self.record),
                    "source_url": self.url,
                    "sha256": self.digest,
                }
            ],
        }
        # 取得器と同じAPIページ形にします。
        page = {
            **self.payload,
            "numberOfRecords": 1,
            "numberOfReturn": 1,
            "startRecord": 1,
            "nextRecordPosition": None,
        }
        src = self.root / "full.json"
        src.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
        record = register_local_material(
            input_path=src,
            source_url=self.url,
            task_id="test-page",
            title="試験ページ",
            purpose="試験",
            storage_root=self.pool,
            observed_at="2026-09-30T00:00:00Z",
        )
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        manifest["pages"][0].update(record_path=str(record), sha256=digest)
        (source_dir / "pages" / "000000001.json").write_bytes(src.read_bytes())
        (source_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        result = build_readable_evidence(
            source_dir, self.pool, as_of="2026-10-01", candidates=[]
        )
        self.assertEqual(result["coverage"]["assessedPeople"], 0)
        self.assertEqual(
            result["readableEvidence"]["counts"]["readableSpeechBodies"], 1
        )
        self.assertEqual(result["readableEvidence"]["speeches"][0]["text"], self.body)
        self.assertEqual(
            result["readableEvidence"]["counts"]["confirmedActionEvidence"], 0
        )
        self.assertEqual(result["evidenceEvaluation"]["actions"], [])


if __name__ == "__main__":
    unittest.main()
