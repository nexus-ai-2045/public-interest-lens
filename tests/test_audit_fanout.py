"""全件検査（scripts/audit_fanout.py）：plan→疑似の子返却→collect の往復、欠け・形式違反・重複・割れの検出、較正、基準の歯止め。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import audit_fanout as af


def ledger_row(i, title="製造業振興法案", amount="1000", **kw):
    row = {"id": f"閣法-1-{i}", "題名": title, "分野": "製造", "額（円）": amount, "付加価値の由来": "全体指標の参考の額（産業の付加価値の差）",
           "検証状態": "未検証", "到達点": "参考額（産業の付加価値の差）", "確かさ": "参考", "分類": "評価対象", "経済に効くか": ""}
    row.update(kw)
    return row


SRC = "狙い：製造業の振興のため、産業全体の設備投資を促す"
SUB = {"全体": ("いいえ", "はい"), "一部": ("はい", "いいえ"), "不明": ("不明", "不明")}
SUBC = {"評価対象": ("はい", "いいえ"), "制度整備": ("いいえ", "はい"), "不明": ("不明", "不明")}


def child(lid, version, rng="全体", cls="評価対象", **kw):
    rec = {"id": lid, "範囲": rng, "分類": cls,
           "小問": dict(zip(("範囲1", "範囲2"), SUB[rng]), **dict(zip(("分類1", "分類2"), SUBC[cls]))),
           "根拠引用": [{"出典": "overviews", "引用": "製造業の振興のため"}], "仮定": [{"内容": "題名の語から産業全体と推定", "強さ": "中", "影響": "一部なら不合格"}],
           "使った前提": "題名から推定", "読んだ出典": ["overviews.csv"], "計算や比較": "産業の差と比べた",
           "判定理由": "対象は産業全体", "確認できなかった点": "なし", "探した場所": "なし", "確信度": "中", "model": "haiku-test", "prompt_version": version}
    rec.update(kw)
    return rec


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.ledger = [ledger_row(i) for i in range(1, 7)] + [ledger_row(7, amount="55"), ledger_row(8, title="特例法案", amount="2000"), ledger_row(9, title="特定法案", amount="2000")]
        self.macro = [{"id": r["id"], "産業": "_T" if "特" in r["題名"] else "C"} for r in self.ledger]
        over = [{"id": r["id"], "何をする": "", "狙い": "製造業の振興のため、産業全体の設備投資を促す", "反対側の心配": "", "材料": "提案理由"} for r in self.ledger]
        self.targets = af.build_targets(self.ledger, self.macro, overviews=over)
        self.manifest = af.plan(self.out, self.targets, "full", size=3)
        self.version = self.manifest["prompt_version"]

    def tearDown(self):
        self.tmp.cleanup()

    def answer(self, stage, system, fn):
        for b in self.manifest["bundles"]:
            if b["stage"] == stage and b["system"] == system:
                af.write_jsonl(self.out / b["return"], [fn(i) for i in b["ids"]])

    def state(self):
        ret = af.read_returns(self.out, self.manifest, {t['id']: t['資料'] for t in self.targets})
        return ret, af.law_records(self.manifest, self.targets, ret["judged"])


class PlanTest(Base):
    def test_targets_are_shared_amount_only(self):
        ids = {t["id"] for t in self.targets}
        self.assertNotIn("閣法-1-7", ids)  # 額が1本だけ
        self.assertEqual(len(ids), 8)

    def test_narrow_title_is_decided_by_machine_and_not_sent_to_model(self):
        asked = {i for b in self.manifest["bundles"] for i in b["ids"]}
        self.assertEqual(self.manifest["machine_decided"], 2)
        self.assertFalse({"閣法-1-8", "閣法-1-9"} & asked)

    def test_a_and_b_get_same_ids_and_versioned_prompt(self):
        by = {}
        for b in self.manifest["bundles"]:
            by.setdefault(b["bundle"][:4], {})[b["system"]] = set(b["ids"])
            self.assertIn(self.version, (self.out / b["prompt"]).read_text(encoding="utf-8"))
        self.assertTrue(all(v["A"] == v["B"] for v in by.values()))
        self.assertEqual(len(by), 2)


class CollectTest(Base):
    def test_round_trip_all_agree(self):
        for s in "AB":
            self.answer("haiku", s, lambda i: child(i, self.version))
        ret, recs = self.state()
        self.assertFalse(ret["unreturned"] or ret["missing"] or ret["violations"] or ret["duplicates"])
        by = {r["id"]: r for r in recs}
        self.assertEqual(by["閣法-1-1"]["判定"], af.PASS)
        self.assertEqual(by["閣法-1-8"]["判定"], af.FAIL)  # 機械判定
        self.assertEqual(by["閣法-1-1"]["段"]["範囲"], "haiku一致")
        self.assertEqual(by["閣法-1-1"]["使ったモデル"], ["haiku-test"])
        self.assertIn("filesHash", by["閣法-1-1"]["プロンプト"])
        total = af.build_table(recs)[2]
        self.assertEqual((total["検査数"], total["機械判定"], total["合格"], total["不合格"], total["未決"]), (8, 2, 6, 2, 0))

    def test_unreturned_bundle_listed(self):
        self.answer("haiku", "A", lambda i: child(i, self.version))
        ret, recs = self.state()
        self.assertEqual(len(ret["unreturned"]), 2)  # B の2束
        self.assertEqual(af.build_table(recs)[2]["未決"], 6)

    def test_missing_line_detected(self):
        b = next(b for b in self.manifest["bundles"] if b["system"] == "A")
        af.write_jsonl(self.out / b["return"], [child(i, self.version) for i in b["ids"][:-1]])
        ret, _ = self.state()
        self.assertEqual([m["id"] for m in ret["missing"]], [b["ids"][-1]])

    def test_format_violations_are_rejected(self):
        b = next(b for b in self.manifest["bundles"] if b["system"] == "A")
        i0, i1, i2 = b["ids"]
        bad = [child(i0, self.version, 範囲="どちらでもない"),
               {k: v for k, v in child(i1, self.version).items() if k != "判定理由"},
               child(i2, "古い版"),
               child(i2, self.version, 確認できなかった点="なし", rng="不明"),
               child(i0, self.version, 判定理由=" ")]
        af.write_jsonl(self.out / b["return"], bad)
        ret, _ = self.state()
        self.assertEqual(len(ret["violations"]), 5)
        self.assertEqual(len(ret["missing"]), 3)  # 弾いた行は未回収扱い

    def test_duplicate_detected(self):
        b = next(b for b in self.manifest["bundles"] if b["system"] == "A")
        af.write_jsonl(self.out / b["return"], [child(i, self.version) for i in b["ids"]] + [child(b["ids"][0], self.version)])
        ret, _ = self.state()
        self.assertEqual(len(ret["duplicates"]), 1)


class DisputeTest(Base):
    def split(self, bad):
        self.answer("haiku", "A", lambda i: child(i, self.version))
        self.answer("haiku", "B", lambda i: child(i, self.version, rng="一部") if i == bad else child(i, self.version))

    def test_split_goes_to_sonnet_then_opus(self):
        bad = "閣法-1-2"
        self.split(bad)
        ret, recs = self.state()
        self.assertEqual(af.disputed_ids(recs, "sonnet"), [bad])
        self.assertEqual(af.disputed_ids(recs, "opus"), [])
        af.plan_disputed(self.out, self.manifest, self.targets, recs, ret["judged"], "sonnet")
        sb = next(b for b in self.manifest["bundles"] if b["stage"] == "sonnet")
        row = json.loads((self.out / sb["input"]).read_text(encoding="utf-8"))
        self.assertEqual(set(row["前の判定"]), {"A", "B"})  # 裁定役には A/B の理由を見せる
        # Sonnet が A とも B とも違う値 → Opus へ
        af.write_jsonl(self.out / sb["return"], [child(bad, self.version, rng="不明", 確認できなかった点="資料なし", model="sonnet-test")])
        ret, recs = self.state()
        self.assertEqual(af.disputed_ids(recs, "opus"), [bad])
        af.plan_disputed(self.out, self.manifest, self.targets, recs, ret["judged"], "opus")
        ob = next(b for b in self.manifest["bundles"] if b["stage"] == "opus")
        af.write_jsonl(self.out / ob["return"], [child(bad, self.version, rng="一部", model="opus-test")])
        _, recs = self.state()
        r = next(r for r in recs if r["id"] == bad)
        self.assertEqual((r["判定"], r["段"]["範囲"], r["裁定者のモデル"]), (af.FAIL, "opus裁定", ["opus-test"]))
        self.assertEqual(set(r["判定の記録"]), {"A", "B", "Sonnet", "Opus"})
        self.assertFalse(r["haikuAB"]["範囲"])

    def test_sonnet_agreeing_with_one_side_settles(self):
        bad = "閣法-1-2"
        self.split(bad)
        ret, recs = self.state()
        af.plan_disputed(self.out, self.manifest, self.targets, recs, ret["judged"], "sonnet")
        sb = next(b for b in self.manifest["bundles"] if b["stage"] == "sonnet")
        af.write_jsonl(self.out / sb["return"], [child(bad, self.version, model="sonnet-test")])
        _, recs = self.state()
        r = next(r for r in recs if r["id"] == bad)
        self.assertEqual((r["判定"], r["段"]["範囲"]), (af.PASS, "sonnet裁定"))
        self.assertEqual(af.stage_stats(recs)["範囲"]["sonnet裁定"], 1)

    def test_sample_lists_each_kind(self):
        for s in "AB":
            self.answer("haiku", s, lambda i: child(i, self.version))
        _, recs = self.state()
        rows = af.sample_rows(recs, 2, 0)
        self.assertEqual({r["種類"] for r in rows}, {"範囲", "分類", "総合"})
        self.assertTrue(all(r["id"] and r["判定"] in (af.PASS, af.FAIL) for r in rows))


class EvidenceTest(Base):
    def one(self, **kw):
        b = next(b for b in self.manifest["bundles"] if b["system"] == "A")
        af.write_jsonl(self.out / b["return"], [child(b["ids"][0], self.version, **kw)])
        ret, _ = self.state()
        return ret["violations"]

    def test_quote_not_in_source_is_rejected(self):
        v = self.one(根拠引用=[{"出典": "overviews", "引用": "資料に書かれていない作り話の一文"}])
        self.assertTrue(v and "実在しない" in v[0]["reason"])

    def test_quote_with_different_whitespace_is_accepted(self):
        self.assertEqual(self.one(根拠引用=[{"出典": "overviews", "引用": "産業全体の 設備投資を促す"}]), [])

    def test_decided_without_quote_is_rejected(self):
        self.assertIn("根拠引用が無い", self.one(根拠引用=[])[0]["reason"])

    def test_subquestions_must_match_answer(self):
        v = self.one(小問={"範囲1": "はい", "範囲2": "いいえ", "分類1": "はい", "分類2": "いいえ"})  # 範囲は全体と答えたが小問は一部
        self.assertIn("整合しない", v[0]["reason"])

    def test_assumption_shape_checked(self):
        self.assertIn("仮定の形", self.one(仮定=[{"内容": "x", "強さ": "とても強い", "影響": "y"}])[0]["reason"])

    def test_assumption_ledger_and_card(self):
        for s in "AB":
            self.answer("haiku", s, lambda i: child(i, self.version))
        _, recs = self.state()
        led = af.assumption_ledger(recs)
        self.assertEqual(len(led), 1)
        self.assertEqual(led[0]["本数"], 6)
        r = next(r for r in recs if r["id"] == "閣法-1-1")
        self.assertEqual(r["仮定"][0]["仮定ID"], led[0]["仮定ID"])

    def test_derive_tables(self):
        self.assertEqual(af.derive_range("はい", "はい"), "不明")
        self.assertEqual(af.derive_class("いいえ", "不明"), "制度整備")


class FrozenAndGroupsTest(Base):
    def test_frozen_is_reproducible_and_excludes_calibration(self):
        led = [ledger_row(i) for i in range(1, 31)]
        a = af.frozen_ids(led, 10, 7, {"閣法-1-1", "閣法-1-2"})
        self.assertEqual(a, af.frozen_ids(led, 10, 7, {"閣法-1-1", "閣法-1-2"}))
        self.assertEqual(len(a), 10)
        self.assertFalse({"閣法-1-1", "閣法-1-2"} & set(a))
        self.assertNotEqual(a, af.frozen_ids(led, 10, 8, set()))

    def test_frozen_rows_record_inclusion_probability(self):
        led = [ledger_row(i) for i in range(1, 21)]
        rows = af.frozen_rows(led, 5, 1, set())
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(abs(r["抽出確率"] - 5 / 20) < 1e-9 and r["N"] == 20 for r in rows))

    def test_upper_bound_for_zero_failures_is_about_three_over_n(self):
        self.assertAlmostEqual(af.cp_upper(0, 300), 3 / 300, delta=0.0006)
        self.assertGreater(af.cp_upper(3, 300), af.cp_upper(0, 300))

    def test_share_groups(self):
        g = af.share_groups(self.ledger, self.macro)
        self.assertEqual([x["本数"] for x in g], [6, 2])
        self.assertIn({"産業": "_T", "窓": ""}, g[1]["業界×期間"])


class PpiTest(unittest.TestCase):
    def test_ppi_corrects_prediction_bias(self):
        f_all = [1] * 20 + [0] * 80  # 予測の不合格率 0.2
        lab = [(1, 1)] * 4 + [(1, 0)] * 1 + [(0, 0)] * 15  # 標本20本：予測1のうち正解0が1本、予測0に見逃しなし
        est = af.ppi_rate(f_all, [p for p, _ in lab], [y for _, y in lab])
        self.assertAlmostEqual(est["推定"], 0.2 - 1 / 20, places=4)
        self.assertLess(est["下限95%"], est["推定"])
        self.assertGreater(est["上限95%"], est["推定"])


class CalibrationTest(Base):
    def test_rates_and_warnings(self):
        for s in "AB":
            self.answer("haiku", s, lambda i: child(i, self.version, rng="一部") if i == "閣法-1-1" else child(i, self.version))
        ret, recs = self.state()
        truth = {t["id"]: af.PASS for t in self.targets}
        truth["閣法-1-1"] = af.PASS  # 子は不合格と判定 → 誤検出
        truth["閣法-1-8"] = af.FAIL
        truth["閣法-1-9"] = af.FAIL
        cal = af.calibration(recs, ret["judged"], truth, self.targets, self.version)
        self.assertEqual(cal["final"]["誤検出率"], round(1 / 6, 4))
        self.assertEqual(cal["final"]["見逃し率"], 0.0)
        warn = af.calibration_warnings(cal, af.load_baseline()["calibration"], af.files_hash_of(self.version))
        self.assertTrue(any("件数" in w for w in warn) and all("全件に回さず" in w for w in warn))
        self.assertTrue(af.calibration_warnings(None, af.load_baseline()["calibration"], "x")[0].startswith("較正が未実施"))
        self.assertTrue(any("プロンプトが替わった" in w for w in af.calibration_warnings(cal, {**af.load_baseline()["calibration"], "min_samples": 1}, "別のハッシュ")))

    def test_low_agreement_warns(self):
        cal = {"n": 118, "final": {"一致率": 0.8, "見逃し率": 0.1, "誤検出率": 0.0, "正解の合格数": 40}, "promptFilesHash": "h"}
        w = af.calibration_warnings(cal, af.load_baseline()["calibration"], "h")
        self.assertEqual(len(w), 2)

    def test_few_truth_passes_say_false_alarm_is_unmeasurable(self):
        cal = {"n": 108, "final": {"一致率": 0.92, "見逃し率": 0.03, "誤検出率": 1.0, "正解の合格数": 1}, "promptFilesHash": "h"}
        w = af.calibration_warnings(cal, af.load_baseline()["calibration"], "h")
        self.assertEqual(len(w), 1)
        self.assertIn("測れない", w[0])


class BaselineTest(unittest.TestCase):
    def test_flag_violations_do_not_increase(self):
        base = af.load_baseline()["flag_violations"]
        now = af.flag_counts(af.build_targets(af.read_csv(af.LEDGER), af.read_csv(af.MACRO), None, af.japan_ceiling()))
        self.assertLessEqual(now["narrow_whole_economy"], base["narrow_whole_economy"])
        if af.japan_ceiling() is not None:
            self.assertLessEqual(now["oversize"], base["oversize"])

    def test_calibration_thresholds_are_not_loosened(self):
        c = af.load_baseline()["calibration"]
        self.assertGreaterEqual(c["min_agreement"], 0.9)
        self.assertLessEqual(c["max_miss_rate"], c["max_false_alarm_rate"])
        self.assertGreaterEqual(c["min_truth_pass"], 10)


if __name__ == "__main__":
    unittest.main()
