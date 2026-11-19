import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class CheckV1RulesTest(unittest.TestCase):
    def test_verdict_must_follow_kind_and_field(self):
        ok = [v1(), v1(種類="実質改正", 分野="金融", 指標="貸出残高", 判定="評価対象"), v1(種類="保留"), v1(分野="金融", 指標="保留", 判定="保留")]
        for row in ok:
            nt.check_v1([row], ["閣法-999-1"], "lane-A")
        bad = [v1(種類="新規", 分野="金融", 判定="評価対象"),  # 評価対象なのに指標が空
               v1(種類="定型改正", 分野="金融", 指標="貸出残高", 判定="評価対象"),  # 定型改正は評価対象にならない
               v1(種類="新規", 判定="評価対象"),  # 対応表なしは評価対象にならない
               v1(種類="新規", 分野="金融", 判定="評価対象外"),  # 対象外の条件に当たらない
               v1(分野="医療"), v1(分野="金融", 指標="賃金", 判定="保留")]
        for row in bad:
            with self.assertRaises(ValueError, msg=row):
                nt.check_v1([row], ["閣法-999-1"], "lane-A")

    def test_existing_lane_rows_pass_except_one_old_blank_field(self):
        # 新しい検査は既存の6,830件（A・B）を誤って拒まない。例外は分野を空で書いた古い1件だけ（いまは「保留」と書く決まり）。
        failed = []
        for row in nt.read(nt.V1 / "triage.csv"):
            for lane in "AB":
                try:
                    nt.check_v1([{"id": row["id"], **{k: row[f"{lane}_{k}"] for k in nt.V1_COLUMNS[1:]}}], [row["id"]], lane)
                except ValueError:
                    failed.append((row["id"], lane))
        self.assertEqual(failed, [("閣法-213-23", "A")])


class ApplyTest(unittest.TestCase):
    """apply を一時フォルダの表で回す。表に書く前に全部を確かめ、途中で失敗したら何も書かない。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        v1_dir, line2_dir = self.tmp / "v1", self.tmp / "line2"
        v1_dir.mkdir()
        line2_dir.mkdir()
        (self.tmp / "enacted.csv").write_text("種別,提出回次,番号,題名,付託委員会_衆,付託委員会_参\n閣法,999,1,済み,内閣,内閣\n閣法,999,2,新しい給与法,内閣,内閣\n", encoding="utf-8")
        head = ",".join(["id", "結果", "種類", "分野", "指標"] + [f"{x}_{k}" for x in "AB" for k in nt.V1_COLUMNS[1:]])
        (v1_dir / "triage.csv").write_text(head + "\n閣法-999-1,評価対象外,定型改正,対応表なし,,定型改正,対応表なし,,評価対象外,x,定型改正,対応表なし,,評価対象外,y\n", encoding="utf-8")
        (line2_dir / "labels.csv").write_text(",".join(nt.LINE2_COLUMNS) + "\n", encoding="utf-8")
        for spec in {s for specs in nt.SPECS.values() for s in specs}:
            (v1_dir if spec.parent == nt.V1 else line2_dir).joinpath(spec.name).write_text(spec.name, encoding="utf-8")
        self.patches = [mock.patch.object(nt, "ENACTED", self.tmp / "enacted.csv"), mock.patch.object(nt, "V1", v1_dir),
                        mock.patch.object(nt, "LINE2", line2_dir), mock.patch.object(nt, "ROOT", self.tmp),
                        mock.patch.object(nt, "SPECS", {lane: [(v1_dir if s.parent == nt.V1 else line2_dir) / s.name for s in specs] for lane, specs in nt.SPECS.items()})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.work = self.tmp / "work"
        nt.prepare(self.work)
        line = "閣法-999-2,定型改正,対応表なし,,評価対象外,"
        (self.work / "lane-A" / "output.csv").write_text("id,種類,分野,指標,判定,理由\n" + line + "給与法の定例改正\n", encoding="utf-8")
        (self.work / "lane-B" / "output.csv").write_text("id,種類,分野,指標,判定,理由\n" + line + "給与の定例改定\n", encoding="utf-8")
        (self.work / "lane-L2" / "output.csv").write_text(",".join(nt.LINE2_COLUMNS) + "\n閣法-999-2,新しい給与法,内閣／内閣,定型改正,対応表なし,,評価対象外,給与法\n", encoding="utf-8")
        for name in nt.PROMPTS:
            (self.work / name).write_text("依頼文", encoding="utf-8")
        self.models = {"lane-A": "m1", "lane-B": "m2", "lane-L2": "m3"}

    def tables(self):
        return (nt.V1 / "triage.csv").read_bytes(), (nt.LINE2 / "labels.csv").read_bytes()

    def test_apply_writes_tables_and_record(self):
        nt.apply(self.work, self.models, "2026-01-01")
        self.assertEqual(nt.read(nt.V1 / "triage.csv")[-1]["結果"], "評価対象外")
        record = json.loads((nt.V1 / "additions" / "2026-01-01" / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["laws"], ["閣法-999-2"])

    def test_missing_prompt_writes_nothing(self):
        (self.work / "prompt-v1.md").unlink()
        before = self.tables()
        with self.assertRaises(ValueError):
            nt.apply(self.work, self.models, "2026-01-01")
        self.assertEqual(self.tables(), before)
        self.assertFalse((nt.V1 / "additions").exists())

    def test_copied_lane_or_same_model_names_are_refused(self):
        before = self.tables()
        with self.assertRaises(ValueError):
            nt.apply(self.work, {**self.models, "lane-B": "m1"}, "2026-01-01")
        shutil.copyfile(self.work / "lane-A" / "output.csv", self.work / "lane-B" / "output.csv")
        with self.assertRaises(ValueError):
            nt.apply(self.work, self.models, "2026-01-01")
        self.assertEqual(self.tables(), before)

    def test_existing_record_folder_is_not_overwritten(self):
        (nt.V1 / "additions" / "2026-01-01").mkdir(parents=True)
        before = self.tables()
        with self.assertRaises(ValueError):
            nt.apply(self.work, self.models, "2026-01-01")
        self.assertEqual(self.tables(), before)


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
