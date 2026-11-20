"""公開サイトの各ページが読むデータが、同じ段階の派生データから作られていることを確かめる。

どれか1つだけ作り直して main に入ると、ページごとに数字が食い違う（/ranking と ranking.json）。
直し方は1つだけ：python3 scripts/rebuild_public.py を回し、出たファイルを全部コミットする。
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts import build_laws_catalog, build_public_ranking

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "app" / "public" / "distribution"
FIX = "python3 scripts/rebuild_public.py を回して、出たファイルを全部コミットしてください"
from _data_gate import requires_data  # noqa: E402


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str) -> dict:
    return json.loads((DIST / name).read_text(encoding="utf-8"))


class PublicSyncTest(unittest.TestCase):
    def test_generated_rankings_bind_method_and_source_code(self):
        for label, value, entry in (("ranking.json", _load("ranking.json"), "scripts/build_public_ranking.py"),):
            meta = value["generatedFrom"]
            from scripts.generation_provenance import generation_metadata
            self.assertEqual(meta["methodSpecVersion"], generation_metadata([])["methodSpecVersion"])
            self.assertIn(entry, meta["codeHashes"])
            if label == "ranking.json":
                self.assertEqual({"methodSpecVersion": meta["methodSpecVersion"], "codeHashes": meta["codeHashes"]},
                                 generation_metadata(["scripts/build_public_ranking.py"]))
            for path, digest in meta["codeHashes"].items():
                self.assertFalse(Path(path).is_absolute())
                self.assertNotIn("..", Path(path).parts)
                self.assertEqual(digest, _digest(ROOT / path), label + ": " + path)

    def setUp(self) -> None:
        self.ranking = _load("ranking.json")
        self.laws = _load("laws.json")

    def assert_inputs(self, label: str, recorded: dict, paths: dict) -> None:
        self.assertEqual(set(recorded), set(paths), f"{label} の入力の組が変わった。{FIX}")
        stale = [name for name, path in paths.items() if recorded[name] != _digest(path)]
        self.assertEqual(stale, [], f"{label} が古い入力から作られている（{', '.join(stale)}）。{FIX}")

    def test_ranking_is_built_from_current_derived_data(self) -> None:
        recorded = self.ranking["generatedFrom"]["inputs"]
        paths = build_public_ranking.INPUTS
        self.assertEqual(set(recorded), set(paths))
        public = {k: p for k, p in paths.items() if k != "industryVa"}
        self.assert_inputs("ranking.json", {k: recorded[k] for k in public}, public)
        self.assertRegex(recorded["industryVa"], r"^[a-f0-9]{64}$")
        # 非公開入力を持つ検査段は既存のPublicRankingTestsが全再生成を比較する。
        # CIでも従来の公開8入力の照合は省略せず、skip許可一覧を増やさない。
        if paths["industryVa"].exists():
            self.assertEqual(recorded["industryVa"], _digest(paths["industryVa"]))

    @requires_data("industry_va", "speeches")
    def test_laws_catalog_is_built_from_current_ranking_and_members(self) -> None:
        self.assert_inputs("laws.json", self.laws["inputs"], build_laws_catalog.INPUTS)

    def test_law_names_match_the_catalog(self) -> None:
        # 議員ページが読む「何をする」の一文は、laws.json の行と同じ文。無い行は理由の印だけを持つ。
        names = _load("law-names.json")
        self.assertEqual(names["schema"], "public-law-names/v1")
        for law in self.laws["laws"]:
            if law.get("what"):
                self.assertEqual(names["what"].get(law["id"]), law["what"], law["id"])
                self.assertNotIn(law["id"], names["withheld"])
            else:
                self.assertIn(law.get("whatWithheld"), {"shared", "unread", "other", "unchecked", "none"}, law["id"])
                self.assertEqual(names["withheld"].get(law["id"]), law["whatWithheld"], law["id"])
        self.assertEqual(len(names["what"]) + len(names["withheld"]), len(self.laws["laws"]))

    def test_counts_agree_between_pages(self) -> None:
        r, c = self.ranking["counts"], self.laws["counts"]
        self.assertEqual(c["enacted"], r["enacted"])
        self.assertEqual(len(self.laws["laws"]), r["enacted"])
        self.assertEqual(c["amounted"], r["published"], "/ranking の額つきの本数が ranking.json と違う")
        self.assertEqual(c["published"], r["confirmed"], "/ranking の確かな額の本数が ranking.json と違う")
        amounted = [law for law in self.laws["laws"] if law["amount"]]
        self.assertEqual(len(amounted), r["published"])
        self.assertEqual(len(self.laws["laws"]) - len(amounted), r["others"])
        # 共有額の参考は「成立」で止まった扱いにしない（再査読 N3）。/ranking の注の「額が出ていない法律」は札の「額なし」とそろう
        shared = [law for law in self.laws["laws"] if law.get("shared")]
        self.assertEqual(len(shared), r["shared"])
        self.assertFalse([law["id"] for law in shared if law["step"] == "enacted"])

    def test_laws_catalog_has_no_member_allocation(self) -> None:
        """議員への配分は撤回した（設計決定0027）。一覧にも詳細にも、配った額・関わった議員の欄を持たない。"""
        for law in self.laws["laws"]:
            for key in ("attributed", "members", "membersTotal"):
                self.assertNotIn(key, law, law["id"])
        for path in sorted((DIST / "laws-detail").glob("*.json")):
            for law_id, item in json.loads(path.read_text(encoding="utf-8"))["items"].items():
                for key in ("attributed", "members", "membersTotal"):
                    self.assertNotIn(key, item, law_id)


if __name__ == "__main__":
    unittest.main()
