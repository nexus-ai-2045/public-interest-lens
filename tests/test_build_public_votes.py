import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_public_votes as b  # noqa: E402


class PublicVotesTest(unittest.TestCase):
    def test_era_date(self):
        self.assertEqual(b.era_date("令和 8年 7月10日"), "2026-07-10")
        self.assertEqual(b.era_date("平成元年 1月 8日"), "1989-01-08")
        self.assertIsNone(b.era_date(""))

    def test_norm_title_drops_schedule_and_brackets(self):
        self.assertEqual(b.norm_title("日程第３ 放送法の一部を改正する法律案（内閣提出、衆議院送付）"), "放送法の一部を改正する法律案")
        self.assertEqual(b.norm_title("日程第３ 公職選挙法の一部を改正する法律案（衆議院提出）「委員長報告のとおり修正議決」"), "公職選挙法の一部を改正する法律案")
        # 別の法案の題名の一部には当たらない
        self.assertNotEqual(b.norm_title("日程第２ 有線ラジオ放送業務の運用の規正に関する法律及び有線テレビジョン放送法の一部を改正する法律案（内閣提出、衆議院送付）"), b.norm_title("放送法の一部を改正する法律案"))

    def test_split_parties(self):
        self.assertEqual(b.split_parties("自由民主党; 公明党"), ["自由民主党", "公明党"])
        self.assertEqual(b.split_parties(""), [])


if __name__ == "__main__":
    unittest.main()
