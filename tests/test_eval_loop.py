import json
import tempfile
import unittest
from pathlib import Path

from scripts import eval_loop


def row(adopt, kind1="組織手続", kind2="実質改正", overview=eval_loop.NO_OVERVIEW):
    return {"id": "閣法-1-1", "採用": adopt, "決め方": "一致", "理由": "",
            "系統1の値": f"評価対象外|{kind1}|金融|指標|理由", "系統2の値": f"評価対象|{kind2}|金融|指標|理由", "概要の値": overview}


class HoldWithoutOverviewTest(unittest.TestCase):
    TITLE = "中小企業者等に対する金融の円滑化を図るための臨時措置に関する法律の一部を改正する法律案"

    def test_holds_substantive_line_without_overview(self):
        out = eval_loop.hold_without_overview(row("系統2"), self.TITLE)
        self.assertEqual((out["採用"], out["決め方"]), ("保留", "規則で保留"))

    def test_keeps_when_overview_exists(self):
        out = eval_loop.hold_without_overview(row("系統2", overview=eval_loop.overview_value("期限を5年延ばす", "")), self.TITLE)
        self.assertEqual(out["採用"], "系統2")

    def test_keeps_non_substantive_line_and_other_titles(self):
        self.assertEqual(eval_loop.hold_without_overview(row("系統1"), self.TITLE)["採用"], "系統1")
        # 新しく作る法律（一部改正でない）は、題名から新規と分かるのでそのまま
        self.assertEqual(eval_loop.hold_without_overview(row("系統2"), "特定農産加工業経営改善臨時措置法案")["採用"], "系統2")

    def test_holds_any_partial_amendment_without_overview(self):
        # 2026-10-18：前日に保留だった閣法-155-44 を、新しい資料なしに実質改正とした
        out = eval_loop.hold_without_overview(row("系統2"), "情報処理の促進に関する法律の一部を改正する法律案")
        self.assertEqual(out["採用"], "保留")

    def test_keeps_line_that_is_out_of_scope(self):
        # 分野が無く評価対象外に決まる系統は額を作らないので、そのまま（衆法-177-2 地震防災対策特別措置法）
        r = {**row("系統2"), "系統2の値": "評価対象外|実質改正|対応表なし||理由"}
        self.assertEqual(eval_loop.hold_without_overview(r, "地震防災対策特別措置法の一部を改正する法律案")["採用"], "系統2")


class ApplyLinesDestTest(unittest.TestCase):
    def test_explicit_dest_receives_l1_hold_and_production_is_unchanged(self):
        title = "中小企業者等に対する金融の円滑化を図るための臨時措置に関する法律の一部を改正する法律案"
        production = eval_loop.LINES.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "lines"
            folder.mkdir()
            (folder / "l000.json").write_text(
                json.dumps([{"id": "閣法-1-1", "題名": title}], ensure_ascii=False), encoding="utf-8")
            (folder / "inputs.json").write_text(json.dumps({"閣法-1-1": {
                "系統1の値": "評価対象外|組織手続|金融|指標|理由",
                "系統2の値": "評価対象|実質改正|金融|指標|理由",
                "概要の値": eval_loop.NO_OVERVIEW,
            }}, ensure_ascii=False), encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps({"labels": [
                {"id": "閣法-1-1", "採用": "系統2", "決め方": "一致", "理由": "推測で実質改正"},
            ]}, ensure_ascii=False), encoding="utf-8")
            dest = root / "dest.csv"
            count = eval_loop.apply_lines(result, folder / "inputs.json", dest)
            row = dest.read_text(encoding="utf-8").splitlines()[1]
        self.assertEqual(count, 1)
        self.assertTrue(row.startswith("閣法-1-1,保留,規則で保留,"))
        self.assertNotIn("推測で実質改正", row)
        self.assertEqual(eval_loop.LINES.read_bytes(), production)


class ConflictingTitlesTest(unittest.TestCase):
    def test_same_id_with_two_titles_stops_before_write(self):
        production = eval_loop.LINES.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "lines"
            folder.mkdir()
            (folder / "l000.json").write_text(
                json.dumps([{"id": "閣法-1-1", "題名": "甲法の一部を改正する法律案"}], ensure_ascii=False), encoding="utf-8")
            (folder / "l001.json").write_text(
                json.dumps([{"id": "閣法-1-1", "題名": "甲法"}], ensure_ascii=False), encoding="utf-8")
            (folder / "inputs.json").write_text(json.dumps({"閣法-1-1": {
                "系統1の値": "評価対象外|組織手続|金融|指標|理由",
                "系統2の値": "評価対象|実質改正|金融|指標|理由",
                "概要の値": eval_loop.NO_OVERVIEW,
            }}, ensure_ascii=False), encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps({"labels": [
                {"id": "閣法-1-1", "採用": "系統2", "決め方": "一致", "理由": "推測で実質改正"},
            ]}, ensure_ascii=False), encoding="utf-8")
            dest = root / "dest.csv"
            with self.assertRaises(eval_loop.LineStop) as caught:
                eval_loop.apply_lines(result, folder / "inputs.json", dest)
            self.assertIn("題名", caught.exception.reason)
            self.assertFalse(dest.exists())
        self.assertEqual(eval_loop.LINES.read_bytes(), production)

    def test_different_ids_keep_their_own_titles(self):
        production = eval_loop.LINES.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "lines"
            folder.mkdir()
            (folder / "l000.json").write_text(json.dumps([
                {"id": "閣法-1-1", "題名": "甲法の一部を改正する法律案"},
            ], ensure_ascii=False), encoding="utf-8")
            (folder / "l001.json").write_text(json.dumps([
                {"id": "閣法-1-2", "題名": "乙法案"},
            ], ensure_ascii=False), encoding="utf-8")
            judged = {
                "系統1の値": "評価対象外|組織手続|金融|指標|理由",
                "系統2の値": "評価対象|実質改正|金融|指標|理由",
                "概要の値": eval_loop.NO_OVERVIEW,
            }
            (folder / "inputs.json").write_text(json.dumps({
                "閣法-1-1": judged, "閣法-1-2": judged,
            }, ensure_ascii=False), encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps({"labels": [
                {"id": "閣法-1-1", "採用": "系統2", "決め方": "一致", "理由": "推測"},
                {"id": "閣法-1-2", "採用": "系統2", "決め方": "一致", "理由": "新規なので題名で足りる"},
            ]}, ensure_ascii=False), encoding="utf-8")
            dest = root / "dest.csv"
            count = eval_loop.apply_lines(result, folder / "inputs.json", dest, agreement_verified=True)
            rows = dest.read_text(encoding="utf-8").splitlines()
        self.assertEqual(count, 2)
        self.assertTrue(any(line.startswith("閣法-1-1,保留,規則で保留,") for line in rows))
        self.assertTrue(any(line.startswith("閣法-1-2,系統2,一致,") for line in rows))
        self.assertEqual(eval_loop.LINES.read_bytes(), production)


class ApplyLinesUnprovenAgreementTest(unittest.TestCase):
    """apply-lines の直接取り込みは2系統の証跡を確かめないので、自己申告の「一致」を採用しない（#159 の Codex P1）。"""

    def _work(self, root: Path) -> tuple[Path, Path]:
        folder = root / "lines"
        folder.mkdir()
        (folder / "l000.json").write_text(json.dumps([{"id": "閣法-183-21", "題名": "森林の間伐等の実施の促進に関する特別措置法の一部を改正する法律案"}],
                                                     ensure_ascii=False), encoding="utf-8")
        (folder / "inputs.json").write_text(json.dumps({"閣法-183-21": {
            "系統1の値": "保留||対応表なし||理由",
            "系統2の値": "評価対象|実質改正|農林水産|農林水産業の付加価値|理由",
            "概要の値": eval_loop.overview_value("間伐支援の延長と母樹の増殖支援", ""),
        }}, ensure_ascii=False), encoding="utf-8")
        result = root / "result.json"
        result.write_text(json.dumps({"labels": [
            {"id": "閣法-183-21", "採用": "系統2", "決め方": "一致", "理由": "証跡なしの一致"},
        ]}, ensure_ascii=False), encoding="utf-8")
        return result, folder / "inputs.json"

    def test_cli_apply_lines_holds_self_reported_agreement(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest import mock
        production = eval_loop.LINES.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, inputs = self._work(root)
            dest = root / "lines.csv"
            with mock.patch.object(eval_loop, "LINES", dest), redirect_stdout(StringIO()):
                self.assertEqual(eval_loop.main(["apply-lines", str(result), str(inputs)]), 0)
            row = dest.read_text(encoding="utf-8").splitlines()[1]
        self.assertTrue(row.startswith("閣法-183-21,保留,規則で保留,"), row)
        self.assertNotIn(",一致,", row)
        self.assertEqual(eval_loop.LINES.read_bytes(), production)

    def test_verified_candidate_keeps_agreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, inputs = self._work(root)
            dest = root / "lines.csv"
            eval_loop.apply_lines(result, inputs, dest, agreement_verified=True)
            row = dest.read_text(encoding="utf-8").splitlines()[1]
        self.assertTrue(row.startswith("閣法-183-21,系統2,一致,"), row)

    def test_non_agreement_rows_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, inputs = self._work(root)
            result.write_text(json.dumps({"labels": [
                {"id": "閣法-183-21", "採用": "系統2", "決め方": "Sonnetが決定", "理由": "単独の判定"},
            ]}, ensure_ascii=False), encoding="utf-8")
            dest = root / "lines.csv"
            eval_loop.apply_lines(result, inputs, dest)
            row = dest.read_text(encoding="utf-8").splitlines()[1]
        self.assertTrue(row.startswith("閣法-183-21,系統2,Sonnetが決定,"), row)


def lane(pick, session, digest="abc", reason="根拠", inputs="inp"):
    return {"pick": pick, "session_id": session, "input_sha256": digest, "inputs_sha256": inputs, "reason": reason}


class LineAgreementProvenTest(unittest.TestCase):
    """2lane の証跡が欠ける・変わる・保留のときは一致を採用しない。両方の pick が採用と一致するときだけ採用する。"""

    def test_missing_lane_is_not_agreement(self):
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1"), None))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", None, None))

    def test_altered_pick_or_input_is_not_agreement(self):
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1"), lane("系統2", "s2")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1"), lane("系統1", "s2", digest="other")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1"), lane("系統1", "s2", inputs="other")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1", inputs=""), lane("系統1", "s2", inputs="")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1"), lane("系統1", "s1")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "一致", lane("系統1", "s1", reason=""), lane("系統1", "s2")))
        self.assertFalse(eval_loop.line_agreement_proven("系統2", "一致", lane("系統1", "s1"), lane("系統1", "s2")))

    def test_matching_lanes_are_agreement(self):
        self.assertTrue(eval_loop.line_agreement_proven("系統2", "一致", lane("系統2", "s1"), lane("系統2", "s2")))

    def test_hold_and_single_judge_are_not_adopted(self):
        self.assertFalse(eval_loop.line_agreement_proven("保留", "一致", lane("保留", "s1"), lane("保留", "s2")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "Sonnetが決定", lane("系統1", "s1"), lane("系統1", "s2")))
        self.assertFalse(eval_loop.line_agreement_proven("系統1", "Opusが修正", lane("系統1", "s1"), lane("系統1", "s2")))


# 2系統の証拠が残っていない9行は、決め方「一致」のまま採用しない（Orca で未 push だった 7931513 の回収）。
UNPROVEN_HOLDS = {
    "衆法-171-33": ("系統1", "Sonnetが決定"),
    "閣法-151-83": ("系統2", "Opusが修正"),
    "閣法-154-89": ("系統1", "Sonnetが決定"),
    "閣法-159-73": ("系統1", "Opusが修正"),
    "閣法-164-35": ("系統1", "Sonnetが決定"),
    "閣法-164-7": ("系統1", "Sonnetが決定"),
    "閣法-166-17": ("系統1", "Sonnetが決定"),
    "閣法-177-12": ("保留", "Opusが修正"),
    "閣法-183-21": ("系統2", "Sonnetが決定"),
}


class UnprovenTiebreakHoldTest(unittest.TestCase):
    def test_nine_rows_are_not_self_reported_agreement(self):
        import csv
        with eval_loop.LINES.open(encoding="utf-8", newline="") as handle:
            rows = {r["id"]: r for r in csv.DictReader(handle)}
        for law_id, (pick, how) in UNPROVEN_HOLDS.items():
            row = rows[law_id]
            self.assertNotEqual(row["決め方"], "一致", law_id)
            self.assertEqual((row["採用"], row["決め方"]), (pick, how), law_id)
            self.assertFalse(eval_loop.line_agreement_proven(row["採用"], row["決め方"], None, None), law_id)


if __name__ == "__main__":
    unittest.main()
