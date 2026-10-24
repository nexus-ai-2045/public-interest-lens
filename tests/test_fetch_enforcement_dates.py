import unittest

from scripts import fetch_enforcement_dates as f


class EnforcementDatesTests(unittest.TestCase):
    def test_kanji_round_trip(self):
        for n in (1, 4, 10, 11, 25, 100, 105, 116, 210):
            self.assertEqual(f.from_kanji(f.to_kanji(n)), n)
        self.assertEqual(f.to_kanji(116), "百十六")

    def test_law_num_and_id(self):
        own = f.parse_law_num("平成十年法律第二十五号")
        self.assertEqual(own, ("平成", 10, 25))
        self.assertEqual(f.law_id_of(*own), "410AC0000000025")
        self.assertEqual(f.format_law_num(*own), "平成十年法律第二十五号")
        self.assertEqual(f.parse_law_num("平成元年法律第四号"), ("平成", 1, 4))

    def test_wareki(self):
        parts = f.parse_wareki("平成28年 6月 3日")
        self.assertEqual(f.wareki_to_iso(parts), "2016-06-03")

    def test_amended_titles(self):
        self.assertEqual(f.amended_titles("預金保険法の一部を改正する法律案"), ["預金保険法"])
        self.assertEqual(f.amended_titles("船員法等の一部を改正する法律案"), ["船員法等"])
        self.assertIsNone(f.amended_titles("中部国際空港の設置及び管理に関する法律案"))

    def test_pick_main(self):
        self.assertEqual(f.pick_main(["2020-04-01"]), ("2020-04-01", ""))
        self.assertEqual(f.pick_main(["2020-04-01", "2020-04-01", "2021-04-01"])[0], "2020-04-01")
        self.assertEqual(f.pick_main(["2020-04-01", "2021-04-01"])[0], "")
        self.assertEqual(f.pick_main([]), ("", ""))

    def test_merge_ledger_keeps_rows_outside_the_fetch_and_appends_new_ones(self):
        columns = [*f.OUT_COLS, "施行期日の原文"]
        old = [{**{c: "" for c in columns}, "id": "閣法-1-1", "施行日": "2000-01-01", "施行期日の原文": "原文"},
               {**{c: "" for c in columns}, "id": "閣法-1-2", "施行日": "2001-01-01"}]
        new = [["閣法-1-2", "題名", "", "", "2002-02-02", "", "", "", ""], ["閣法-1-3", "題名3", "", "", "", "", "取得不可", "", ""]]
        merged = f.merge_ledger(columns, old, new)
        self.assertEqual([r["id"] for r in merged], ["閣法-1-1", "閣法-1-2", "閣法-1-3"])
        self.assertEqual(merged[0]["施行期日の原文"], "原文")  # 今回の対象でない行は変えない
        self.assertEqual(merged[1]["施行日"], "2002-02-02")  # 同じ id は置き換える
        self.assertEqual(merged[2]["取得方法"], "取得不可")  # 台帳に無い id は末尾に足す（日付は捏造しない）
        self.assertEqual(merged[2]["施行日"], "")

    def test_merge_ledger_does_not_erase_dates_when_the_fetch_fails(self):
        columns = [*f.OUT_COLS, "施行期日の原文"]
        old = [{**{c: "" for c in columns}, "id": "閣法-1-1", "施行日": "2000-01-01", "取得方法": "附則", "施行期日の原文": "原文"},
               {**{c: "" for c in columns}, "id": "閣法-1-2", "施行日": "2001-01-01", "施行期日の原文": "原文2"}]
        new = [["閣法-1-1", "題名", "", "", "", "", "取得不可", "版がない", ""],
               ["閣法-1-2", "題名", "", "", "2001-01-01", "2001-01-01", "条文", "", ""]]
        old.append({**{c: "" for c in columns}, "id": "閣法-1-3", "取得方法": "施行期日条文（政令で定める日）", "備考": "政令で定める日"})
        new.append(["閣法-1-3", "題名", "", "", "", "", "取得不可", "現行法令が無い", ""])
        old.append({**{c: "" for c in columns}, "id": "閣法-1-4", "施行日": "2003-04-01", "出典URL": "https://a"})
        new.append(["閣法-1-4", "題名", "", "", "", "2003-04-01;2004-04-01", "改正履歴", "", "https://a;https://b"])
        merged = f.merge_ledger(columns, old, new)
        self.assertEqual(merged[3]["施行日"], "2003-04-01")  # 主な日は既存の値を残す
        self.assertEqual(merged[3]["施行日の候補（; 区切り）"], "2003-04-01;2004-04-01")  # 今回の候補は足し込む
        self.assertEqual(merged[3]["出典URL"], "https://a;https://b")
        self.assertEqual(merged[0]["施行日"], "2000-01-01")  # 取れなかった日は既存の確かめた値を残す
        self.assertEqual(merged[2]["取得方法"], "施行期日条文（政令で定める日）")  # 日が無い行どうしでも、調べた理由を消さない
        self.assertEqual(merged[0]["取得方法"], "附則")
        self.assertEqual(merged[1]["取得方法"], "条文")  # 同じ日なら新しい取得で置き換え
        self.assertEqual(merged[1]["施行期日の原文"], "原文2")  # 後で足した列は引き継ぐ


if __name__ == "__main__":
    unittest.main()


class ReportOverwriteTests(unittest.TestCase):
    """毎朝の段階1だけの実行で、段階2・3が書いたレポートを消さない。"""

    def _run(self, existing):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "enforcement-dates.md"
            if existing is not None:
                path.write_text(existing, encoding="utf-8")
            row = ["閣法-200-1", "例の法律", "令和元年法律第一号", "2019-05-01", "2019-06-01", "2019-06-01", "law_revisions", "", ""]
            with mock.patch.object(f, "REPORT", path):
                f.write_report([row])
            return path.read_text(encoding="utf-8")

    def test_keeps_report_written_by_later_stages(self):
        existing = "# 成立法（評価対象）の施行日 取得結果\n\n評価対象 349 本の施行日を取った結果。3段階で取っている。\n\n## 施行期日政令による補完（3段階目）\n"
        self.assertEqual(self._run(existing), existing)

    def test_writes_stage1_report_when_none_or_stage1_only(self):
        self.assertIn("## 件数", self._run(None))
        self.assertIn("- 対象: 1 本", self._run("# 古い段階1だけのレポート\n"))
