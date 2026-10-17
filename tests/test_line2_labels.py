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
    def test_labels_cover_laws_with_enforcement_date_and_follow_spec(self):
        labels = read(DERIVED / "bill-triage-v1-line2" / "labels.csv")
        ledger = read(ROOT / "data" / "acquired" / "enforcement-dates" / "enforcement.csv")
        dated = [r["id"] for r in ledger if r["施行日"].strip()]
        # 施行日の取得を待つ行にも先に付けてよい。施行日のある行は漏らさず、並びは施行日台帳の順。
        ids = [r["id"] for r in labels]
        self.assertEqual(ids, [r["id"] for r in ledger if r["id"] in set(ids)])
        self.assertTrue(set(dated) <= set(ids))
        for r in labels:
            self.assertIn(r["系統2_種類"], KINDS)
            if r["系統2_分野"] == "対応表なし":
                self.assertEqual(r["系統2_指標"], "")
            else:
                self.assertIn(r["系統2_指標"], FIELDS[r["系統2_分野"]], r["id"])
            out = r["系統2_種類"] in {"定型改正", "組織手続"} or r["系統2_分野"] == "対応表なし"
            self.assertEqual(r["系統2_判定"], "評価対象外" if out else "評価対象", r["id"])

    def test_disagreements_are_held_in_impact(self):
        # impact-v1-triage-v2 の振り分けは bill-triage-v2。両系統が評価対象外で一致した法律は影響の判定に回らず、それ以外は全て載る。
        agreement = {r["id"]: r for r in read(DERIVED / "bill-triage-v2" / "agreement.csv")}
        l1 = {r["id"]: r for r in read(DERIVED / "bill-triage-v2" / "labels-line1.csv")}
        l2 = {r["id"]: r for r in read(DERIVED / "bill-triage-v2" / "labels-line2.csv")}
        impact = read(DERIVED / "impact-v1-triage-v2" / "impact.csv")
        judged = {i for i in agreement if not (agreement[i]["結果"] == "採用" and l1[i]["結果"] == l2[i]["系統2_判定"] == "評価対象外")}
        self.assertEqual({r["id"] for r in impact}, judged)
        for r in impact:
            if agreement[r["id"]]["結果"] == "保留":
                self.assertEqual(r["判定"], "保留（2系統の振り分けが一致しない）", r["id"])
                self.assertEqual(r["向き"], "", r["id"])

if __name__ == "__main__":
    unittest.main()
