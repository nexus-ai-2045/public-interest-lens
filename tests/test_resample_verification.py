"""抜き取り検証2回目（sample-v2）の検査。

標本が記録した種と手順で作り直せること、初回と重ならないこと、突き合わせの判定が2系統の記録とサイトの値から
機械的に出ること（verdicts.csv を手で書き換えていないこと）を確かめる。
"""
import csv
import json
import unittest
from pathlib import Path

from scripts import build_public_ranking
from scripts.evaluation_rules import SAMPLE2_REASON_PREFIX, sample2_failures
from scripts.resample_verification import (
    MEMO,
    SEED_V2,
    judge,
    ledger_state,
    load_record,
    overriding,
)

L = Path(__file__).resolve().parents[1] / "data" / "derived" / "evaluation-ledger-v1"
V2 = L / "sample-v2"


def rows(p: Path) -> list[dict]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


SITE = {"類型": "実質改正", "分類": "評価対象", "到達点": "参考額（産業の付加価値の差）", "分野": "金融"}
READ = {"類型": "実質改正", "経済に効くか": "経済に効く", "主な産業分野": "金融", "範囲": "その産業全体"}


class JudgeRules(unittest.TestCase):
    def test_single_ruling_does_not_override_agreement(self):
        # 2系統が一致した値を、1つの裁定だけで覆さない（設計決定0007）。独立の確認があれば採る
        flip = {"経済に効くか": "制度のみ" if READ["経済に効くか"] != "制度のみ" else "経済に効く"}
        self.assertEqual(overriding(READ, dict(READ), flip), ["経済に効くか"])
        self.assertEqual(judge(SITE, READ, dict(READ), flip)[0], "割れ")
        self.assertNotEqual(judge(SITE, READ, dict(READ), flip, ("経済に効くか",))[0], "割れ")

    def test_agree_and_match_passes(self):
        self.assertEqual(judge(SITE, READ, dict(READ))[0], "合格")

    def test_institutional_is_read_by_reach(self):
        site = {**SITE, "分類": "評価対象外", "到達点": "保留"}
        # 振り分けの分類が評価対象外でも、到達点が保留ならサイトは「経済に効く」と扱う
        self.assertEqual(judge(site, READ, dict(READ))[0], "合格")
        site = {**SITE, "到達点": "評価対象外"}
        self.assertEqual(judge(site, READ, dict(READ))[0], "不合格")

    def test_narrow_scope_fails_amount(self):
        a = {**READ, "範囲": "産業の一部（狭い特例）"}
        v, diffs, _ = judge(SITE, a, dict(a))
        self.assertEqual(v, "不合格")
        self.assertTrue(any(d.startswith("範囲") for d in diffs))

    def test_split_waits_then_ruling_decides(self):
        b = {**READ, "類型": "定型改正"}
        self.assertEqual(judge(SITE, READ, b)[0], "割れ")
        self.assertEqual(judge(SITE, READ, b, {"類型": "実質改正"})[0], "合格")

    def test_field_and_scope_only_for_amounts(self):
        site = {**SITE, "到達点": "保留"}
        a = {**READ, "主な産業分野": "農林水産", "範囲": "産業の一部（狭い特例）"}
        self.assertEqual(judge(site, a, dict(a))[0], "合格")


class SampleRecord(unittest.TestCase):
    def test_manifest_matches_sample(self):
        m = json.loads((V2 / "manifest.json").read_text(encoding="utf-8"))
        s = rows(V2 / "sample.csv")
        self.assertEqual(m["種"], SEED_V2)
        self.assertEqual(m["標本"], len(s))
        self.assertEqual(sum(v["標本"] for v in m["層ごと"].values()), len(s))

    def test_no_overlap_with_first_sample(self):
        first = {r["id"] for r in rows(L / "sample.csv")}
        self.assertFalse(first & {r["id"] for r in rows(V2 / "sample.csv")})

    def test_verdicts_follow_from_lines(self):
        a = {x["id"]: x for x in json.loads((V2 / "lineA.json").read_text(encoding="utf-8"))}
        b = {x["id"]: x for x in json.loads((V2 / "lineB.json").read_text(encoding="utf-8"))}
        p = V2 / "rulings.json"
        rulings = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        verdicts = rows(V2 / "verdicts.csv")
        self.assertEqual({r["id"] for r in verdicts}, {r["id"] for r in rows(V2 / "sample.csv")})
        for r in verdicts:
            site = {k: r[f"サイト_{k}"] for k in ("類型", "分類", "到達点", "分野")}
            ru = rulings.get(r["id"], {})
            v, _, _ = judge(site, a[r["id"]], b[r["id"]], ru.get("値"), ru.get("確認", ()))
            self.assertEqual(v, r["判定"], r["id"])
            if r["判定"] == "割れ":  # 割れが残るのは、裁定が2系統の一致を覆して独立の確認を待つ法律だけ
                self.assertTrue(overriding(a[r["id"]], b[r["id"]], ru.get("値"), ru.get("確認", ())), f"{r['id']} は裁定が無い")

    def test_every_failure_is_resolved(self):
        failed = {r["id"] for r in rows(V2 / "verdicts.csv") if r["判定"] == "不合格"}
        res = {r["id"]: r for r in rows(V2 / "resolutions.csv")} if (V2 / "resolutions.csv").exists() else {}
        self.assertEqual(failed - set(res), set(), "決着の無い不合格がある")
        for i in failed:
            self.assertTrue(res[i]["決着"] and res[i]["原因"] and res[i]["理由"], i)


class LedgerIntegration(unittest.TestCase):
    """台帳は標本2を今のサイトの値で判定し直す。公開ランキングは、まだ不合格の標本2の法律を参考に下げる。"""

    def setUp(self):
        self.ledger = {r["id"]: r for r in rows(L / "ledger.csv")}
        self.rec = load_record()

    def test_ledger_state_is_recomputed_from_current_site(self):
        self.assertEqual(set(self.rec), {r["id"] for r in rows(V2 / "sample.csv")})
        for i, rec in self.rec.items():
            r = self.ledger[i]
            site = {"類型": r["類型"], "分類": r["分類"], "到達点": r["到達点"], "分野": r["分野"], "確かさ": r["確かさ"]}
            self.assertEqual(ledger_state(site, rec), (r["検証状態"], r["検証メモ"]), i)
            self.assertTrue(r["検証メモ"].startswith(MEMO), i)

    def test_individual_amount_failures_are_demoted_in_ledger_and_ranking(self):
        # #229 の暫定表（interim-holds.csv）の3本は、訂正表（primary-source-corrections-v1）で値が直り、標本2を今のサイトの値で
        # 判定し直すと合格になる（衆法-189-20 は制度、閣法-193-61・閣法-196-2 は分野）。公開ランキングでも参考に下げる理由から外れる
        failed = build_public_ranking.verification_failed()
        for i in ("衆法-189-20", "閣法-193-61", "閣法-196-2"):
            self.assertEqual(self.ledger[i]["検証状態"], "抜き取り検証で合格", i)
            self.assertFalse(failed.get(i, "").startswith(SAMPLE2_REASON_PREFIX), i)
        self.assertFalse((L / "interim-holds.csv").exists())

    def test_ranking_and_ledger_agree_on_sample2(self):
        # 公開ランキングの降格は、台帳と同じ判定し直しから決める（台帳が後で作られても、記録の判定欄と向きが違っても食い違わない）
        open_ = {i for i in self.rec if self.ledger[i]["検証状態"] != "抜き取り検証で合格"}
        self.assertEqual(set(sample2_failures()), open_)

    def test_ranking_drops_laws_the_ledger_now_passes(self):
        for i in sample2_failures():
            self.assertNotEqual(self.ledger[i]["検証状態"], "抜き取り検証で合格", i)
        fixed = [r["id"] for r in rows(V2 / "verdicts.csv") if r["判定"] == "不合格" and self.ledger[r["id"]]["検証状態"] == "抜き取り検証で合格"]
        self.assertFalse(set(fixed) & set(sample2_failures()))

    def test_candidates_cover_every_open_failure(self):
        cand = {r["id"] for r in rows(V2 / "correction-candidates.csv")}
        for r in rows(V2 / "resolutions.csv"):
            self.assertEqual(r["決着"].startswith("訂正候補"), r["id"] in cand, r["id"])
        kept = {i for i, r in self.ledger.items() if r["検証状態"] == "抜き取り検証で不合格" and i in self.rec}
        held = {r["id"] for r in rows(V2 / "resolutions.csv") if r["決着"].startswith("独立の確認待ち")}
        self.assertLessEqual(kept, cand | held)


class FetchAndRecord(unittest.TestCase):
    def test_failed_fetch_is_fetched_again(self):
        from scripts.resample_verification import _has_body
        self.assertTrue(_has_body("法律：x\n\n【議案本文】\n第一条 …\n\n【会議録】\n…\n"))
        self.assertFalse(_has_body("法律：x\n\n【議案本文】\n取得できない\n\n\n【会議録】\n…\n"))
        self.assertFalse(_has_body("法律：x\n\n【議案本文】\n\n\n【会議録】\n…\n"))

    def test_compare_does_not_overwrite_the_record(self):
        from scripts.resample_verification import cmd_compare
        before = (V2 / "verdicts.csv").read_bytes()
        self.assertEqual(cmd_compare(), 1)
        self.assertEqual((V2 / "verdicts.csv").read_bytes(), before)


class ConfirmationRecord(unittest.TestCase):
    """独立の確認（2026-11-20）：訂正候補の値は採った値（裁定か確認か2系統）から出し、覆された古い裁定の値を出さない。"""
    def test_value_follows_the_chosen_value_not_the_overturned_ruling(self):
        from scripts.resample_verification import _value
        a = {"経済に効くか": "経済に効く", "経済の理由": "A の理由", "引用": ["A の引用"]}
        ruling = {"値": {"経済に効くか": "経済に効く"},
                  "裁定": [{"項目": "経済に効くか", "値": "制度のみ", "理由": "古い裁定", "引用": "x", "裁定者": "sonnet"}],
                  "確認の記録": [{"項目": "経済に効くか", "値": "経済に効く", "理由": "盲検の理由", "引用": ["y"], "確認者": "opus"}]}
        val, why, _, who = _value(a, a, ruling, "経済に効くか")
        self.assertEqual((val, why), ("経済に効く", "盲検の理由"))
        self.assertIn("opus", who)

    def test_every_confirmation_is_recorded_blind_with_a_quote(self):
        rulings = json.loads((V2 / "rulings.json").read_text(encoding="utf-8"))
        for i, ru in rulings.items():
            for c in ru.get("確認の記録", []):
                self.assertIn("盲検", c["確認者"], i)
                self.assertTrue(c["引用"] and c["出典URL"], i)
            for item in ru.get("確認", []):
                self.assertEqual(ru["値"][item], next(c["値"] for c in ru["確認の記録"] if c["項目"] == item), i)


if __name__ == "__main__":
    unittest.main()