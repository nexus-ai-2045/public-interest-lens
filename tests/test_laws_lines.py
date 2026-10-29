"""laws.json は法律・政策を1本1行に並べる。1本変わっても差分がその行だけになり、名義検査の上限に当たらないこと。"""

import json
import unittest
from pathlib import Path

from scripts import build_laws_catalog as catalog

LAWS = Path(__file__).resolve().parents[1] / "app" / "public" / "distribution" / "laws.json"
# repo-preflight の identity_gate が 1 コミットで足せる行の文字数の上限（MAX_ADDED_CHARS）。
ADDED_CHARS_LIMIT = 4_000_000


def _sample(count: int) -> dict:
    return {
        "schema": "public-laws/v1",
        "counts": {"laws": count},
        "laws": [{"id": f"閣法-{i}", "title": "テスト法" * 5, "amount": {"low": 1, "high": 2}, "certainty": "参考"} for i in range(count)],
        "policies": [],
    }


class LawsOnePerLineTest(unittest.TestCase):
    def test_same_content_as_compact_json(self):
        payload = _sample(5)
        self.assertEqual(json.loads(catalog.dump_one_per_line(payload)), payload)

    def test_one_law_per_line(self):
        text = catalog.dump_one_per_line(_sample(7))
        lines = [line for line in text.split("\n") if line.startswith('{"id"')]
        self.assertEqual(len(lines), 7)

    def test_changing_one_law_changes_one_line(self):
        before = catalog.dump_one_per_line(_sample(1000)).split("\n")
        payload = _sample(1000)
        payload["laws"][500]["certainty"] = "高"
        after = catalog.dump_one_per_line(payload).split("\n")
        self.assertEqual(len(before), len(after))
        self.assertEqual(sum(a != b for a, b in zip(before, after)), 1)

    def test_even_with_many_laws_a_full_rewrite_stays_under_the_limit(self):
        # 法律が今の3,415本の4倍に増えても、全部書き換わる最悪の差分が上限の半分に収まる。
        text = catalog.dump_one_per_line(_sample(3415 * 4))
        self.assertLess(len(text), ADDED_CHARS_LIMIT // 2)

    def test_committed_file_is_one_per_line(self):
        text = LAWS.read_text(encoding="utf-8")
        data = json.loads(text)
        lines = text.split("\n")
        self.assertGreaterEqual(len(lines), len(data["laws"]))
        self.assertLess(max(len(line) for line in lines), 20_000)
        self.assertEqual(text, catalog.dump_one_per_line(data))

    def test_detail_files_are_one_law_per_line_when_converted(self):
        # laws-detail/ は数回に分けて1本1行へ移している（1回で足す行が上限を超えるため）。
        # 移した束は、1本1行で、どの行も大きくならない。まだ移していない束は1行のまま。
        converted = 0
        for path in sorted((LAWS.parent / "laws-detail").glob("*.json")):
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            lines = text.split("\n")
            if len(lines) > 3:
                converted += 1
                self.assertGreaterEqual(len(lines), len(data["items"]), path.name)
                self.assertLess(max(len(line) for line in lines), 60_000, path.name)
                self.assertEqual(text, catalog.dump_bundle_one_per_line(data), path.name)
        self.assertGreater(converted, 0)

    def test_bundle_writer_keeps_content(self):
        bundle = {"schema": "public-laws-detail/v1", "items": {"閣法-1-1": {"a": 1}, "閣法-1-2": {"a": 2}}}
        text = catalog.dump_bundle_one_per_line(bundle)
        self.assertEqual(json.loads(text), bundle)
        self.assertEqual(len(text.strip().split("\n")), 5)

    def test_members_reference_is_one_member_per_line(self):
        path = LAWS.parent / "members-reference.json"
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        lines = text.split("\n")
        self.assertGreaterEqual(len(lines), len(data["members"]))
        self.assertLess(max(len(line) for line in lines), 20_000)


if __name__ == "__main__":
    unittest.main()
