import unittest

from scripts import daily_update


class DailyUpdateTests(unittest.TestCase):
    def test_merge_keeps_missing_rows_and_updates_by_key(self):
        old = [{"種別": "閣法", "提出回次": "1", "番号": "1", "題名": "a"}, {"種別": "閣法", "提出回次": "1", "番号": "2", "題名": "b"}]
        new = [{"種別": "閣法", "提出回次": "1", "番号": "2", "題名": "b2"}, {"種別": "衆法", "提出回次": "2", "番号": "1", "題名": "c"}]
        merged, added, updated = daily_update.merge_rows(old, new, daily_update.CENSUS_KEY)
        self.assertEqual([r["題名"] for r in merged], ["a", "b2", "c"])
        self.assertEqual((added, updated), (1, 1))

    def test_committed_census_is_fully_labeled(self):
        self.assertEqual(daily_update.unlabeled_laws(), [])

    def test_standing_approvals_are_publishable_only(self):
        approved = daily_update.standing_approvals()
        self.assertTrue(approved)
        self.assertEqual(len(approved), len(set(approved)))


if __name__ == "__main__":
    unittest.main()


class EvaluationLoopTests(unittest.TestCase):
    def test_queue_lists_only_laws_that_still_need_an_ai_judgment(self):
        import csv
        queue = daily_update.evaluation_queue()
        self.assertEqual(set(queue), {"振り分けの決着", "分野ラベル", "出典チェックの不一致", "系統の決着"})
        with (daily_update.DERIVED / "bill-triage-v2" / "labels-line1.csv").open(encoding="utf-8") as f:
            line1 = {r["id"]: r for r in csv.DictReader(f)}
        for item in queue["振り分けの決着"]:
            self.assertTrue(line1[item["id"]]["規則"].startswith("D5"), item["id"])
        with (daily_update.DERIVED / "ai-field-v1" / "labels.csv").open(encoding="utf-8") as f:
            labeled = {r["id"] for r in csv.DictReader(f)}
        self.assertFalse(labeled & {item["id"] for item in queue["分野ラベル"]})
        # 系統の決着：保留のうち、第3の判定者の記録が無いか、記録の入力が今と違うものだけ
        with (daily_update.DERIVED / "bill-triage-v2" / "agreement.csv").open(encoding="utf-8") as f:
            held = {r["id"]: r["題名"] for r in csv.DictReader(f) if r["結果"] == "保留"}
        with (daily_update.DERIVED / "bill-triage-v2" / "tiebreak-lines.csv").open(encoding="utf-8") as f:
            judged = {r["id"]: r for r in csv.DictReader(f)}
        now = daily_update._line_inputs(daily_update.DERIVED)
        self.assertEqual({item["id"] for item in queue["系統の決着"]},
                         {i for i, title in held.items()
                          if not daily_update._line_record_is_current(judged.get(i), now.get(i, ("", "", "")), title)})

    def test_line_queue_rejudges_only_when_inputs_change(self):
        import shutil
        import tempfile
        from pathlib import Path
        from scripts import eval_loop
        src = daily_update.DERIVED
        with tempfile.TemporaryDirectory() as tmp:
            derived = Path(tmp)
            for name in ("bill-triage-v2/labels-line1.csv", "bill-triage-v2/labels-line2.csv", "law-overviews-v1/overviews.csv"):
                (derived / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src / name, derived / name)
            law = next(r["id"] for r in eval_loop._read(src / "bill-triage-v2" / "agreement.csv") if r["結果"] == "保留")
            (derived / "bill-triage-v2" / "agreement.csv").write_text(f"id,題名,結果\n{law},題名,保留\n", encoding="utf-8")
            queued = lambda: [x["id"] for x in daily_update.evaluation_queue(derived)["系統の決着"]]
            self.assertEqual(queued(), [law])
            v1, v2, ov = daily_update._line_inputs(derived)[law]
            lines = derived / "bill-triage-v2" / "tiebreak-lines.csv"
            record = {"id": law, "採用": "保留", "決め方": "一致", "理由": "r", "系統1の値": v1, "系統2の値": v2,
                      "概要の値": ov, "題名": "題名"}
            eval_loop._merge(lines, eval_loop.LINES_HEADER, [record])
            self.assertEqual(queued(), [])
            eval_loop._merge(lines, eval_loop.LINES_HEADER, [{**record, "概要の値": "0000000000000000"}])
            self.assertEqual(queued(), [law])
            eval_loop._merge(lines, eval_loop.LINES_HEADER, [{**record, "題名": "前の題名"}])
            self.assertEqual(queued(), [law])

    def test_tree_results_merge_into_the_tables_by_id(self):
        import json
        import tempfile
        from pathlib import Path
        from scripts import eval_loop
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "labels.csv"
            result = Path(tmp) / "result.json"
            result.write_text(json.dumps({"result": {"labels": [{"id": "b", "field": "教育", "how": "一致", "reason": "学校"}]}}), encoding="utf-8")
            eval_loop._merge(table, eval_loop.FIELD_HEADER, [{"id": "a", "分野": "経済全体", "決め方": "一致", "理由": "x"}])
            eval_loop._merge(table, eval_loop.FIELD_HEADER, [{"id": x["id"], "分野": x["field"], "決め方": x["how"], "理由": x["reason"]}
                                                            for x in eval_loop._labels(result)])
            eval_loop._merge(table, eval_loop.FIELD_HEADER, [{"id": "a", "分野": "建設", "決め方": "Opusが修正", "理由": "y"}])
            self.assertEqual(table.read_text(encoding="utf-8").splitlines(),
                             ["id,分野,決め方,理由", "a,建設,Opusが修正,y", "b,教育,一致,学校"])

    def test_line_tiebreak_records_the_inputs_it_judged(self):
        # 系統の決着は、判定したときの系統1・系統2の値を残す（入力が変われば run-impact-v1.mjs が当てない）
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        from scripts import eval_loop
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.json"
            result.write_text(json.dumps({"labels": [{"id": "x", "採用": "系統2", "決め方": "一致", "理由": "r"}]}), encoding="utf-8")
            # 指紋は木に渡したときの inputs.json から取る（取り込む時点の表は読まない）
            inputs = Path(tmp) / "inputs.json"
            inputs.write_text(json.dumps({"x": {"系統1の値": "評価対象外|定型改正|金融||a", "系統2の値": "評価対象|新規|金融|貸出残高|b",
                                                 "概要の値": eval_loop.overview_value("何", "狙"), "題名": "銀行法の一部を改正する法律案"}}),
                              encoding="utf-8")
            with mock.patch.object(eval_loop, "LINES", Path(tmp) / "lines.csv"):
                eval_loop.apply_lines(result, inputs, agreement_verified=True)
                rows = (Path(tmp) / "lines.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows, ["id,採用,決め方,理由,系統1の値,系統2の値,概要の値,題名",
                                f"x,系統2,一致,r,評価対象外|定型改正|金融||a,評価対象|新規|金融|貸出残高|b,{eval_loop.overview_value('何', '狙')},"
                                "銀行法の一部を改正する法律案"])
