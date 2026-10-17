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
        for r in rows:
            out = py.triage(r["題名"], r["系統1_入力種類"], r["系統1_入力分野"])
            self.assertEqual(
                (out["verdict"], out["kind"], out["field"], out["indicator"], "／".join(out["rules"]), out["reason"]),
                (r["結果"], r["種類"], r["分野"], r["指標"], r["規則"], r["理由"]), r["id"])

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
        for r in ag:
            a, b = l1[r["id"]], l2[r["id"]]
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

    def test_d5_holds_equal_position_field_conflicts(self):
        self.assertEqual(py.triage("電子商取引法案", "新規", "通信・ネット")["verdict"], "保留")

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
        # 「保険」は既存の金融の語。前に「介護」（新分野）があっても既存優先。
        out = py.triage("介護保険法の一部を改正する法律案", "実質改正", "対応表なし")
        self.assertEqual((out["field"], out["indicator"]), ("金融", "貸出残高"))

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
        for r in new:
            self.assertEqual(r["系統2_判定"], "評価対象")
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
