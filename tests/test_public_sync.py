"""公開サイトの各ページが読むデータが、同じ段階の派生データから作られていることを確かめる。

どれか1つだけ作り直して main に入ると、ページごとに数字が食い違う（/ranking と /members と ranking.json）。
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
# scripts/build_public_members.mjs の inputs と同じ。
MEMBER_INPUTS = {
    "involvements": ROOT / "data/derived/allocation-v1/involvements.csv",
    "publish": ROOT / "data/derived/publish-v1-triage-v2/publish.csv",
    "loss": ROOT / "data/derived/loss-v1-triage-v2/loss.csv",
    "enacted": ROOT / "data/acquired/bill-census-full/enacted.csv",
    "votes": ROOT / "data/derived/allocation-v1/votes.csv",
    "opposing": ROOT / "data/derived/allocation-v1/opposing.csv",
    "autoInvolvements": ROOT / "data/derived/allocation-v1/involvements-auto.csv",
    "autoVotes": ROOT / "data/derived/allocation-v1/votes-auto.csv",
    "voteParties": ROOT / "data/derived/allocation-v1/vote-parties.csv",
    "ministries": ROOT / "data/derived/ministry-v1/cabinet-bills.csv",
    "taxLedger": ROOT / "data/derived/tax-v1/consumption-tax.csv",
    "resistance": ROOT / "data/derived/org-ledger-v1/ministry-resistance.csv",
    "orgStances": ROOT / "data/derived/org-ledger-v1/org-stances.csv",
}
FIX = "python3 scripts/rebuild_public.py を回して、出たファイルを全部コミットしてください"
from _data_gate import requires_data  # noqa: E402


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str) -> dict:
    return json.loads((DIST / name).read_text(encoding="utf-8"))


class PublicSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ranking = _load("ranking.json")
        self.laws = _load("laws.json")
        self.members = _load("members.json")

    def assert_inputs(self, label: str, recorded: dict, paths: dict) -> None:
        self.assertEqual(set(recorded), set(paths), f"{label} の入力の組が変わった。{FIX}")
        stale = [name for name, path in paths.items() if recorded[name] != _digest(path)]
        self.assertEqual(stale, [], f"{label} が古い入力から作られている（{', '.join(stale)}）。{FIX}")

    def test_ranking_is_built_from_current_derived_data(self) -> None:
        self.assert_inputs("ranking.json", self.ranking["generatedFrom"]["inputs"], build_public_ranking.INPUTS)

    def test_members_is_built_from_current_derived_data(self) -> None:
        self.assert_inputs("members.json", self.members["inputs"], MEMBER_INPUTS)

    def test_reference_members_is_built_from_current_ranking_and_roster(self) -> None:
        reference = _load("members-reference.json")
        paths = {
            "ranking": DIST / "ranking.json",
            "enacted": ROOT / "data/acquired/bill-census-full/enacted.csv",
            "votesIndex": ROOT / "data/acquired/sangiin-votes/votes_index.csv",
            "sangiinMembers": ROOT / "data/acquired/sangiin-votes/members.csv",
            "cabinet": ROOT / "data/acquired/office-holders/cabinet.csv",
            "roster": ROOT / "data/acquired/diet-roster/current.csv",
            "persons": ROOT / "data/derived/person-ids/persons.csv",
        }
        inputs = dict(reference["inputs"])
        ballots = hashlib.sha256()
        for f in sorted((ROOT / "data/acquired/sangiin-votes/ballots").glob("*.csv")):
            ballots.update((f.name + "\n").encode("utf-8"))
            ballots.update(f.read_bytes())
            ballots.update(b"\n")
        self.assertEqual(inputs.pop("ballots", None), ballots.hexdigest(), "members-reference.json の個人別の賛否の照合値が今のファイルと違う")
        self.assert_inputs("members-reference.json", inputs, paths)
        # コロナ期と重なる・分離できない参考の法律は配らない（設計決定0014、app/src/members-reference.ts）。
        reference_laws = sum(1 for law in self.ranking["laws"] if law.get("certainty") == "参考"
                             and not any(n.startswith("コロナ期と") for n in law.get("notes", [])))
        self.assertEqual(reference["counts"]["laws"], reference_laws, "全議員の表の参考の法律の本数が ranking.json と違う")
        roster = (ROOT / "data/acquired/diet-roster/current.csv").read_text(encoding="utf-8").splitlines()[1:]
        names = {m["name"] for m in reference["members"]}
        missing = [line.split(",")[1] for line in roster if line.split(",")[1].replace(" ", "").replace("\u3000", "") not in names]
        self.assertEqual(missing, [], "現職の名簿の人が全議員の表に無い")
        self.assertEqual(reference["counts"]["current"], len(roster), "同じ名前の別人も含め、現職は名簿の人数だけ行がある")
        for m in reference["members"]:
            for r in (m["loss"], m["credit"]):
                self.assertLessEqual(r["low"], r["median"], m["id"])
                self.assertLessEqual(r["median"], r["high"], m["id"])

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

    def test_members_laws_use_the_ranking_amounts(self) -> None:
        ranked = {law["id"]: law for law in self.ranking["laws"]}
        for law in self.members["laws"]:
            self.assertIn(law["id"], ranked, f"議員ページの {law['id']} が公開ランキングに無い")
            self.assertEqual(ranked[law["id"]]["side"], law["side"], law["id"])

    def test_confirmed_laws_without_members_are_marked(self) -> None:
        in_members = {law["id"] for law in self.members["laws"]}
        catalog = {law["id"]: law for law in self.laws["laws"]}
        for law in self.ranking["laws"]:
            if law["certainty"] in ("高", "中") and law["id"] not in in_members:
                marks = catalog[law["id"]]["marks"]
                self.assertIn(build_laws_catalog.MEMBERS_PENDING, marks, f"{law['id']} は議員ページに未反映の印が無い")


if __name__ == "__main__":
    unittest.main()
