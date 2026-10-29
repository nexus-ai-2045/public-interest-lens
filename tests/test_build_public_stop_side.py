import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_public_stop_side as b  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class PublicStopSideTest(unittest.TestCase):
    def test_org_name_keeps_only_the_organisation(self):
        self.assertEqual(b.org_name("全国旅館ホテル生活衛生同業組合連合会 会長", "業界団体"), "全国旅館ホテル生活衛生同業組合連合会")
        self.assertEqual(b.org_name("日本漢方連盟（（氏名）啓晃 参考人。根本構成員の代理として出席）", "業界団体"), "日本漢方連盟")
        self.assertEqual(b.org_name("公益社団法人全国賃貸住宅経営者協会連合会会長", "業界団体"), "公益社団法人全国賃貸住宅経営者協会連合会")

    def test_individuals_get_no_name_or_affiliation(self):
        self.assertEqual(b.org_name("東京大学", "学者"), "")
        self.assertEqual(b.org_name("涼風法律事務所 弁護士", "その他（弁護士）"), "")
        self.assertEqual(b.org_name("委員（匿名）", "その他"), "")
        self.assertEqual(b.org_name("議事録上の所属記載なし", "業界団体"), "")

    def test_built_file_counts_match_the_sources(self):
        data = b.build()
        c = data["counts"]
        self.assertEqual(c["actors"], 1227)
        self.assertEqual((c["confirmed"], c["held"], c["unchecked"]), (653, 524, 50))
        self.assertEqual((c["rulings"], c["rulingsHeld"]), (40, 8))
        self.assertTrue(all(a["u"].startswith("https://") for a in data["actors"] if "u" in a))
        self.assertTrue(all(a["r"] for a in data["actors"] if "r" in a))

    def test_no_dropped_columns_leak(self):
        raw = json.dumps(b.build(), ensure_ascii=False)
        for forbidden in ("鎌田", "石飛", "梅沢", "根本構成員"):
            self.assertNotIn(forbidden, raw)

    def test_distribution_stays_one_file_while_light(self):
        # 約0.7MB。1.5MBを超えたら系統ごとに分割する（配布ファイルは他に votes.json が約2.8MB）。
        self.assertLess((ROOT / "app/public/distribution/stop-side.json").stat().st_size, 1_500_000)

    def test_committed_file_is_current(self):
        committed = json.loads((ROOT / "app/public/distribution/stop-side.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, b.build())


if __name__ == "__main__":
    unittest.main()
