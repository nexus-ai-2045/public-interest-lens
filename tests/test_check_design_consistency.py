"""設計の整合の検査（scripts/check_design_consistency.py）の検査。小さな作業ツリーを作って、当たる・外れるを確かめる。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_design_consistency as dc

CONSTANTS = """export const SCORING_CONSTANTS = Object.freeze({
  hitRateFloor: 0.8,
  minContributingLaws: 5,
  topThreeShareCap: 0.5,
  certaintyFloor: '中',
} as const);
"""
FIXED = "寄与法律数の下限 5、上位3本の占有率の上限 50%、確かさの下限「中」。的中率の合格線 80%。"
SPEC = f"""export const STANDARD_METHODS = [
  {{ name: 'シャープレイ＝シュービック投票力指数', use: '点数設計 v2.1 で撤回' }},
];
export const SECTIONS = [
  {{
    id: 'score-design',
    title: '点数設計 v2.1',
    status: '案',
    rules: ['{FIXED}'],
  }},
  {{
    id: 'allocation-v0',
    title: '成立への寄与',
    status: '採用',
    lead: '【置き換え予定：点数設計 v2.1（設計決定0027）】Shapley 値で配る。',
  }},
];
"""
FORMULA = f"""# 計算式

## 点数設計 v2.1

- {FIXED}

## 成立への寄与

【置き換え予定：点数設計 v2.1（設計決定0027）】Shapley 値で配る。
"""
ADR = """# 設計決定0027

| 定数 | 値 |
|---|---|
| 的中率の合格線 | 80%（2026-10-29 の 95% から変更） |
| 寄与法律数の下限 | 5 |
| 上位3本の占有率の上限 | 50% |
| 確かさの下限 | 中以上 |

Shapley 値による配分は撤回。確かさ「低」も印つきで配る、は置き換える。
"""
FILES = {
    "app/src/scoring-constants.ts": CONSTANTS,
    "app/src/method-spec.ts": SPEC,
    "docs/計算式.md": FORMULA,
    "docs/adr/0027-score-design-v2-1.md": ADR,
    "docs/評価方法設計書.md": "版：v1.1（的中率の合格線を 95% から 80% に）。\n\n## 5. 精度の測り方（合格線は的中率80%）\n\n区間（目標の確からしさ95%）。**80%以上**を合格とする。\n",
    "docs/ロードマップ.md": "- 精度は、的中率80%以上を合格線として固定する。\n",
    "docs/影響度ランキング.md": "- 精度の測り方（設計書5章、合格線は的中率80%）。\n",
    "scripts/backtest_transplant.py": "TARGET = 0.8   # 合格の線\n",
    "scripts/backtest.py": "import backtest_transplant as tr\nTARGET = tr.TARGET   # 借りる\n",
}


def make_tree(tmp: str, **override: str | None) -> Path:
    root = Path(tmp)
    for name, text in (FILES | override).items():
        if text is None:
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class ConsistencyTest(unittest.TestCase):
    def run_tree(self, **override):
        with tempfile.TemporaryDirectory() as tmp:
            return dc.run(make_tree(tmp, **override))

    def bad_constants(self, result):
        return [(r["file"], r["key"], r["status"]) for r in result["constant_rows"] if r["status"] != "一致"]

    def test_a_consistent_tree_passes(self):
        result = self.run_tree()
        self.assertEqual(self.bad_constants(result), [])
        self.assertEqual(result["withdrawn"]["stale"], [])
        self.assertEqual(dc.verdict(result, strict=False), (True, []))

    def test_history_of_a_change_is_not_read_as_the_current_value(self):
        # 「95% から 80% に」「目標の確からしさ95%」は合格線の主張ではない
        result = self.run_tree()
        found = {r["found"] for r in result["constant_rows"] if r["file"] in ("docs/評価方法設計書.md", "docs/adr/0027-score-design-v2-1.md") and r["key"] == "hitRateFloor"}
        self.assertEqual(found, {"80%"})

    def test_a_stale_pass_line_in_a_document_fails(self):
        result = self.run_tree(**{"docs/ロードマップ.md": "- 精度は95%以上を目標とする。\n"})
        self.assertEqual(self.bad_constants(result), [("docs/ロードマップ.md", "hitRateFloor", "不一致")])
        self.assertFalse(dc.verdict(result, strict=False)[0])

    def test_each_constant_is_compared(self):
        for old, new, key in [("下限 5、", "下限 3、", "minContributingLaws"), ("上限 50%", "上限 60%", "topThreeShareCap"),
                              ("下限「中」", "下限「低」", "certaintyFloor"), ("合格線 80%", "合格線 95%", "hitRateFloor")]:
            with self.subTest(key=key):
                result = self.run_tree(**{"docs/計算式.md": FORMULA.replace(old, new)})
                self.assertEqual(self.bad_constants(result), [("docs/計算式.md", key, "不一致")])

    def test_a_missing_statement_fails(self):
        result = self.run_tree(**{"docs/影響度ランキング.md": "合格線の話は無い。\n", "docs/adr/0027-score-design-v2-1.md": None})
        self.assertEqual(self.bad_constants(result), [("docs/adr/0027-*.md", "", "ファイルなし"), ("docs/影響度ランキング.md", "hitRateFloor", "記載なし")])

    def test_backtest_target_must_match_and_live_in_one_place(self):
        result = self.run_tree(**{"scripts/backtest_transplant.py": "TARGET = 0.95\n"})
        self.assertEqual(self.bad_constants(result), [("scripts/backtest_transplant.py", "hitRateFloor", "不一致")])
        result = self.run_tree(**{"scripts/backtest.py": "TARGET = 0.8\n"})
        self.assertEqual(self.bad_constants(result), [("scripts/backtest*.py", "hitRateFloor", "不一致")])

    def test_the_canonical_file_must_be_readable(self):
        with self.assertRaises(SystemExit):
            self.run_tree(**{"app/src/scoring-constants.ts": "export const SCORING_CONSTANTS = {};\n"})

    def test_replace_marks_are_listed_and_fail_only_in_strict(self):
        result = self.run_tree()
        self.assertEqual([(m["file"], m["section"]) for m in result["replace_marks"]],
                         [("docs/計算式.md", "成立への寄与"), ("app/src/method-spec.ts", "allocation-v0（成立への寄与）")])
        self.assertTrue(dc.verdict(result, strict=False)[0])
        ok, reasons = dc.verdict(result, strict=True)
        self.assertFalse(ok)
        self.assertIn("② 置き換え予定の印 2 件（--strict）", reasons)

    def test_a_withdrawn_method_left_as_adopted_fails(self):
        spec = SPEC.replace("【置き換え予定：点数設計 v2.1（設計決定0027）】", "")
        result = self.run_tree(**{"app/src/method-spec.ts": spec, "docs/配り方.md": "確かさ「低」も印つきで議員に配る。群の額は本数で割る。\n"})
        stale = {(s["file"], s["section"], s["status"], tuple(s["methods"])) for s in result["withdrawn"]["stale"]}
        self.assertEqual(stale, {
            ("app/src/method-spec.ts", "allocation-v0（成立への寄与）", "採用", ("Shapley 値による配分",)),
            ("docs/配り方.md", "（ファイル全体）", "", ("群の額の本数割り", "確かさ「低」の配分")),
        })
        self.assertFalse(dc.verdict(result, strict=False)[0])

    def test_saying_the_method_is_not_used_is_not_a_hit(self):
        result = self.run_tree(**{"docs/配り方.md": "群の差は法律の本数で割らない。「低」は額と印を出すが、配らない。\n"})
        self.assertEqual(result["withdrawn"]["stale"], [])

    def test_code_residue_fails_only_in_strict(self):
        result = self.run_tree(**{"app/src/causal-allocation.ts": "export function shapley() {}\n", "app/src/causal-allocation.test.ts": "shapley();\n"})
        self.assertEqual([r["file"] for r in result["withdrawn"]["residue"]], ["app/src/causal-allocation.ts"])
        self.assertTrue(dc.verdict(result, strict=False)[0])
        self.assertFalse(dc.verdict(result, strict=True)[0])


LEDGER_HEAD = "id,到達点,額（円）,国の収支（億円）,検証状態\n"


class CompletionTest(unittest.TestCase):
    def status(self, files: dict[str, str], logic_counts=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp, **files)
            return {c["no"]: c for c in dc.completion_status(root, logic_counts)}

    def test_nothing_measured_is_never_reported_as_done(self):
        status = self.status({})
        self.assertEqual({c["state"] for c in status.values()}, {"未実行"})

    def test_ledger_sampling_logic_and_release_record(self):
        d = "data/derived/"
        status = self.status({
            d + "all-laws-v1/outcomes.csv": "id\nA\nB\nC\n",
            d + "evaluation-ledger-v1/ledger.csv": LEDGER_HEAD + "A,額（個別の因果の鎖）,100,,抜き取り検証で合格\nB,測定できない,,,参考に下げた\n",
            d + "evaluation-ledger-v1/sample.csv": "層,id,題名\nx,A,a\nx,B,b\n",
            d + "evaluation-ledger-v1/sample-verdicts.csv": "id,判定,食い違い\nA,合格,\nB,不合格,向き\n",
            ".local/release-check/2026-11-19.json": json.dumps([{"step": "事前チェック", "ok": True}, {"step": "CI と同じ検査", "ok": False}]),
        }, logic_counts=lambda: {"L1": 0, "L2": 2})
        self.assertEqual(status[1]["state"], "未達")  # C が台帳に無い
        self.assertIn("台帳に無い 1", status[1]["now"])
        self.assertEqual(status[2]["state"], "未達")
        self.assertIn("計 2 本", status[2]["now"])
        self.assertEqual(status[3]["state"], "達成")  # 不合格は参考に下げてあり、不合格のままは0
        self.assertIn("参考に下げた 1 本、不合格のまま 0 本", status[3]["now"])
        self.assertEqual(status[4]["state"], "未達")
        self.assertIn("CI と同じ検査", status[4]["now"])

    def test_completion_does_not_change_the_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = dc.run(make_tree(tmp))
        self.assertTrue(all(c["state"] == "未実行" for c in result["completion"]))
        self.assertTrue(dc.verdict(result, strict=False)[0])
        self.assertIn("| 4 | 公開前検査", dc.render(result, strict=False))


class RepositoryTest(unittest.TestCase):
    """今のリポジトリで、正本が読めて、バックテストの合格線が正本と一致する（文書の一致は docs の移行後に CI へ足す）。"""

    def test_constants_and_backtest_agree(self):
        constants = dc.load_constants(ROOT)
        self.assertEqual(set(constants), set(dc.KEYS))
        rows = dc.check_backtest_targets(ROOT, float(constants["hitRateFloor"]))
        self.assertTrue(rows)
        self.assertEqual([r for r in rows if r["status"] != "一致"], [])


if __name__ == "__main__":
    unittest.main()
