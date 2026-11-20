"""読みの取得（scripts/fetch_person_readings.py）が、会議録 API の応答の原本を外部資料として登録すること（AGENTS.md）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import fetch_person_readings as fpr


def speech(name: str, yomi: str) -> dict:
    return {"speaker": name, "speakerYomi": yomi}


class KeepsApiResponsesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.storage = root / "external-materials"
        patcher = mock.patch.object(fpr, "WORK", root / "work")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def fake_get(self, pages: dict[str, dict]):
        seen: list[str] = []

        def get(url: str) -> bytes:
            seen.append(url)
            for key, body in pages.items():
                if key in url:
                    return json.dumps(body, ensure_ascii=False).encode("utf-8")
            return json.dumps({"numberOfRecords": 0}).encode("utf-8")

        return get, seen

    def look_up(self, get) -> dict[str, str]:
        real = fpr.call_kept
        with mock.patch.object(fpr, "call_kept", lambda params, materials: real(params, materials, get=get, storage=self.storage)):
            return fpr.look_up("国会太郎", "国会太郎", [], 0)

    def test_each_response_is_registered_and_listed_in_the_row(self) -> None:
        get, seen = self.fake_get({"startRecord=1&": {"numberOfRecords": 1, "speechRecord": [speech("国会太郎", "こっかいたろう")]}})
        row = self.look_up(get)
        self.assertEqual(row["読み"], "こっかいたろう")
        ids = row["外部資料ID"].split()
        self.assertEqual(len(ids), len(seen))
        self.assertTrue(ids)
        for material_id in ids:
            record = json.loads((self.storage / fpr.TASK_ID / material_id / "record.json").read_text(encoding="utf-8"))
            self.assertIn(record["source_url"], seen)
            self.assertEqual(record["task_id"], fpr.TASK_ID)

    def test_responses_without_a_match_are_also_registered(self) -> None:
        get, seen = self.fake_get({})
        row = self.look_up(get)
        self.assertEqual(row["読み"], "")
        self.assertEqual(len(row["外部資料ID"].split()), len(set(seen)))

    def test_output_columns_include_material_id(self) -> None:
        self.assertIn("外部資料ID", fpr.FIELDS)


if __name__ == "__main__":
    unittest.main()
