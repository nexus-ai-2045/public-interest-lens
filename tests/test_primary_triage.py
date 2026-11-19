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
            self.assertTrue(r["指示文"].startswith(pt.PROMPT_VERSION))


if __name__ == "__main__":
    unittest.main()
