"""抜き取り検証で不合格のまま残った法律の決着（sample-resolutions.csv）の検査。

決着は一次資料の読み直しの記録から機械的に決める。手で書き換えた行、根拠の無い行、記録と合わない行があれば落ちる。
"""
import csv
import json
import unittest
from pathlib import Path
from typing import ClassVar

from scripts.build_evaluation_ledger import (
    RESOLVED_DEMOTED,
    RESOLVED_PASS,
    site_key,
    verify_state,
)
from scripts.evaluation_rules import STATE_DEMOTED, STATE_FAILED
from scripts.resolve_sample_failures import (
    HEADER,
    RV,
    SAMPLED_AT,
    reading_allowed,
    resolve,
    targets,
)

L = Path(__file__).resolve().parents[1] / "data" / "derived" / "evaluation-ledger-v1"


def rows(name: str) -> list[dict]:
    with (L / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def site(**kw) -> dict:
    base = {"id": "x", "類型": "実質改正", "分類": "評価対象", "到達点": "保留", "経済に効くか": "", "国の収支（億円）": "", "額（円）": ""}
    return {**base, **kw}


def line(kind: str, econ: str) -> dict:
    return {"類型": kind, "経済に効くか": econ, "出典URL": ["https://example.invalid/a"]}


class ResolveRuleTest(unittest.TestCase):
    def test_site_kind_error_is_demoted_not_passed(self):
        r = resolve(site(類型="定型改正"), line("実質改正", "経済に効く"), line("実質改正", "経済に効く"), None, "類型：サイト定型改正／独立判定実質改正")
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)
        self.assertIn("サイト「定型改正」、読み直し「実質改正」", r["理由"])

    def test_institutional_law_held_as_target_is_demoted(self):
        r = resolve(site(), line("実質改正", "制度のみ"), line("実質改正", "制度のみ"), None, "分類：サイト対象／独立判定制度のみ")
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)

    def test_split_without_ruling_is_undecided_and_demoted(self):
        r = resolve(site(), line("実質改正", "制度のみ"), line("実質改正", "経済に効く"), None, "")
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)
        self.assertIn("決められない", r["理由"])

    def test_ruling_decides_a_split(self):
        ruling = {"経済に効くか": {"値": "経済に効く", "理由": "給付の対象が広がる"}}
        r = resolve(site(), line("実質改正", "制度のみ"), line("実質改正", "経済に効く"), ruling, "制度のみ。評価対象は誤り")
        self.assertEqual(r["決着"], RESOLVED_PASS)

    def test_excluded_law_without_site_econ_record_is_demoted(self):
        s = site(分類="評価対象外", 到達点="測定できない", 経済に効くか="判定不能（Sonnet）")
        r = resolve(s, line("実質改正", "経済に効く"), line("実質改正", "経済に効く"), None, "分類：サイト対象外／独立判定経済に効く")
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)


    def test_site_econ_record_against_institutional_reading_is_an_error(self):
        """読み直しが制度のみなら、サイトが自分で「経済に効く」と記録した対象外の法律もサイトの誤り（どちらの向きでも同じ読み方）。"""
        s = site(分類="評価対象外", 到達点="保留", 経済に効くか="経済に効く（一致）")
        r = resolve(s, line("実質改正", "制度のみ"), line("実質改正", "制度のみ"), None, "", reading_ok=True)
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)

    def test_empty_site_kind_is_an_error(self):
        r = resolve(site(類型=""), line("実質改正", "経済に効く"), line("実質改正", "経済に効く"), None, "")
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)

    def test_state_budget_reach_is_not_read_as_holding(self):
        s = site(分類="評価対象外", 到達点="国の収支の額（GDP とは別欄）", 経済に効くか="経済に効く（一致）")
        r = resolve(s, line("実質改正", "経済に効く"), line("実質改正", "経済に効く"), None, "", reading_ok=True)
        self.assertEqual(r["決着"], RESOLVED_DEMOTED)

    def test_reading_ruling_applies_only_to_named_laws(self):
        rulings = {"照合の読み方": {"裁定": "合格に訂正してよい", "3本それぞれの扱い": {"a": "合格に訂正。理由", "b": "不合格のまま"}}}
        self.assertEqual(reading_allowed(rulings), {"a"})
        self.assertEqual(reading_allowed({"照合の読み方": {"裁定": "不合格のままにすべき", "3本それぞれの扱い": {"a": "合格に訂正"}}}), set())

    def test_excluded_law_with_site_econ_record_passes_only_with_a_ruling(self):
        s = site(分類="評価対象外", 到達点="保留", 経済に効くか="経済に効く（一致）")
        args = (s, line("実質改正", "経済に効く"), line("実質改正", "経済に効く"), None, "分類：サイト対象外／独立判定経済に効く")
        self.assertEqual(resolve(*args)["決着"], RESOLVED_DEMOTED)
        self.assertEqual(resolve(*args, reading_ok=True)["決着"], RESOLVED_PASS)


class ResolutionDataTest(unittest.TestCase):
    def setUp(self):
        self.ledger = {r["id"]: r for r in rows("ledger.csv")}
        self.verdicts = rows("sample-verdicts.csv")
        self.res = rows("sample-resolutions.csv")

    def test_every_remaining_failure_has_exactly_one_resolution(self):
        self.assertEqual(sorted(r["id"] for r in self.res), targets(self.ledger, self.verdicts))

    def test_rows_carry_reason_reference_and_sources(self):
        for r in self.res:
            self.assertEqual(list(r), HEADER)
            self.assertIn(r["決着"], (RESOLVED_PASS, RESOLVED_DEMOTED), r["id"])
            for k in ("原因の区分", "理由", "参考値"):
                self.assertTrue(r[k].strip(), f"{r['id']} {k}")
            self.assertTrue(r["根拠URL"].startswith("https://"), r["id"])

    def test_rows_match_the_recorded_readings(self):
        """決着の表は、読み直しの記録から作り直したものと同じ（手で書き換えていない）。"""
        a = {x["id"]: x for x in json.loads((RV / "lineA.json").read_text(encoding="utf-8"))}
        b = {x["id"]: x for x in json.loads((RV / "lineB.json").read_text(encoding="utf-8"))}
        rulings = json.loads((RV / "rulings.json").read_text(encoding="utf-8"))
        memo = {v["id"]: v["食い違い"] for v in self.verdicts}
        allowed = reading_allowed(rulings)
        sampled = {r["id"]: r["到達点"] for r in rows(SAMPLED_AT.relative_to(L).as_posix())}
        for r in self.res:
            i = r["id"]
            self.assertEqual(r, resolve(self.ledger[i], a[i], b[i], rulings.get(i), memo[i], i in allowed, sampled.get(i, "")), i)

    def test_resolutions_were_made_against_todays_site_values(self):
        for r in self.res:
            self.assertEqual(r["判定時のサイトの値"], site_key(self.ledger[r["id"]]), r["id"])

    def test_ledger_has_no_remaining_failure(self):
        sampled = {v["id"] for v in self.verdicts}
        left = [i for i in sampled if self.ledger[i]["検証状態"] == STATE_FAILED]
        self.assertEqual(left, [])

    def test_first_round_verdicts_are_kept(self):
        """初回の判定表は書き換えない（公開ランキングの降格がこの表を引く）。"""
        self.assertEqual(sum(v["判定"] == "不合格" for v in self.verdicts), 78)
        self.assertEqual(len(self.verdicts), 118)


class LedgerStateTest(unittest.TestCase):
    V: ClassVar[dict] = {"x": {"判定": "不合格", "食い違い": "類型：…"}}

    def test_no_amount_failure_stays_failed_without_resolution(self):
        self.assertEqual(verify_state("x", "", self.V, "保留", "")[0], STATE_FAILED)

    def test_resolution_moves_state_and_keeps_reason(self):
        for word, state in ((RESOLVED_PASS, "抜き取り検証で合格"), (RESOLVED_DEMOTED, STATE_DEMOTED)):
            got, memo = verify_state("x", "", self.V, "保留", "", {"x": {"決着": word, "理由": "わけ", "判定時のサイトの値": "k"}}, "k")
            self.assertEqual(got, state)
            self.assertIn("わけ", memo)

    def test_resolution_never_overrides_a_pass_or_an_automatic_demotion(self):
        res = {"x": {"決着": RESOLVED_PASS, "理由": "わけ", "判定時のサイトの値": "k"}}
        self.assertEqual(verify_state("x", "", self.V, "参考額（産業の付加価値の差）", "参考", res)[0], STATE_DEMOTED)


    def test_stale_resolution_is_not_used(self):
        """決着の後にサイトの値が変わったら、決着を使わず不合格に戻す。"""
        res = {"x": {"決着": RESOLVED_PASS, "理由": "わけ", "判定時のサイトの値": "古い値"}}
        self.assertEqual(verify_state("x", "", self.V, "保留", "", res, "新しい値")[0], STATE_FAILED)


if __name__ == "__main__":
    unittest.main()
