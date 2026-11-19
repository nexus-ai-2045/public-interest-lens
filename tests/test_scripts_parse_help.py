"""scripts/ の入口は --help を解釈する（新しく足す入口の歯止め）。

--help を解釈しない入口に --help を渡すと、本番の処理が走って生成物を書き換える（進め方 3章の事前チェック）。
2026-11-19 時点で、直接実行できる scripts/*.py の 57 本が ArgumentParser を持たない。ここに無い入口が増えたら落ちる。
既存の分は直したら一覧から消す（減らすのはよいが、増やさない）。
"""
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# --help を解釈しない既存の入口（2026-11-19）。直したら消す。
KNOWN = {
    "apply_enforcement_egov_browser",
    "apply_enforcement_shugiin_index",
    "apply_enforcement_webfetch",
    "apply_enforcement_year_window",
    "benefit_fetch",
    "build_all_laws_outcomes",
    "build_auto_involvements",
    "build_backing_forces",
    "build_bill_submitters",
    "build_business_ledger",
    "build_cause_axis",
    "build_committee_amend_involvements",
    "build_covid_benefit",
    "build_evaluation_ledger",
    "build_law_outcomes_view",
    "build_law_overviews",
    "build_laws_catalog",
    "build_macro_amounts",
    "build_opposing_votes",
    "build_org_ledger",
    "build_provisional",
    "build_public_pledges",
    "build_public_unenacted",
    "build_public_votes",
    "build_speech_facts",
    "build_submitter_points",
    "build_support_base",
    "build_tax_impact",
    "build_tax_ledger",
    "build_three_columns",
    "build_treaty_outcomes",
    "build_unenacted_bills_scale",
    "build_unenacted_direction",
    "build_vote_parties",
    "check_error_types",
    "check_evaluation_logic",
    "check_evidence_ledger",
    "compare_verification",
    "dstat_xl",
    "estimate_field_expansion",
    "eval_transport",
    "fetch_affiliation_at_time",
    "fetch_courts_bankruptcy",
    "fetch_dic_assistance",
    "fetch_fsa_kasikin",
    "fetch_kokusen_pionet",
    "fetch_law_source",
    "fetch_sesc_actions",
    "loop_status",
    "merge_mechanism_labels",
    "prepare_oecd_stan",
    "rebuild_public",
    "report_verification",
    "resolve_sample_failures",
    "roadmap_check",
    "strip_commit_trace",
    "triage_v2_line2",
}


def entrypoints_without_parser() -> set[str]:
    out = set()
    for path in SCRIPTS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "__main__" in text and "ArgumentParser" not in text:
            out.add(path.stem)
    return out


class ParseHelpTest(unittest.TestCase):
    def test_no_new_entrypoint_ignores_help(self):
        new = sorted(entrypoints_without_parser() - KNOWN)
        self.assertEqual(new, [], "--help を解釈しない入口が増えた。argparse を使う")

    def test_known_list_only_shrinks(self):
        fixed = sorted(KNOWN - entrypoints_without_parser())
        self.assertEqual(fixed, [], "直った（または消えた）入口が一覧に残っている。KNOWN から消す")


if __name__ == "__main__":
    unittest.main()
