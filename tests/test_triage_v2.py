"""bill-triage-v2 の2つの実装（app/src/indicator-pick.ts と scripts/triage_v2_line2.py）の出力が全題名で同じことと、
派生データの形（施行日のある全行・語彙・一致表）を確かめる。規則の中身の正しさではなく、書き起こしの写し間違いと出力の食い違いを拾う。"""
import csv
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from scripts import estimate_field_expansion as est
from scripts import triage_v2_line2 as py

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "data" / "derived" / "bill-triage-v2"
ENFORCEMENT = ROOT / "data" / "acquired" / "enforcement-dates" / "enforcement.csv"


def read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def dated_count():
    return sum(1 for r in read(ENFORCEMENT) if r["施行日"].strip())


class TriageV2Test(unittest.TestCase):
    def test_python_implementation_reproduces_the_typescript_line1_output(self):
        # 系統1のラベルは TypeScript の実装の出力。同じ入力（系統1のAIの種類・分野）をPython実装に通して、全行で同じになる。
        rows = read(V2 / "labels-line1.csv")
        self.assertEqual(len(rows), dated_count())
        # A・B が割れて第3の判定者の値を使った行は、規則の末尾に TB、理由の末尾に「／TB：…」が付く。
        for r in rows:
            out = py.triage(r["題名"], r["系統1_入力種類"], r["系統1_入力分野"])
            rules, reason = r["規則"], r["理由"]
            if rules.endswith("／TB"):
                rules, reason = rules[: -len("／TB")], reason.split("／TB：")[0]
            self.assertEqual(
                (out["verdict"], out["kind"], out["field"], out["indicator"], "／".join(out["rules"]), out["reason"]),
                (r["結果"], r["種類"], r["分野"], r["指標"], rules, reason), r["id"])

    def test_line2_labels_are_what_the_script_produces(self):
        src = {r["id"]: r for r in read(ROOT / "data" / "derived" / "bill-triage-v1-line2" / "labels.csv")}
        rows = read(V2 / "labels-line2.csv")
        self.assertEqual([r["id"] for r in rows], list(src))
        for r in rows:
            out = py.triage(r["題名"], src[r["id"]]["系統2_種類"], src[r["id"]]["系統2_分野"])
            self.assertEqual((r["系統2_判定"], r["系統2_種類"], r["系統2_分野"], r["系統2_指標"]),
                             (out["verdict"], out["kind"], out["field"], out["indicator"]), r["id"])

    def test_both_lines_use_known_vocabulary(self):
        pick_indicators = {i for rows, default in py._PICK.values() for _, _, i in rows} | {d for _, d in py._PICK.values()}
        pick_indicators |= {py.new_indicator(f, m) for f in py.NEW_FIELD_NAMES for m in ("直接", "代理")}
        for name, cols in (("labels-line1.csv", ("結果", "種類", "分野", "指標")), ("labels-line2.csv", ("系統2_判定", "系統2_種類", "系統2_分野", "系統2_指標"))):
            for r in read(V2 / name):
                verdict, kind, field, indicator = (r[c] for c in cols)
                self.assertIn(verdict, {"評価対象", "評価対象外", "保留"}, r["id"])
                if verdict == "保留":
                    self.assertEqual(indicator, "", r["id"])
                    continue
                self.assertIn(kind, py.KINDS, r["id"])
                if field == py.NO_FIELD:
                    self.assertEqual(indicator, "", r["id"])
                else:
                    self.assertIn(field, py.ALL_FIELDS, r["id"])
                    self.assertIn(indicator, pick_indicators, r["id"])

    def test_agreement_csv_matches_the_two_label_files(self):
        l1 = {r["id"]: r for r in read(V2 / "labels-line1.csv")}
        l2 = {r["id"]: r for r in read(V2 / "labels-line2.csv")}
        ag = read(V2 / "agreement.csv")
        self.assertEqual(len(ag), dated_count())
        from scripts import eval_loop
        overviews = {r["id"]: r for r in read(ROOT / "data" / "derived" / "law-overviews-v1" / "overviews.csv")}
        lines = {r["id"]: r for r in read(V2 / "tiebreak-lines.csv")} if (V2 / "tiebreak-lines.csv").exists() else {}
        for r in ag:
            if r["解消規則"] == "TB2":
                # 第3の判定者が系統を選んだ行は、選んだ系統の値をそのまま採る（新しい値は作らない）。
                # Haiku 2系統が一致した決定で、判定したときの入力が今のラベルと同じものだけ
                tb = lines[r["id"]]
                self.assertIn(tb["採用"], {"系統1", "系統2"}, r["id"])
                self.assertEqual(tb["決め方"], "一致", r["id"])
                a, b = l1[r["id"]], l2[r["id"]]
                self.assertEqual(tb["系統1の値"], eval_loop.value1(a), r["id"])
                self.assertEqual(tb["系統2の値"], eval_loop.value2(b), r["id"])
                o = overviews.get(r["id"], {})
                self.assertEqual(tb["概要の値"], eval_loop.overview_value(o.get("何をする", ""), o.get("狙い", "")), r["id"])
                self.assertEqual(r["結果"], "採用", r["id"])
                continue
            a, b = l1[r["id"]], l2[r["id"]]
            if r["解消規則"] == "R2":
                # 点検 R2：2系統が一致していても、r2-holds.csv にある法律は採用しない
                self.assertEqual(r["結果"], "保留", r["id"])
                self.assertIn(r["id"], {h["id"] for h in read(V2 / "r2-holds.csv")}, r["id"])
                continue
            same = a["結果"] != "保留" and (a["結果"], a["分野"], a["指標"]) == (b["系統2_判定"], b["系統2_分野"], b["系統2_指標"])
            self.assertEqual(r["結果"], "採用" if same else "保留", r["id"])

    def test_v1_agreement_is_left_untouched(self):
        # 版を切り替えても、bill-triage-v1 の一致の表は 142/170 のまま（旧版の結果は上書きしない）
        ag = read(ROOT / "data" / "derived" / "bill-triage-v1" / "agreement.csv")
        self.assertEqual((len(ag), sum(r["結果"] == "採用" for r in ag)), (170, 142))

    def test_d1_uses_first_keyword_not_ai_field(self):
        for title, ai, expected in [
            ("特定高度情報通信技術活用システムの開発供給及び導入の促進に関する法律案", "通信・ネット", "行政のデジタル化"),
            ("道路と銀行に関する法律案", "金融", "交通・移動"),
            ("銀行と道路に関する法律案", "交通・移動", "金融"),
            ("労働基準法案", "対応表なし", "労働市場"),
        ]:
            with self.subTest(title=title):
                self.assertEqual(py.triage(title, "新規", ai)["field"], expected)

    def test_hr1_resolves_equal_position_conflict_by_longest_word(self):
        # v2.1 HR1：同じ位置の「電子」（行政のデジタル化）と「電子商取引」（通信・ネット）は、他の語の一部でない最長の語の分野
        out = py.triage("電子商取引法案", "新規", "通信・ネット")
        self.assertEqual((out["verdict"], out["field"], out["indicator"]), ("評価対象", "通信・ネット", "ネット企業の時価総額"))
        self.assertEqual(out["rules"][:2], ["HR1", "D1"])
        out = py.triage("海洋再生可能エネルギー発電設備の整備に係る海域の利用の促進に関する法律案", "新規", "エネルギー")
        self.assertEqual((out["field"], out["indicator"]), ("エネルギー", "発電構成"))

    def test_hr1_still_holds_when_unrelated_words_conflict(self):
        # 他の語の一部でない語が複数の分野に残るなら解けない（D5のまま、競合した分野と語を理由に残す）
        res = py.resolve_tie([("金融", "AB", 1), ("交通・移動", "AC", 2)])
        self.assertIsInstance(res, str)
        self.assertIn("金融「AB」／交通・移動「AC」", res)
        self.assertEqual(py.resolve_tie([("金融", "再生", 1), ("エネルギー", "再生可能", 2)]), 2)

    def test_hr2_treats_kikouhou_nado_amendment_like_d4(self):
        out = py.triage("地方公共団体情報システム機構法等の一部を改正する法律案", "組織手続", "行政のデジタル化")
        self.assertEqual((out["kind"], out["verdict"]), ("実質改正", "評価対象"))
        self.assertIn("HR2", out["rules"])
        # 設置法を含む題名や、機構法でない題名は直さない
        self.assertEqual(py.triage("法務省設置法等の一部を改正する法律案", "組織手続", "対応表なし")["kind"], "組織手続")

    def test_hr3_hr4_resolve_by_fixed_rules_and_otherwise_stay_held(self):
        def line(verdict, field, indicator, kind="新規"):
            return {"verdict": verdict, "field": field, "indicator": indicator, "kind": kind}
        # HR3：同分野で指標違い → 分野の表の上の行（F1 不良債権比率 が F2 企業倒産件数 と既定 貸出残高 より先）
        r = py.resolve_diff("預金保険法案", line("評価対象", "金融", "貸出残高"), line("評価対象", "金融", "不良債権比率"))
        self.assertEqual((r["rule"], r["line"]["indicator"]), ("HR3", "不良債権比率"))
        r = py.resolve_diff("x", line("評価対象", "金融", "貸出残高"), line("評価対象", "金融", "企業倒産件数"))
        self.assertEqual(r["line"]["indicator"], "企業倒産件数")
        # 判定も違えば HR3 に当たらない
        self.assertEqual(py.resolve_diff("x", line("評価対象", "金融", "貸出残高"), line("評価対象外", "金融", "不良債権比率"))["rule"], "")
        # HR4：片方が対応表なし、題名に分野の直接の語があれば採る（種類が同じ場合だけ）
        r = py.resolve_diff("銀行法案", line("評価対象外", "対応表なし", ""), line("評価対象", "金融", "貸出残高"))
        self.assertEqual((r["rule"], r["line"]["field"], r["line"]["verdict"]), ("HR4", "金融", "評価対象"))
        r = py.resolve_diff("銀行法案", line("評価対象外", "対応表なし", "", "定型改正"), line("評価対象", "金融", "貸出残高"))
        self.assertEqual(r["rule"], "")
        # 題名に直接の語が無ければ採らない
        r = py.resolve_diff("ほげ法案", line("評価対象外", "対応表なし", ""), line("評価対象", "金融", "貸出残高"))
        self.assertEqual(r["rule"], "")
        self.assertIn("直接の語が無い", r["reason"])
        # 保留が混じる、別々の分野は解消しない
        self.assertEqual(py.resolve_diff("x", line("保留", "", ""), line("評価対象", "金融", "貸出残高"))["rule"], "")
        self.assertEqual(py.resolve_diff("x", line("評価対象", "金融", "貸出残高"), line("評価対象", "労働市場", "賃金"))["rule"], "")

    def test_typescript_and_python_agree_on_hr3_hr4(self):
        def line(verdict, field, indicator, kind="新規"):
            return {"verdict": verdict, "field": field, "indicator": indicator, "kind": kind}
        cases = [
            ["預金保険法案", line("評価対象", "金融", "貸出残高"), line("評価対象", "金融", "不良債権比率")],
            ["x", line("評価対象", "金融", "企業倒産件数"), line("評価対象", "金融", "貸出残高")],
            ["x", line("評価対象", "金融", "貸出残高"), line("評価対象外", "金融", "不良債権比率")],
            ["x", line("評価対象", "金融", "未知の指標"), line("評価対象", "金融", "貸出残高")],
            ["銀行法案", line("評価対象外", "対応表なし", ""), line("評価対象", "金融", "貸出残高")],
            ["銀行法案", line("評価対象", "金融", "貸出残高"), line("評価対象外", "対応表なし", "")],
            ["銀行法案", line("評価対象外", "対応表なし", "", "定型改正"), line("評価対象", "金融", "貸出残高")],
            ["銀行法案", line("評価対象外", "対応表なし", "", "組織手続"), line("評価対象外", "金融", "貸出残高", "組織手続")],
            ["ほげ法案", line("評価対象外", "対応表なし", ""), line("評価対象", "金融", "貸出残高")],
            ["x", line("保留", "", ""), line("評価対象", "金融", "貸出残高")],
            ["x", line("評価対象", "金融", "貸出残高"), line("評価対象", "労働市場", "賃金")],
            ["出入国管理及び難民認定法及び銀行設置法の一部を改正する法律案", line("評価対象外", "対応表なし", ""), line("評価対象", "金融", "貸出残高")],
        ]
        res = subprocess.run(["node", str(ROOT / "tests" / "triage_v2_resolve_ts_dump.mjs")], input=json.dumps(cases), capture_output=True, text=True, check=True)
        for (title, l1, l2), got in zip(cases, json.loads(res.stdout)):
            out = py.resolve_diff(title, l1, l2)
            ln = out.get("line", {})
            self.assertEqual(got, [out["rule"], ln.get("verdict", ""), ln.get("field", ""), ln.get("indicator", ""), out["reason"]], title)
        self.assertEqual(len(json.loads(res.stdout)), len(cases))

    def test_v21_resolves_known_holds_and_every_row_carries_rule_or_reason(self):
        # 施行日のある全法律に広げた後も、元の5本は解消規則で解け、残る保留には必ず理由がある。
        ag = read(V2 / "agreement.csv")
        for r in ag:
            if r["結果"] == "保留":
                self.assertTrue(r["理由"], r["id"])
        resolved = [r for r in ag if r["解消規則"] and r["解消規則"] != "R2"]
        self.assertLessEqual({"閣法-151-92", "閣法-185-8", "閣法-193-45", "閣法-197-5", "閣法-217-46"}, {r["id"] for r in resolved})
        for r in resolved:
            self.assertTrue(r["食い違いの区分"], r["id"])
            self.assertIn("TB2：第3の判定者が" if r["解消規則"] == "TB2" else "解消前は保留または食い違い", r["理由"], r["id"])
            self.assertEqual(r["結果"], "採用", r["id"])

    def test_r2_holds_are_held_with_their_reason_and_never_adopted(self):
        # 点検 R2：第3の判定者の対応表なしを D1 が上書きして通信業の額になっていた2本は、保留の理由と根拠を持つ
        holds = {h["id"]: h for h in read(V2 / "r2-holds.csv")}
        self.assertEqual(set(holds), {"閣法-169-48", "閣法-189-62"})
        ag = {r["id"]: r for r in read(V2 / "agreement.csv")}
        for law_id, h in holds.items():
            self.assertTrue(h["理由"] and h["根拠"], law_id)
            self.assertEqual((ag[law_id]["結果"], ag[law_id]["解消規則"]), ("保留", "R2"), law_id)
            self.assertIn(h["理由"], ag[law_id]["理由"], law_id)

    def test_first_law_title(self):
        self.assertEqual(py.first_law("出入国管理及び難民認定法及び法務省設置法の一部を改正する法律案"), "出入国管理及び難民認定法の一部を改正する法律案")


class FieldExpansionTest(unittest.TestCase):
    """field-expansion-v1：新分野の語は既存8分野の語が無い題名にだけ当てる。代理の語は「（代理）」付きの別の指標（参考扱い）。水道・廃棄物は作らない（B3）。"""

    def test_word_tables_are_the_proposal_tables_without_water_and_waste(self):
        expected = {f: (ind, [w for w, m in ws if m == "直接"], [w for w, m in ws if m == "代理"])
                    for f, (ind, ws) in est.NEW_FIELDS.items() if f != "水道・廃棄物"}
        got = {f: (ind, [w for w in direct.split("、") if w], [w for w in proxy.split("、") if w]) for f, (ind, direct, proxy) in py._NEW_FIELDS.items()}
        self.assertEqual(got, expected)
        self.assertNotIn("水道・廃棄物", py._NEW_FIELDS)
        self.assertEqual(len(py.NEW_FIELD_NAMES), 9)

    def test_new_fields_apply_only_when_existing_words_give_no_field(self):
        self.assertEqual(py.triage("農業経営基盤強化促進法の一部を改正する法律案", "実質改正", "対応表なし")["field"], "農林水産")
        # 同じ位置なら既存優先：「信託」（金融）と同じ位置に新分野の語は無いが、既存8分野の語が先なら既存のまま。
        out = py.triage("信託業法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual(out["field"], "金融")
        # R3：新分野の語（建築）が既存8分野の語（エネルギー）より先にあれば新分野。
        out = py.triage("建築物のエネルギー消費性能の向上に関する法律案", "新規", "対応表なし")
        self.assertEqual(out["field"], "建設")
        self.assertIn("R3", out["rules"])

    def test_direct_word_keeps_the_indicator_name_and_proxy_word_gets_the_proxy_suffix(self):
        direct = py.triage("建設業法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual((direct["field"], direct["indicator"], direct["verdict"]), ("建設", "建設業の付加価値", "評価対象"))
        self.assertEqual(direct["rules"], ["D1", "建設直接"])
        proxy = py.triage("河川法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual((proxy["field"], proxy["indicator"]), ("建設", "建設業の付加価値（代理）"))
        self.assertEqual(proxy["rules"], ["D1", "建設代理"])
        # 教育は代理の語しか無い
        self.assertTrue(py.triage("義務教育の改正に関する法律案", "実質改正", "対応表なし")["indicator"].endswith("（代理）"))

    def test_water_and_waste_laws_stay_without_a_table(self):
        out = py.triage("下水道法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual((out["field"], out["verdict"]), (py.NO_FIELD, "評価対象外"))

    def test_kind_still_decides_the_verdict(self):
        self.assertEqual(py.triage("農業振興法の一部を改正する法律案", "定型改正", "対応表なし")["verdict"], "評価対象外")

    def test_ai_input_may_name_a_new_field_but_unknown_fields_are_held(self):
        self.assertEqual(py.triage("農業法案", "新規", "農林水産")["verdict"], "評価対象")
        self.assertEqual(py.triage("農業法案", "新規", "水道・廃棄物")["verdict"], "保留")

    def test_longer_word_at_the_same_position_wins_and_different_fields_are_held(self):
        out = py.triage("建築士法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual((out["field"], out["indicator"]), ("専門サービス・研究開発", "専門・科学技術、業務支援サービス業の付加価値"))
        saved = py._NEW_FIELDS
        try:
            py._NEW_FIELDS = {"教育": ("教育の付加価値", "", "共通語"), "建設": ("建設業の付加価値", "共通語", "")}
            self.assertEqual(py.triage("共通語法案", "新規", "対応表なし")["verdict"], "保留")
        finally:
            py._NEW_FIELDS = saved

    def test_existing_results_do_not_change_for_any_enacted_title(self):
        # 新分野の語を無効にした結果と比べる。違ってよいのは、もとが「対応表なし」だった行だけ。
        titles = [r["題名"] for r in read(ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv")]
        saved = py._NEW_FIELDS
        changed = 0
        try:
            for title in titles:
                for kind in py.KINDS:
                    py._NEW_FIELDS = saved
                    now = py.triage(title, kind, py.NO_FIELD)
                    py._NEW_FIELDS = {}
                    before = py.triage(title, kind, py.NO_FIELD)
                    if now != before:
                        changed += 1
                        # もとが対応表なしだった行か、R3（新分野の語が題名の先）で新分野に移った行だけ
                        if "R3" not in now["rules"]:
                            self.assertEqual(before["field"], py.NO_FIELD, title)
                        self.assertIn(now["field"], py.NEW_FIELD_NAMES + ("",), title)
        finally:
            py._NEW_FIELDS = saved
        self.assertGreater(changed, 0)

    @unittest.skipUnless(shutil.which("node"), "node が無い")
    def test_typescript_and_python_agree_on_every_enacted_title(self):
        titles = [r["題名"] for r in read(ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv")]
        inputs = [[t, py.KINDS[i % 4], (py.NO_FIELD, "金融", "農林水産")[i % 3]] for i, t in enumerate(titles)]
        res = subprocess.run(["node", str(ROOT / "tests" / "triage_v2_ts_dump.mjs")], input=json.dumps(inputs), capture_output=True, text=True, check=True)
        for (title, kind, field), got in zip(inputs, json.loads(res.stdout)):
            out = py.triage(title, kind, field)
            self.assertEqual(got, [out["verdict"], out["kind"], out["field"], out["indicator"], "／".join(out["rules"]), out["reason"]], title)
        self.assertEqual(len(json.loads(res.stdout)), len(titles))

    def test_derived_labels_hold_the_new_field_rows_and_the_funnel_is_unchanged(self):
        l2 = read(V2 / "labels-line2.csv")
        new = [r for r in l2 if r["系統2_分野"] in py.NEW_FIELD_NAMES]
        self.assertGreater(len(new), 0)
        self.assertTrue(any(r["系統2_判定"] == "評価対象" for r in new))
        for r in new:
            # 組織手続・定型改正などは分野があっても評価対象外（D1 など、種類で外れる）。
            self.assertIn(r["系統2_判定"], ("評価対象", "評価対象外"), r["id"])
            self.assertIn(r["系統2_指標"], {py.new_indicator(r["系統2_分野"], m) for m in ("直接", "代理")})
        # 施行日のある行の数は版を足しても変わらない（新しい法律は施行日の取得後に入る）
        self.assertEqual(len(l2), len(read(ENFORCEMENT)))
        self.assertEqual(len(read(V2 / "labels-line1.csv")), dated_count())

    def test_indicator_map_marks_proxy_rows_as_reference(self):
        rows = {r["指標"]: r for r in read(ROOT / "data" / "derived" / "impact-v1-triage-v2" / "indicator-map.csv")}
        for f in py.NEW_FIELD_NAMES:
            proxy = rows[py.new_indicator(f, "代理")]
            self.assertEqual(proxy["対応"], "代理", f)
            self.assertIn("参考", proxy["向き（指標ごとの扱い）"], f)
            if py._NEW_FIELDS[f][1]:
                direct = rows[py.new_indicator(f, "直接")]
                self.assertEqual(direct["向き（指標ごとの扱い）"], "高いほど良い", f)
            else:
                self.assertNotIn(py._NEW_FIELDS[f][0], rows, f)
            self.assertIn("国民経済計算", proxy["国内_対象と比較（候補を優先順に）"], f)
        # 教育・保健衛生・専門サービス・その他のサービスは2005・2000基準では分けられない
        for name in ("教育の付加価値（代理）", "保健衛生・社会事業の付加価値（代理）"):
            self.assertNotIn("2005基準", rows[name]["国内_対象と比較（候補を優先順に）"])
            self.assertNotIn("2000基準", rows[name]["国内_対象と比較（候補を優先順に）"])
        self.assertIn("2000基準", rows["建設業の付加価値"]["国内_対象と比較（候補を優先順に）"])


if __name__ == "__main__":
    unittest.main()


class LargeAmountRulesTest(unittest.TestCase):
    """R1・R3・R4（2026-10-18、額の大きい法律の点検 /mnt/project-files/analysis/額の大きい法律の点検_2026-10-18.md の6）。"""

    def test_r1_word_inside_an_excluded_compound_is_not_a_hit(self):
        self.assertEqual(py.find_word("国民健康保険法", "保険"), -1)
        self.assertEqual(py.find_word("財政投融資特別会計", "融資"), -1)
        self.assertEqual(py.find_word("特定農産加工業経営改善臨時措置法", "工業"), -1)
        # 同じ題名の別の位置に単独で現れれば当たる
        self.assertEqual(py.find_word("健康保険法及び保険業法", "保険"), 7)
        self.assertEqual(py.find_word("海洋汚染等及び海上災害の防止に関する法律", "災害"), -1)
        self.assertEqual(py.find_word("労働災害防止対策の推進", "災害"), 2)
        maritime = py.triage("海洋汚染等及び海上災害の防止に関する法律の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertNotEqual(maritime["field"], "労働市場")
        out = py.triage("国民健康保険法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual(out["field"], "医療・福祉")
        self.assertEqual(py.triage("国際通貨基金及び国際復興開発銀行への加盟に伴う措置に関する法律の一部を改正する法律案", "実質改正", "対応表なし")["field"], py.NO_FIELD)

    def test_r4_finance_uses_loans_only_with_a_lending_word(self):
        self.assertEqual(py.triage("金融商品取引法の一部を改正する法律案", "実質改正", "金融")["indicator"], "金融・保険業の付加価値")
        self.assertEqual(py.triage("保険業法の一部を改正する法律案", "実質改正", "金融")["indicator"], "金融・保険業の付加価値")
        self.assertEqual(py.triage("株式会社日本政策金融公庫法案", "新規", "金融")["indicator"], "貸出残高")

    @unittest.skipUnless(shutil.which("node"), "node が無い")
    def test_exclusion_tables_are_the_same_in_both_implementations(self):
        script = "const m = await import(process.argv[1]); process.stdout.write(JSON.stringify(m.WORD_EXCLUSIONS));"
        res = subprocess.run(["node", "--input-type=module", "-e", script, (ROOT / "app" / "src" / "indicator-pick.ts").as_uri()],
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(res.stdout), py.WORD_EXCLUSIONS)
