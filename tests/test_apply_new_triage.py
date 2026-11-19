import tempfile
import unittest
from pathlib import Path

from scripts import apply_new_triage as nt
from scripts import build_all_laws_outcomes as ol
from scripts import build_public_ranking as pr

A = {"種類": "定型改正", "分野": "対応表なし", "指標": "", "判定": "評価対象外", "理由": "給与法の定例改正"}


def v1(law: str = "閣法-999-1", **changes: str) -> dict[str, str]:
    return {"id": law, **A, **changes}


class CombineTest(unittest.TestCase):
    def test_combine_reproduces_every_existing_row(self):
        # 採用の決まりを新しく作らない：既存の全行が、A・B の列から同じ規則で出る。
        for row in nt.read(nt.V1 / "triage.csv"):
            a = {k: row[f"A_{k}"] for k in nt.V1_COLUMNS[1:]}
            b = {k: row[f"B_{k}"] for k in nt.V1_COLUMNS[1:]}
            self.assertEqual(nt.combine(row["id"], a, b), row, row["id"])

    def test_disagreement_is_held_and_only_agreed_items_are_filled(self):
        out = nt.combine("閣法-999-1", A, {**A, "種類": "実質改正"})
        self.assertEqual((out["結果"], out["種類"], out["分野"]), ("保留（2系統が不一致）", "", "対応表なし"))
        market = {"種類": "新規", "分野": "金融", "指標": "貸出残高", "判定": "評価対象", "理由": "x"}
        out = nt.combine("閣法-999-2", market, {**market, "指標": "不良債権比率"})
        self.assertEqual((out["結果"], out["指標"]), ("保留（指標が不一致）", ""))


class CheckTest(unittest.TestCase):
    def test_v1_lane_must_cover_the_input_in_order_with_known_words_and_a_reason(self):
        nt.check_v1([v1()], ["閣法-999-1"], "lane-A")
        nt.check_v1([v1(種類="保留")], ["閣法-999-1"], "lane-A")  # 迷ったら保留（spec.md）
        for rows in ([], [v1("閣法-999-2")], [v1(種類="その他")], [v1(理由=" ")], [v1(指標="賃金")], [{**v1(), "余分": ""}]):
            with self.assertRaises(ValueError):
                nt.check_v1(rows, ["閣法-999-1"], "lane-A")

    def test_line2_must_copy_the_input_and_keep_verdict_consistent(self):
        source = [{"id": "閣法-999-1", "題名": "題", "付託委員会（衆／参）": "内閣／内閣"}]
        row = {"id": "閣法-999-1", "題名": "題", "付託委員会": "内閣／内閣", "系統2_種類": "実質改正", "系統2_分野": "対応表なし",
               "系統2_指標": "", "系統2_判定": "評価対象外", "系統2_理由": "x"}
        nt.check_line2([row], source)
        for bad in ({"題名": "別の題"}, {"系統2_判定": "評価対象"}, {"系統2_種類": "保留"}, {"系統2_理由": ""}):
            with self.assertRaises(ValueError):
                nt.check_line2([{**row, **bad}], source)


class AppendTest(unittest.TestCase):
    def test_append_keeps_existing_bytes_and_line_ending(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ending in (b"\r\n", b"\n"):
                path = Path(tmp) / "t.csv"
                before = b"id,x" + ending + b"a,1" + ending
                path.write_bytes(before)
                nt.append(path, ["id", "x"], [{"id": "b", "x": "2"}])
                self.assertEqual(path.read_bytes(), before + b"b,2" + ending)


class RecordTest(unittest.TestCase):
    def test_every_added_law_has_a_record_with_models_prompts_and_matching_hashes(self):
        # 説明責任：あとから足した法律は、入力・各系統の結果・依頼文・モデルが残っていて、指紋が記録と合う。
        import json

        recorded = {}
        for folder in sorted((nt.V1 / "additions").iterdir()):
            record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
            for lane in nt.SPECS:
                self.assertTrue(record["lanes"][lane]["model"])
                self.assertTrue((folder / record["lanes"][lane]["prompt"]).exists())
            for name in ("input.csv", "lane-A.csv", "lane-B.csv", "lane-L2.csv", *nt.PROMPTS):
                self.assertEqual(nt.sha256(folder / name), record["sha256"][name], name)
            a, b = nt.read(folder / "lane-A.csv"), nt.read(folder / "lane-B.csv")
            for law, x, y in zip(record["laws"], a, b):
                recorded[law] = nt.combine(law, x, y)
            line2 = {r["id"]: r for r in nt.read(nt.LINE2 / "labels.csv")}
            for r in nt.read(folder / "lane-L2.csv"):
                self.assertEqual(line2[r["id"]], r)
        triage = {r["id"]: r for r in nt.read(nt.V1 / "triage.csv")}
        for law, row in recorded.items():
            self.assertEqual(triage[law], row, law)

    def test_no_enacted_law_is_left_without_triage(self):
        self.assertEqual(nt.untriaged(nt.read(nt.ENACTED), {r["id"] for r in nt.read(nt.V1 / "triage.csv")}), [])


class UntriagedGuardTest(unittest.TestCase):
    """振り分けが付く前の成立法は、落とさず・落ちず、理由つきの保留として出る。"""

    def test_ledger_keeps_untriaged_laws_as_held_with_the_reason(self):
        enacted = {"閣法-999-1": {"題名": "済みの法律"}, "閣法-999-2": {"題名": "新しい法律"}}
        rows = ol.untriaged_rows(enacted, {"閣法-999-1"}, {"閣法-999-2": "2027-04-01"})
        self.assertEqual([r["id"] for r in rows], ["閣法-999-2"])
        row = rows[0]
        self.assertEqual((row["結果"], row["経路"], row["理由"], row["施行日"]), ("保留", ol.ROUTE_UNTRIAGED, ol.UNTRIAGED_REASON, "2027-04-01"))
        self.assertEqual((row["分野"], row["指標"], row["損失または便益の額"]), ("", "", ""))

    def test_ranking_gives_a_held_row_instead_of_a_key_error(self):
        row = pr._no_amount("閣法-999-2", "新しい法律", {}, {}, {}, {}, {})
        self.assertEqual(row["outcome"], pr.OUTCOMES["triage_hold"])
        self.assertIn("まだ無い", row["reason"])


if __name__ == "__main__":
    unittest.main()
