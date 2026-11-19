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
            ("docs/配り方.md", "（冒頭）", "", ("群の額の本数割り", "確かさ「低」の配分")),
        })
        self.assertFalse(dc.verdict(result, strict=False)[0])

    def test_saying_the_method_is_not_used_is_not_a_hit(self):
        for text in ["群の差は法律の本数で割らない。「低」は額と印を出すが、配らない。", "群の額は本数で割りません。「低」は配りません。",
                     "「低」と「参考」は順位にも配分にも使わない。", "Shapley 値による配分は撤回した。"]:
            with self.subTest(text=text):
                self.assertEqual(dc.withdrawn_hits(text), [])

    def test_the_wordings_the_documents_actually_use_are_hits(self):
        for text in ["段階1の額は確かさ「低」として印を付け、議員への配分にも使う。", "配るのは確かさ「高」「中」「低」の法律（印つき）。",
                     "今の実装は確かさ「低」の額も議員に配る（設計決定0014 決定6）。"]:
            with self.subTest(text=text):
                self.assertEqual(dc.withdrawn_hits(text), ["確かさ「低」の配分"])
        self.assertEqual(dc.withdrawn_hits("本数で等分し「同じ観測を共有」の印を付ける。"), ["群の額の本数割り"])

    def test_a_pointer_elsewhere_in_the_file_does_not_clear_another_section(self):
        doc = "# 仕様の版\n\n## 決まり\n\n観測の額を本数で割る。\n\n## 変更の記録\n\n| v3 | 点数設計 v2.1 を採用 |\n"
        result = self.run_tree(**{"docs/adr/0013-spec.md": doc})
        self.assertEqual([(s["file"], s["section"]) for s in result["withdrawn"]["stale"]], [("docs/adr/0013-spec.md", "決まり")])

    def test_a_replacement_note_at_the_top_covers_the_whole_decision(self):
        doc = "# 設計決定0014\n\n> **一部を置き換え済み**：設計決定0027 が置き換えた。\n\n## 決定\n\nShapley 値の賛成1票分を配る。\n"
        result = self.run_tree(**{"docs/adr/0014-allocation.md": doc})
        self.assertEqual(result["withdrawn"]["stale"], [])
        # 計算式は節ごとに版と状態を持つので、冒頭の注記では済まない
        formula = "# 計算式\n\n移行中。設計決定0027 が置き換える。\n\n## 点数設計 v2.1\n\n- " + FIXED + "\n\n## 成立への寄与\n\nShapley 値で配る。\n"
        result = self.run_tree(**{"docs/計算式.md": formula})
        self.assertEqual([s["section"] for s in result["withdrawn"]["stale"]], ["成立への寄与"])

    def test_measured_results_and_past_values_are_not_claims(self):
        def claims(text):
            return [(c["key"], c["value"]) for c in dc.find_claims(text)]

        self.assertEqual(claims("今回のバックテストの的中率 62%（合格線 80% に届かない）"), [("hitRateFloor", 0.8)])
        self.assertEqual(claims("以前の合格線 95%（v5 まで）。固定済みの測定は当時の合格線 95% のまま残す。"), [])
        self.assertEqual(claims("確かさの下限を高くする案は採らない"), [])
        self.assertEqual(claims("| 確かさの下限 | 中以上 |"), [("certaintyFloor", "中")])

    def test_latex_bounds_are_read_in_the_usual_spellings(self):
        def values(text):
            return [c["value"] for c in dc.find_claims(text)]

        for text in [r"上位3本の占有率 $s \le 0.5$", r"上位3本の占有率 $s \leq 0.5$", r"上位3本の占有率 $s \le 50\%$", "上位3本の占有率 s ≤ 50%",
                     r"'\\frac{\\sum_{i\\in\\text{上位3本}} x}{y} \\le 0.5'"]:
            with self.subTest(text=text):
                self.assertEqual(values(text), [0.5])
        self.assertEqual(values(r"|\mathcal L_p| \geq 5"), [5.0])

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
        self.assertIn("議員：", status[1]["now"])
        self.assertIn("台帳に無い 1", status[1]["now"])
        self.assertEqual(status[2]["state"], "未達")
        self.assertIn("計 2 本", status[2]["now"])
        self.assertEqual(status[3]["state"], "達成")  # 不合格は参考に下げてあり、不合格のままは0
        self.assertIn("参考に下げた 1 本、読み直しで合格に訂正 0 本、不合格のまま 0 本", status[3]["now"])
        self.assertEqual(status[4]["state"], "未達")
        self.assertIn("CI と同じ検査", status[4]["now"])

    def test_laws_alone_do_not_make_the_ledger_condition_done(self):
        # 進め方 5章-1 は法律と議員の全件。議員の側は測る台帳が無いので「達成」とは言わない
        d = "data/derived/"
        status = self.status({d + "all-laws-v1/outcomes.csv": "id\nA\n", d + "evaluation-ledger-v1/ledger.csv": LEDGER_HEAD + "A,測定できない,,,未検証\n"})
        self.assertEqual(status[1]["state"], "一部達成")

    def test_members_are_measured_against_the_exposure_output(self):
        # 進め方 5章-1 の議員：人物台帳の全員が、曝露ランキングに「点あり」か「点なし＋理由」で1回ずつ載る
        d = "data/derived/"
        laws = {d + "all-laws-v1/outcomes.csv": "id\nA\n", d + "evaluation-ledger-v1/ledger.csv": LEDGER_HEAD + "A,測定できない,,,未検証\n"}
        persons = {d + "person-ids/persons.csv": "人物ID,氏名\nP1,a\nP2,b\n"}
        cov = {"ledger": 2, "ranked": 1, "unrankedWithAmount": 0, "noInvolvement": 1, "outsideLedger": 1}
        people = [{"actorId": "P1", "tier": 1, "unrankedReason": ""}, {"actorId": "P2", "tier": None, "unrankedReason": "関与の記録が無い"},
                  {"actorId": "当時だけの閣僚", "tier": 1, "unrankedReason": ""}]
        out = "data/derived/exposure-v1/exposure-ranking.json"
        status = self.status(laws | persons | {out: json.dumps({"people": people, "coverage": cov})})
        self.assertEqual(status[1]["state"], "達成")
        self.assertIn("人物台帳 2 人中、曝露ランキングに載る 2 人（点あり 1、点なし＋理由 1、載っていない 0、2回以上 0）", status[1]["now"])
        # 理由の無い点なし・載っていない人・2回・台帳の空行は、どれも達成にしない
        for broken_people, broken_persons in [
            ([people[0], {"actorId": "P2", "tier": None, "unrankedReason": ""}], persons),
            ([people[0]], persons),
            ([people[0], people[1], people[1]], persons),
            (people, {d + "person-ids/persons.csv": "人物ID,氏名\nP1,a\n,\nP2,b\n"}),
        ]:
            status = self.status(laws | broken_persons | {out: json.dumps({"people": broken_people, "coverage": cov})})
            self.assertEqual(status[1]["state"], "一部達成", broken_people)
        status = self.status(laws | persons)
        self.assertIn("曝露ランキングの出力", status[1]["now"])
        self.assertEqual(status[1]["state"], "一部達成")

    def test_empty_or_broken_inputs_are_not_measured_and_do_not_crash(self):
        d = "data/derived/"
        status = self.status({
            d + "all-laws-v1/outcomes.csv": "id\nA\n",
            d + "evaluation-ledger-v1/ledger.csv": "id,到達点\nA,測定できない\n",  # 額の列が無い
            d + "evaluation-ledger-v1/sample.csv": "層,id,題名\n",
            d + "evaluation-ledger-v1/sample-verdicts.csv": "id,判定,食い違い\n",
            ".local/release-check/2026-11-19.json": "{",
        }, logic_counts=dict)
        self.assertEqual({no: c["state"] for no, c in status.items()}, {1: "未実行", 2: "未実行", 3: "未実行", 4: "未実行"})
        self.assertIn("KeyError", status[1]["now"])
        status = self.status({".local/release-check/2026-11-19.json": "[]"})
        self.assertEqual(status[4]["state"], "未実行")

    def test_every_sampled_law_needs_its_own_verdict(self):
        d = "data/derived/evaluation-ledger-v1/"
        status = self.status({
            d + "ledger.csv": LEDGER_HEAD + "A,測定できない,,,抜き取り検証で合格\nB,測定できない,,,未検証\nC,測定できない,,,未検証\n",
            d + "sample.csv": "層,id,題名\nx,A,a\nx,B,b\nx,C,c\n",
            d + "sample-verdicts.csv": "id,判定,食い違い\nA,不合格,向き\nA,合格,\nB,,\n",  # A はやり直しで2行、B は空欄、C は行が無い
        })
        self.assertEqual(status[3]["state"], "未達")
        self.assertIn("判定済み 1 本（合格 1、不合格 0）、判定なし 2 本", status[3]["now"])

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
