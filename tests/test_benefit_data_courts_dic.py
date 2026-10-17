import csv
import tempfile
import unittest
from pathlib import Path

from scripts import benefit_fetch as bf
from scripts import fetch_courts_bankruptcy as c
from scripts import fetch_dic_assistance as d


class BenefitFetchTests(unittest.TestCase):
    def test_sha256_and_manifest_round_trip(self):
        self.assertEqual(bf.sha256_bytes(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.csv"
            row = {k: "x" for k in bf.MANIFEST_COLS}
            row["url"] = "https://example.invalid/a"
            bf.append_manifest(row, path)
            bf.append_manifest({**row, "url": "https://example.invalid/b"}, path)
            got = bf.read_manifest(path)
            self.assertEqual(set(got), {"https://example.invalid/a", "https://example.invalid/b"})
            with path.open(encoding="utf-8", newline="") as fh:
                self.assertEqual(next(csv.reader(fh)), bf.MANIFEST_COLS)

    def test_write_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "o.csv"
            bf.write_csv(path, ["a", "b"], [[1, "x"], [2, "y"]])
            self.assertEqual(path.read_text(encoding="utf-8"), "a,b\n1,x\n2,y\n")


class CourtsTests(unittest.TestCase):
    def test_groupings_ambiguous_but_checked(self):
        # 千位の空白で切れ目が曖昧な並びは、検算を満たす分け方が1通りのときだけ採る
        toks = "131 370 121 150 120 930 10 220 9 840 129 576".split()
        self.assertEqual(c.values_from_tokens(toks), [131370, 121150, 120930, 10220, 9840, 129576])
        self.assertTrue(len(c.groupings(toks, 6)) > 1)

    def test_inconsistent_returns_none(self):
        self.assertIsNone(c.values_from_tokens("100 200 300 400 500 600".split()))

    def test_consistent(self):
        self.assertTrue(c.consistent([10, 7, 6, 3, 2, 9]))
        self.assertFalse(c.consistent([10, 7, 8, 3, 2, 9]))
        self.assertFalse(c.consistent([10, 7, 6, 4, 2, 9]))

    def test_pdf_text_plain(self):
        text = "\n".join([
            "第 104 表 執行官事務事件数",
            "総 数 1",
            "第 105 表 破産新受事件数―受理区分別―全地方裁判所",
            "新 受",
            "131 370 121 150 120 930 10 220 9 840 129 576",
            "第 106 表 破産未済事件数―審理期間別―全地方裁判所",
            "33 767 24 119",
        ])
        vals, why = c.values_from_pdf_text(text)
        self.assertEqual(vals[0], 131370)
        self.assertEqual(why, "")

    def test_pdf_text_missing_table(self):
        vals, why = c.values_from_pdf_text("第 1 表 何か\n1 2 3")
        self.assertIsNone(vals)
        self.assertIn("題名が無い", why)

    def test_pdf_text_old_layout_rejected(self):
        text = "第 102 表 破産新受事件数―受理区分別―全地方裁判所\n220 261 219 402 194 080 211 860 211 402 193 036 219 408\n第 103 表 x"
        vals, why = c.values_from_pdf_text(text)
        self.assertIsNone(vals)
        self.assertIn("検算", why)

    def test_decode_cid_and_garbled_table(self):
        self.assertEqual(c.decode_cid("(cid:20)(cid:19)(cid:23)(cid:3)(cid:999)"), "104 □")
        digits = "".join(f"(cid:{int(ch) + 19})" for ch in "105")

        def enc(n: str) -> str:
            return "".join(f"(cid:{int(ch) + 19})" if ch.isdigit() else "(cid:3)" for ch in n)

        text = f"(cid:1){enc('7722')}\n(cid:10152)(cid:3){digits}(cid:3)(cid:12210)\n" \
               f"(cid:3){enc('110 449   100 735   100 510   9 714   9 398   110 079')}\n" \
               f"(cid:10152)(cid:3){enc('106')}(cid:3)(cid:12210)"
        vals, why = c.values_from_pdf_text(text)
        self.assertEqual(vals, [110449, 100735, 100510, 9714, 9398, 110079])

    def test_values_from_rows_numbers_and_strings(self):
        head = [["第105表　破産新受事件数―受理区分別―全地方裁判所"], ["新   受"], ["総数"], [None, "自然人", None, "法人・その他"]]
        rows = head + [[None, 71840, 64872, 64639, 6968, 6759, 69714]]
        self.assertEqual(c.values_from_rows(rows)[0], [71840, 64872, 64639, 6968, 6759, 69714])
        rows2 = head + [["80 202", "73 292", "73 095", " 6 910", " 6 743", "78 415"]]
        self.assertEqual(c.values_from_rows(rows2)[0], [80202, 73292, 73095, 6910, 6743, 78415])
        rows3 = head + [[1, 2, 3, 4, 5, 6]]
        self.assertIsNone(c.values_from_rows(rows3)[0])

    def test_cell_int(self):
        self.assertEqual(c.cell_int(" 6 910"), 6910)
        self.assertIsNone(c.cell_int("自然人"))
        self.assertIsNone(c.cell_int(True))

    def test_candidate_links(self):
        page = '<a href="./../x/toukei-pdf-5.pdf">a</a>破産新受事件数<a href="../toukei-pdf-6.pdf">b</a><a href="../toukei-excel-6.xlsx">c</a>'
        self.assertEqual(c.candidate_links(page, after="破産新受事件数"), ["toukei-pdf-6.pdf", "toukei-excel-6.xlsx"])
        self.assertEqual(len(c.candidate_links(page)), 3)
        self.assertEqual(c.candidate_links(page, after="無い"), [])

    def test_to_rows(self):
        rows = c.to_rows(2010, [1, 1, 1, 0, 0, 1], "u", "n")
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0][:4], [c.SERIES, "総数", 2010, 1])


class DicTests(unittest.TestCase):
    TEXT = "\n".join([
        "資金援助等の実施及び回収状況等（令和8年3月末現在)",
        "資金援助等項目",
        "①金銭の贈与 （注４）（注10）(cid:62)(cid:62) 190,319",
        "③資本増強 （注７）(cid:62)(cid:62) 123,809(cid:62)(cid:62) 123,809 － 16,934(cid:62)(cid:62) 140,743",
        "旧安定化法に基づく資本増強(cid:62)(cid:62) 18,156(cid:62)(cid:62) 18,156 － 581",
        "早期健全化法に基づく資本増強(cid:62)(cid:62) 86,053(cid:62)(cid:62) 86,053 － 13,730",
        "預金保険法に基づく資本増強(cid:62)(cid:62) 19,600(cid:62)(cid:62) 19,600 － 2,624",
        "131,208(cid:62)(cid:62) 127,696(cid:62)(cid:62) 3,512",
        "⑤その他(cid:62)(cid:62) 63,832(cid:62)(cid:62) ▲(cid:62)12,432",
        "※億円単位未満四捨五入",
        "損失の補塡 1",
    ])

    def test_parse_and_check(self):
        rows = d.parse_table(self.TEXT)
        got = dict(rows)
        self.assertEqual(got["①金銭の贈与"], 190319)
        self.assertEqual(got["③資本増強"], 123809)
        self.assertEqual(got["⑤その他"], 63832)
        self.assertNotIn("131,208", got)
        self.assertNotIn("損失の補塡", got)
        self.assertEqual(d.check(rows), "")

    def test_check_detects_mismatch(self):
        rows = [("③資本増強", 10), ("旧安定化法に基づく資本増強", 1), ("早期健全化法に基づく資本増強", 2), ("預金保険法に基づく資本増強", 3)]
        self.assertIn("合わない", d.check(rows))
        self.assertIn("必要な行が無い", d.check([("x", 1)]))


if __name__ == "__main__":
    unittest.main()
