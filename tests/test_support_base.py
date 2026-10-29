"""議員の支持基盤の表（scripts/build_support_base.py）：出典のある公表分だけ、個人は入れない。"""
import unittest

from scripts import build_support_base as sb


class BuildTest(unittest.TestCase):
    def test_only_sourced_verified_org_rows(self) -> None:
        end = [
            {"人物ID": "P1", "氏名": "x", "団体": "株式会社日本薬剤師連盟", "団体区分": "政治連盟", "関係": "推薦", "年": "2022", "出典URL": "https://example.jp/a", "確度": "原本照合済み（2系統一致）"},
            {"人物ID": "P1", "氏名": "x", "団体": "B連盟", "団体区分": "", "関係": "推薦", "年": "2022", "出典URL": "", "確度": "原本照合済み"},
            {"人物ID": "P1", "氏名": "x", "団体": "C連盟", "団体区分": "", "関係": "噂", "年": "2022", "出典URL": "https://example.jp/c", "確度": "原本照合済み"},
            {"人物ID": "P1", "氏名": "x", "団体": "D連盟", "団体区分": "", "関係": "支持", "年": "2022", "出典URL": "https://example.jp/d", "確度": "未照合"},
        ]
        rel = [{"区分": "受けた寄附", "相手方種別": "団体", "人物ID": "P1", "団体名キー": "日本薬剤師連盟", "相手方": "日本薬剤師連盟", "年分": "2021", "金額": "10", "PDF_URL": "https://example.jp/p"},
               {"区分": "受けた寄附", "相手方種別": "個人", "人物ID": "P1", "団体名キー": "", "相手方": "個人", "年分": "2021", "金額": "1", "PDF_URL": ""},
               {"区分": "支出", "相手方種別": "団体", "人物ID": "P1", "団体名キー": "Z", "相手方": "Z", "年分": "2021", "金額": "1", "PDF_URL": ""}]
        rows = sb.build(end, rel)
        self.assertEqual([r["根拠"] for r in rows], ["寄附", "推薦"])
        self.assertEqual({r["団体名キー"] for r in rows}, {"日本薬剤師連盟"})  # 推薦と寄附が同じ鍵で結べる

    def test_distributed_table_matches(self) -> None:
        self.assertEqual(sb.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
