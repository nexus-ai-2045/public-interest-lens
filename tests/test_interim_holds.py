"""当て直しまでの暫定の降格（interim-holds.csv）：抜き取り2回目で不合格の個別の額を、台帳と公開ランキングの両方で参考に下げる。"""
import csv
import unittest
from pathlib import Path

from scripts import build_public_ranking
from scripts import primary_source_corrections as corrections
from scripts.build_evaluation_ledger import SAMPLED_STATES, VERIFY_STATES, verify_state
from scripts.evaluation_rules import (
    INTERIM_HOLDS,
    INTERIM_REASON_PREFIX,
    STATE_INTERIM_HELD,
    interim_holds,
)

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "derived" / "evaluation-ledger-v1"


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class InterimHolds(unittest.TestCase):
    def test_holds_are_the_three_new_individual_amount_failures(self):
        # 個別の額7本中、不合格4本。衆法-185-2 は初回の抜き取りで不合格（sample-verdicts.csv）なので、ここには入れない（1つの事実は1か所）。
        self.assertEqual(set(interim_holds()), {"衆法-189-20", "閣法-193-61", "閣法-196-2"})

    def test_no_overlap_with_first_sample(self):
        first = {r["id"] for r in read(LEDGER / "sample-verdicts.csv")}
        self.assertEqual(set(interim_holds()) & first, set())

    def test_ledger_marks_held_and_individual_failures_leave_ranking(self):
        rows = {r["id"]: r for r in read(LEDGER / "ledger.csv")}
        fixed = corrections.load()
        for law_id, reason in interim_holds().items():
            if fixed.get(law_id, {}).get("経済に効くか", {}).get("直した値") == corrections.INSTITUTIONAL:
                # 訂正表で制度と直した法律は評価対象外に移る（暫定の降格より先に、訂正が値そのものを直す）
                self.assertTrue(rows[law_id]["到達点"].startswith("評価対象外"), law_id)
            elif "分野" in fixed.get(law_id, {}):
                # 訂正表で分野を直した法律は、個別の額（旧い分野で計算）を外し、直した分野の参考額に移る
                self.assertTrue(rows[law_id]["到達点"].startswith("参考額"), law_id)
            else:
                self.assertTrue(rows[law_id]["到達点"].startswith("額（個別"), law_id)
            self.assertEqual(rows[law_id]["検証状態"], STATE_INTERIM_HELD)
            self.assertEqual(rows[law_id]["検証メモ"], f"{INTERIM_REASON_PREFIX}{reason}")
        individual = [r for r in rows.values() if r["到達点"].startswith("額（個別")]
        failed = [r["id"] for r in individual if r["検証状態"] in ("参考に下げた", STATE_INTERIM_HELD)]
        # 衆法-189-20 は制度と直して評価対象外、閣法-193-61・閣法-196-2 は分野を直して参考額へ移り、個別の額に残らない
        self.assertEqual(sorted(failed), ["衆法-185-2"])

    def test_interim_state_is_not_counted_as_first_sample(self):
        self.assertIn(STATE_INTERIM_HELD, VERIFY_STATES)
        self.assertNotIn(STATE_INTERIM_HELD, SAMPLED_STATES)

    def test_public_ranking_demotes_with_marked_reason(self):
        failed = build_public_ranking.verification_failed()
        for law_id, reason in interim_holds().items():
            self.assertEqual(failed[law_id], f"{INTERIM_REASON_PREFIX}{reason}")

    def test_verify_state_holds_amounts_and_rejects_overlap(self):
        held = {"x": "分野：サイトA／一次資料ではB"}
        self.assertEqual(verify_state("x", "2系統が一致", {}, "額（個別の因果の鎖）", "段階3", interim=held),
                         (STATE_INTERIM_HELD, f"{INTERIM_REASON_PREFIX}分野：サイトA／一次資料ではB"))
        # 額の無い到達点は下げられないので、台帳と公開ランキングが食い違わないよう止める
        with self.assertRaises(ValueError):
            verify_state("x", "2系統が一致", {}, "保留", "", interim=held)
        with self.assertRaises(ValueError):
            verify_state("x", "2系統が一致", {"x": {"判定": "不合格", "食い違い": ""}}, "額（個別の因果の鎖）", "段階3", interim=held)

    def test_rejects_rows_without_failure_or_reason(self):
        tmp = ROOT / "data" / "derived" / "evaluation-ledger-v1" / "_tmp_interim_bad.csv"
        try:
            tmp.write_text("id,判定,食い違い,出典\nx,合格,,y\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                interim_holds(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        self.assertTrue(INTERIM_HOLDS.exists())


if __name__ == "__main__":
    unittest.main()
