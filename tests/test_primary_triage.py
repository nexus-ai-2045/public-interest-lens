"""振り分けの当て直し（scripts/primary_triage.py）の規則の検査。AI は呼ばない。"""
import csv
import unittest
from pathlib import Path

from scripts import primary_source_corrections as corrections
from scripts import primary_triage as pt

ROOT = Path(__file__).resolve().parents[1]
SITE = {"類型": "実質改正", "経済に効くか": "経済に効く", "主な産業分野": "金融"}


def reader(**kw):
    base = {"類型": "実質改正", "経済に効くか": "経済に効く", "主な産業分野": "金融", "確信": "高", "類型の理由": "r", "経済の理由": "e",
            "分野の理由": "f", "引用": ["q"], "出典URL": ["u"]}
    return {**base, **kw}


def target(**kw):
    t = {"id": "閣法-1-1", "題名": "t", "到達点": "参考額（産業の付加価値の差）", "サイト_類型": "実質改正", "サイト_経済に効くか": "経済に効く",
         "サイト_台帳の経済に効くか": "", "サイト_分野": "金融", "_set": "pilot"}
    return {**t, **kw}


class NeedsRulingTest(unittest.TestCase):
    def test_agree_and_same_as_site_is_adopted(self):
        self.assertEqual(pt.needs_ruling(SITE, reader(), reader()), {})

    def test_split_undecided_low_and_change_go_to_sonnet(self):
        self.assertEqual(pt.needs_ruling(SITE, reader(類型="新規"), reader()), {"類型": "割れ"})
        self.assertEqual(pt.needs_ruling(SITE, reader(経済に効くか="判定不能"), reader(経済に効くか="判定不能")), {"経済に効くか": "判定不能"})
        self.assertEqual(set(pt.needs_ruling(SITE, reader(確信="低"), reader())), set(pt.ITEMS))
        self.assertEqual(pt.needs_ruling(SITE, reader(主な産業分野="建設"), reader(主な産業分野="建設")), {"主な産業分野": "値の変更"})

    def test_empty_site_value_is_filled_without_ruling(self):
        site = {**SITE, "類型": "", "主な産業分野": ""}
        self.assertEqual(pt.needs_ruling(site, reader(主な産業分野="建設"), reader(主な産業分野="建設")), {})

    def test_field_spelling_variants_agree(self):
        self.assertEqual(pt.needs_ruling({**SITE, "主な産業分野": "医療・福祉"}, reader(主な産業分野="医療"), reader(主な産業分野="医療・福祉")), {})


class DeepReadTest(unittest.TestCase):
    def test_deep_read_law_always_goes_to_sonnet_for_econ(self):
        self.assertEqual(pt.needs_ruling(SITE, reader(), reader(), deep=True), {"経済に効くか": pt.DEEP_REASON})
        self.assertEqual(pt.needs_ruling(SITE, reader(類型="新規"), reader(), deep=True), {"経済に効くか": pt.DEEP_REASON, "類型": "割れ"})

    def test_deep_read_laws_are_measured_targets(self):
        path = pt.set_dir("all") / "targets.csv"
        if not path.exists():
            self.skipTest("all/targets.csv が無い")
        ids = {r["id"] for r in pt.read_csv(path)}
        self.assertLessEqual(set(pt.DEEP_READ), ids)

    def test_decide_without_ruling_stops_for_deep_read(self):
        with self.assertRaises(ValueError):
            pt.decide(target(id="閣法-211-46"), reader(), reader(), None)


class CompareTest(unittest.TestCase):
    def test_compare_lines_up_sample_and_reruns_and_marks_missing(self):
        ids = [{"id": "閣法-1-1", "判定": "不合格"}, {"id": "閣法-9-9", "判定": "割れ"}]
        A = {"閣法-1-1": reader(主な産業分野="建設")}
        B = {"閣法-1-1": reader(主な産業分野="建設")}
        rulings = {"閣法-1-1": {"裁定": [{"項目": "主な産業分野", "値": "建設", "理由": "r"}]}}
        labels = [{"id": "閣法-1-1", "項目": "分野", "直した値": "建設", "判定者": "Sonnet 裁定", "理由": "r", "引用": "q", "出典URL": "u"}]
        rows = pt.compare_rows(ids, [target()], A, B, rulings, labels)
        self.assertEqual(len(rows), 6)
        field = next(r for r in rows if r["id"] == "閣法-1-1" and r["項目"] == "主な産業分野")
        self.assertEqual((field["当て直しの値"], field["系統A"], field["裁定"], field["サイトの値"], field["標本_判定"]), ("建設", "建設", "建設", "金融", "不合格"))
        self.assertTrue(all(r["当て直しの対象"].startswith("対象外") for r in rows if r["id"] == "閣法-9-9"))


class DecideTest(unittest.TestCase):
    def test_rows_use_corrections_vocabulary(self):
        rows = pt.decide(target(), reader(経済に効くか="制度のみ"), reader(経済に効くか="制度のみ"),
                         {"裁定": [{"項目": "経済に効くか", "値": "制度のみ", "理由": "x", "引用": "y", "正しい側": "読み手"}]})
        got = {r["項目"]: r for r in rows}
        self.assertEqual(got["経済に効くか"]["直した値"], corrections.INSTITUTIONAL)
        self.assertIn("Sonnet 裁定（値の変更", got["経済に効くか"]["判定者"])
        self.assertTrue(got["類型"]["判定者"].startswith("Haiku 2系統"))
        self.assertEqual(list(rows[0]), pt.CORR_HEADER)

    def test_missing_ruling_stops(self):
        with self.assertRaises(ValueError):
            pt.decide(target(), reader(類型="新規"), reader(), None)

    def test_whole_economy_is_written_with_full_label(self):
        rows = pt.decide(target(サイト_分野=""), reader(主な産業分野="経済全体（産業を特定できない）"), reader(主な産業分野="経済全体"), None)
        self.assertEqual({r["項目"]: r["直した値"] for r in rows}["分野"], pt.WHOLE_LABEL)

    def test_undecided_kind_has_no_row_but_undecided_econ_does(self):
        ruling = {"裁定": [{"項目": "類型", "値": "判定不能", "理由": "", "引用": ""}, {"項目": "経済に効くか", "値": "判定不能", "理由": "", "引用": ""}]}
        rows = pt.decide(target(), reader(類型="判定不能", 経済に効くか="判定不能"), reader(類型="判定不能", 経済に効くか="判定不能"), ruling)
        self.assertEqual({r["項目"]: r["直した値"] for r in rows}, {"経済に効くか": corrections.UNDECIDED, "分野": "金融"})


class LabelsFileTest(unittest.TestCase):
    """labels.csv は corrections.csv と同じ列で、値が定義の中にある。"""

    def test_labels_schema(self):
        if not pt.LABELS.exists():
            self.skipTest("labels.csv が無い")
        with pt.LABELS.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), pt.CORR_HEADER)
        seen = set()
        for r in rows:
            self.assertNotIn((r["id"], r["項目"]), seen)
            seen.add((r["id"], r["項目"]))
            item = "主な産業分野" if r["項目"] == "分野" else r["項目"]
            self.assertEqual(pt.canonical(item, r["直した値"]), r["直した値"])
            # 組ごとの版（versions.json）と一致する。試走は v1
            group = r["記録"].rstrip("/").rsplit("/", 1)[-1]
            self.assertTrue(r["指示文"].startswith(pt.prompt_version(pt.set_prompt_version(group))), r["指示文"])


class VersionTest(unittest.TestCase):
    def test_pilot_was_read_with_v1_and_v2_adds_only_the_salary_line(self):
        self.assertEqual(pt.set_prompt_version("pilot"), "v1")
        v1 = pt.PROMPTS["v1"].read_text(encoding="utf-8").splitlines()
        v2 = pt.PROMPTS["v2"].read_text(encoding="utf-8").splitlines()
        added = [x for x in v2 if x not in v1]
        self.assertTrue(any("人事院勧告に沿う俸給の定例改定" in x for x in added))
        self.assertFalse(any("人事院勧告に沿う俸給の定例改定" in x for x in v1))

    def test_decide_records_the_reader_version(self):
        rows = pt.decide(target(), reader(), reader(), None, "v2")
        self.assertTrue(all(r["指示文"].startswith(pt.prompt_version("v2")) for r in rows))


class EstimateTest(unittest.TestCase):
    def test_ruling_rate_is_weighted_by_stratum_share(self):
        def t(i, reach, econ=""):
            return target(id=i, 到達点=reach, サイト_台帳の経済に効くか=econ)
        pilot = [t("a", "効果なし（定例）"), t("b", "参考額（x）")]
        everyone = [t(str(i), "参考額（x）") for i in range(9)] + [t("z", "効果なし（定例）")]
        r = pt.ruling_rate(pilot, {"a"}, everyone)
        self.assertEqual(r["素の率"], 0.5)
        self.assertEqual(r["層で重みづけた率"], 0.1)  # 定例 1/10 × 1.0 ＋ 参考額 9/10 × 0

    def test_wilson_interval(self):
        lo, hi = pt.wilson(3, 10)
        self.assertAlmostEqual(lo, 0.108, places=3)
        self.assertAlmostEqual(hi, 0.603, places=3)


if __name__ == "__main__":
    unittest.main()
