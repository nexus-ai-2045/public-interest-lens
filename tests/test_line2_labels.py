"""設計決定0007の系統2のラベルと一致表の形を確かめる（内容の正しさではなく、漏れ・語彙・一致の数え方）。"""
import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"

BENEFIT_KINDS = {"経済（内包）", "経済（付加価値の外）", "消費者保護", "金融の安定", "安全（事故）", "安全（犯罪）", "プライバシー", "環境", "移転"}
FIELDS = {"金融": {"不良債権比率", "貸出残高", "企業倒産件数"},
          "交通・移動": {"旅客輸送の付加価値", "利用件数", "就業者数"},
          "宿泊・観光": {"宿泊者数", "宿泊業の付加価値", "客室数"},
          "通信・ネット": {"通信業の付加価値", "ブロードバンド普及率", "ネット企業の時価総額"},
          "半導体・電子": {"世界輸出シェア", "生産額"},
          "エネルギー": {"電力価格", "発電構成", "エネルギー効率"},
          "労働市場": {"労働生産性", "賃金", "雇用の流動性"},
          "行政のデジタル化": {"電子申請率", "行政手続きの時間"}}
KINDS = {"新規", "実質改正", "定型改正", "組織手続"}
# 分野の拡張（criteria-v2-fields.md）の新分野は、直接の指標名か「（代理）」付きの指標名。
from scripts import triage_v2_line2 as _py  # noqa: E402
ALL_FIELDS = {**FIELDS, **{f: {_py.new_indicator(f, m) for m in ("直接", "代理")} for f in _py.NEW_FIELD_NAMES}}


def read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class BenefitLine2Test(unittest.TestCase):
    def test_labels_cover_loss_rows_with_known_kinds(self):
        labels = read(DERIVED / "benefit-v1-line2" / "labels.csv")
        loss_ids = {r["id"] for r in read(DERIVED / "loss-v1" / "loss.csv")}
        self.assertTrue(loss_ids <= {r["id"] for r in labels})
        for r in labels:
            self.assertIn(r["系統2_向きの矛盾"], {"抑える", "なし"})
            for k in filter(None, r["系統2_種類"].split("・")):
                self.assertTrue(k in BENEFIT_KINDS or (k.startswith("対応表外（") and k.endswith("）")), k)

    def test_agreement_table_matches_loss_rows_and_only_agreed_are_adopted(self):
        rows = read(DERIVED / "benefit-v1" / "agreement.csv")
        self.assertEqual([r["id"] for r in rows], [r["id"] for r in read(DERIVED / "loss-v1" / "loss.csv")])
        for r in rows:
            agreed = r["種類の一致"] == "一致" and r["向きの矛盾の一致"] == "一致"
            self.assertEqual(r["結果"], "採用" if agreed else "保留", r["id"])
        adopted = {r["id"] for r in rows if r["結果"] == "採用"}
        for r in read(DERIVED / "benefit-v1" / "classification.csv"):
            if r["id"] not in adopted:
                self.assertEqual(r["採用する種類"], "保留", r["id"])


class TriageLine2Test(unittest.TestCase):
    def test_labels_follow_ledger_order_and_may_cover_all_laws(self):
        labels = read(DERIVED / "bill-triage-v1-line2" / "labels.csv")
        ledger = read(ROOT / "data" / "acquired" / "enforcement-dates" / "enforcement.csv")
        triage_ids = [r["id"] for r in read(DERIVED / "bill-triage-v1" / "triage.csv")]
        ids = [r["id"] for r in labels]
        # 全3,415本に付けてよい（上位集合）。重複はなく、全て成立法の id。
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(ids) <= set(triage_ids))
        # 並びは次のどちらか：(a) triage.csv の順（全3,415本に付けた版）、(b) 施行日台帳の順に台帳の行が先で、台帳に無い行が triage.csv の順で続く（従来の349本の版を含む）。
        idset, ledger_ids = set(ids), [r["id"] for r in ledger]
        in_ledger = [i for i in ids if i in set(ledger_ids)]
        n = len(in_ledger)
        by_triage = ids == [i for i in triage_ids if i in idset]
        ledger_first = (in_ledger == [i for i in ledger_ids if i in idset] and ids[:n] == in_ledger
                        and ids[n:] == [i for i in triage_ids if i in idset and i not in set(ledger_ids)])
        self.assertTrue(by_triage or ledger_first)
        # 施行日のある行で系統2のラベルが無いものは、影響の段で「系統欠落」として保留になる（落ちない）。それでも台帳の行が全て揃う間は漏れを検出する。
        dated = [r["id"] for r in ledger if r["施行日"].strip()]
        if len(ids) < len(triage_ids):
            self.assertTrue(set(dated) <= set(ids))
        for r in labels:
            self.assertIn(r["系統2_種類"], KINDS)
            if r["系統2_分野"] in ("対応表なし", "保留"):
                # 保留：題名だけでは分野が1つに決まらない（振り分け v2 の D5 と同じく保留になる）。
                self.assertEqual(r["系統2_指標"], "")
            else:
                self.assertIn(r["系統2_指標"], ALL_FIELDS[r["系統2_分野"]], r["id"])
            out = r["系統2_種類"] in {"定型改正", "組織手続"} or r["系統2_分野"] in ("対応表なし", "保留")
            self.assertEqual(r["系統2_判定"], "評価対象外" if out else "評価対象", r["id"])

    def test_disagreements_are_held_in_impact(self):
        # impact-v1-triage-v2 の振り分けは bill-triage-v2。両系統が評価対象外で一致した法律は影響の判定に回らず、それ以外は全て載る。
        agreement = {r["id"]: r for r in read(DERIVED / "bill-triage-v2" / "agreement.csv")}
        l1 = {r["id"]: r for r in read(DERIVED / "bill-triage-v2" / "labels-line1.csv")}
        l2 = {r["id"]: r for r in read(DERIVED / "bill-triage-v2" / "labels-line2.csv")}
        impact = read(DERIVED / "impact-v1-triage-v2" / "impact.csv")
        # TB2（第3の判定者）で決着した行は、選ばれた系統の判定で決める
        tb_path = DERIVED / "bill-triage-v2" / "tiebreak-lines.csv"
        tb = {r["id"]: r["採用"] for r in read(tb_path)} if tb_path.exists() else {}

        def excluded(i):
            if agreement[i]["結果"] != "採用":
                return False
            if agreement[i]["解消規則"] == "TB2":
                return (l1[i]["結果"] if tb[i] == "系統1" else l2[i]["系統2_判定"]) == "評価対象外"
            return l1[i]["結果"] == l2[i]["系統2_判定"] == "評価対象外"
        judged = {i for i in agreement if not excluded(i)}
        self.assertEqual({r["id"] for r in impact}, judged)
        for r in impact:
            if agreement[r["id"]]["結果"] == "保留":
                self.assertEqual(r["判定"], "保留（2系統の振り分けが一致しない）", r["id"])
                self.assertEqual(r["向き"], "", r["id"])

if __name__ == "__main__":
    unittest.main()
