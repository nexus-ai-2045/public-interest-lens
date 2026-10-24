import unittest

from scripts.apply_enforcement_webfetch import apply, decree_deadline, header_matches, main_sentence, remarks_after_adoption
from scripts.apply_enforcement_year_window import same_year
from scripts.fetch_enforcement_fusoku import parse_koryoku
from scripts.fetch_enforcement_old_egov import ABBREVIATED

ROW = {
    "id": "閣法-1-1", "題名": "甲法案", "法令番号": "平成十年法律第五号", "公布日": "1998-02-18", "施行日": "",
    "施行日の候補（; 区切り）": "", "取得方法": "取得不可", "備考": "", "出典URL": "", "施行期日の原文": "",
}


def quote(line, text, header="法律第五号（平一〇・二・一八）"):
    return {"系統": line, "id": "閣法-1-1", "honbun_url": "https://www.shugiin.go.jp/x.htm", "header": header, "fusoku_quote": text}


class ApplyEnforcementTests(unittest.TestCase):
    def test_main_sentence_strips_heading_and_number(self):
        a, _ = main_sentence("（施行期日）\n第一条 この法律は、平成十一年十月一日から施行する。ただし、附則第七条は、公布の日から施行する。")
        b, _ = main_sentence("この法律は、平成十一年十月一日から施行する。ただし、附則第七条は、公布の日から施行する。")
        self.assertEqual(a, b)
        self.assertEqual(a, "この法律は、平成十一年十月一日から施行する。")

    def test_header_must_match_number_and_date(self):
        self.assertTrue(header_matches("法律第五号（平一〇・二・一八）", "平成十年法律第五号", "1998-02-18"))
        self.assertFalse(header_matches("法律第六号（平一〇・二・一八）", "平成十年法律第五号", "1998-02-18"))
        self.assertFalse(header_matches("法律第五号（平一〇・二・一九）", "平成十年法律第五号", "1998-02-18"))

    def test_decree_deadline(self):
        text = "この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。"
        self.assertEqual(decree_deadline(text, "2005-05-06"), "2005-11-06")

    def test_both_lines_must_agree(self):
        rows = [dict(ROW)]
        apply(rows, {"附則": [quote("A", "この法律は、公布の日から施行する。"), quote("B", "この法律は、平成十年四月一日から施行する。")], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "")

    def test_agreeing_lines_set_date(self):
        rows = [dict(ROW)]
        apply(rows, {"附則": [quote("A", "第一条 この法律は、公布の日から施行する。"), quote("B", "この法律は、公布の日から施行する。")], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "1998-02-18")
        self.assertIn("2系統一致", rows[0]["取得方法"])

    def test_candidate_needs_second_fetch_and_period(self):
        base = dict(ROW, 施行期日の原文="この法律は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。")
        first = {"id": "閣法-1-1", "施行日": "1998-04-01", "出典URL": "https://www.mlit.go.jp/a", "原文の引用": "甲法の施行期日を平成十年四月一日とする。"}
        rows = [dict(base)]
        apply(rows, {"附則": [], "省庁資料の候補": [first]})
        self.assertEqual(rows[0]["施行日"], "")
        self.assertIn("1998-04-01", rows[0]["施行日の候補（; 区切り）"])
        rows = [dict(base)]
        second = {"id": "閣法-1-1", "fetched": True, "law_matches": True, "date": "1998-04-01"}
        apply(rows, {"附則": [], "省庁資料の候補": [first], "候補の再取得": [second]})
        self.assertEqual(rows[0]["施行日"], "1998-04-01")
        rows = [dict(base)]
        late = dict(first, 施行日="1998-07-01")
        apply(rows, {"附則": [], "省庁資料の候補": [late], "候補の再取得": [dict(second, date="1998-07-01")]})
        self.assertEqual(rows[0]["施行日"], "")

    def test_halfwidth_middle_dot_is_the_same_heisei_law(self):
        # 閣法-142-20 の制定法律ページ（sha256 b808b82fcad33905b2c60504ec379f3d3bffdd499edff5623e32d830779e9f82）の見出し。
        # 期待する一致・不一致は、この関数の出力を写して作っていない。
        half = "法律第二十九号（平一〇･三･三一）"
        full = "法律第二十九号（平一〇・三・三一）"
        law = "平成十年法律第二十九号"
        day = "1998-03-31"
        self.assertEqual([hex(ord(ch)) for ch in half if ord(ch) in (0x30FB, 0xFF65)], ["0xff65", "0xff65"])
        self.assertEqual([hex(ord(ch)) for ch in full if ord(ch) in (0x30FB, 0xFF65)], ["0x30fb", "0x30fb"])
        self.assertTrue(header_matches(half, law, day))
        self.assertTrue(header_matches(full, law, day))
        self.assertTrue(header_matches("法律第二十九号（平一〇･三・三一）", law, day))
        self.assertFalse(header_matches("法律第三十号（平一〇･三･三一）", law, day))
        self.assertFalse(header_matches("法律第二十九号（平一〇･四･一）", law, day))
        self.assertFalse(header_matches(half, "平成十年法律第三十号", day))
        self.assertFalse(header_matches(half, law, "1998-04-01"))
        self.assertFalse(header_matches("", law, day))
        self.assertFalse(header_matches("法律第二十九号", law, day))
        self.assertFalse(header_matches(half, "", day))
        self.assertFalse(header_matches(half, law, ""))
        self.assertFalse(header_matches("法律第二十九号（昭五一･三･三一）", "昭和五十一年法律第二十九号", "1976-03-31"))
        self.assertFalse(header_matches("法律第九十二号（平二六・六・二七）", law, day))
        self.assertFalse(header_matches("法律第二十九号（平一〇\u00b7三\u00b7三一）", law, day))

    def test_official_explicit_date_follows_when_only_the_dot_width_differs(self):
        half = "法律第二十九号（平一〇･三･三一）"
        full = "法律第二十九号（平一〇・三・三一）"
        text = "この法律は、平成十年四月一日から施行する。"
        row = dict(
            ROW, id="閣法-142-20", 法令番号="平成十年法律第二十九号", 公布日="1998-03-31",
            題名="青年の就農促進のための資金の貸付け等に関する特別措置法の一部を改正する法律案",
        )

        def quote_at(line, header):
            return {
                "系統": line, "id": row["id"],
                "honbun_url": "https://www.shugiin.go.jp/internet/itdb_housei.nsf/html/housei/h142029.htm",
                "header": header, "fusoku_quote": text,
            }

        rows = [dict(row)]
        apply(rows, {"附則": [quote_at("A", half), quote_at("B", full)], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "1998-04-01")
        body, rest = main_sentence(text)
        parsed = parse_koryoku(body, rest, "1998-03-31")
        self.assertEqual(parsed["kind"], "date")
        self.assertEqual(parsed["date"], "1998-04-01")
        self.assertEqual(parsed["others"], [])
        self.assertIsNone(ABBREVIATED.search(row["題名"]))

    def test_year_crossing_decree_stays_empty(self):
        header = "法律第九十二号（平二六・六・二七）"
        text = "この法律は、公布の日から起算して一年を超えない範囲内において政令で定める日から施行する。"
        self.assertEqual(header.count("\u30fb"), 2)
        self.assertTrue(header_matches(header, "平成二十六年法律第九十二号", "2014-06-27"))
        row = dict(ROW, id="衆法-186-36", 法令番号="平成二十六年法律第九十二号", 公布日="2014-06-27")

        def quote_at(line):
            return {
                "系統": line, "id": row["id"],
                "honbun_url": "https://www.shugiin.go.jp/internet/itdb_housei.nsf/html/housei/18620140627092.htm",
                "header": header, "fusoku_quote": text,
            }

        rows = [dict(row)]
        apply(rows, {"附則": [quote_at("A"), quote_at("B")], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "")
        body, rest = main_sentence(text)
        parsed = parse_koryoku(body, rest, "2014-06-27")
        self.assertEqual(parsed["kind"], "decree")
        self.assertEqual(parsed["date"], "")
        self.assertEqual(decree_deadline(text, "2014-06-27"), "2015-06-27")
        self.assertFalse(same_year("2014-06-27", "2015-06-27"))

    def test_showa_header_item_dates_and_abbreviation_stay_unconfirmed(self):
        header = "法律第七号（昭五一・三・三一）"
        text = (
            "この法律は、昭和五十一年四月一日から施行する。ただし、次の各号に掲げる規定は、"
            "当該各号に掲げる日から施行する。一　第一条中地方税法第四百八十九条の改正規定　昭和五十一年六月一日"
        )
        self.assertFalse(header_matches(header, "昭和五十一年法律第七号", "1976-03-31"))
        self.assertFalse(header_matches(header.replace("\u30fb", "\uff65"), "昭和五十一年法律第七号", "1976-03-31"))
        row = dict(
            ROW, id="旧-77-7", 法令番号="昭和五十一年法律第七号", 公布日="1976-03-31",
            題名="地方税法等の一部を改正する法律",
        )

        def quote_at(line):
            return {
                "系統": line, "id": row["id"], "honbun_url": "https://www.shugiin.go.jp/internet/itdb_housei.nsf/html/houritsu/07719760331007.htm",
                "header": header, "fusoku_quote": text,
            }

        rows = [dict(row)]
        apply(rows, {"附則": [quote_at("A"), quote_at("B")], "省庁資料の候補": []})
        self.assertEqual(rows[0]["施行日"], "")
        body, rest = main_sentence(text)
        parsed = parse_koryoku(body, rest, "1976-03-31")
        self.assertEqual(parsed["kind"], "date")
        self.assertEqual(parsed["date"], "1976-04-01")
        self.assertEqual(parsed["others"], ["1976-06-01"])
        self.assertNotEqual(rows[0]["施行日"], parsed["others"][0])
        self.assertIsNotNone(ABBREVIATED.search("地方税法等の一部を改正する法律"))
        self.assertIsNone(ABBREVIATED.search("青年の就農促進のための資金の貸付け等に関する特別措置法の一部を改正する法律"))


STALE_CLAUSES = (
    "ページ冒頭の法律番号・公布日が台帳と合わないため使わない",
    "附則の施行期日の文を読めない",
    "各号ごとに施行（本則の施行日が1つに決まらない）",
)
EGOV_MISSING = "e-Gov 照合（ブラウザ経由）: 確定できず。改正対象・当該法令が e-Gov で見つからない（改称・廃止・保持範囲外）。施行期日を明示した政令の附則も無い"
EGOV_NARROW = "e-Gov 照合（ブラウザ経由）: 確定できず。附則の期限が読めず、改正履歴の日から一つに絞れない。施行期日を明示した政令の附則も無い"
HISTORY = "過去の索引転記で施行日を空にした記録は、現行の施行日を否定しない"
SIMILAR_NEGATIVE = "改正対象の現行法令を特定できないため附則を読めない"


def agreeing(text="この法律は、公布の日から施行する。"):
    return {"附則": [quote("A", text), quote("B", text)], "省庁資料の候補": []}


class StaleNoteTests(unittest.TestCase):
    def test_fusoku_adoption_drops_only_the_three_index_clauses(self):
        rows = [dict(ROW, 備考="；".join([*STALE_CLAUSES, EGOV_MISSING]))]
        apply(rows, agreeing())
        note = rows[0]["備考"]
        self.assertEqual(rows[0]["施行日"], "1998-02-18")
        for clause in STALE_CLAUSES:
            self.assertNotIn(clause, note)
        self.assertIn("衆議院 制定法律の附則で確定（2系統の引用が一致）", note)
        self.assertIn("確定できず", note)
        self.assertIn("見つからない", note)
        self.assertIn("施行期日を明示した政令の附則も無い", note)
        self.assertEqual(note.count(HISTORY), 1)
        self.assertEqual(remarks_after_adoption(note).count(HISTORY), 1)

    def test_egov_narrowing_sentence_is_removed_and_the_limit_stays(self):
        rows = [dict(ROW, 備考="；".join(["附則の施行期日の文を読めない", EGOV_NARROW]))]
        apply(rows, agreeing())
        note = rows[0]["備考"]
        self.assertNotIn("附則の施行期日の文を読めない", note)
        self.assertNotIn("一つに絞れない", note)
        self.assertIn("確定できず", note)
        self.assertIn("施行期日を明示した政令の附則も無い", note)
        self.assertEqual(note.count(HISTORY), 1)

    def test_filled_row_keeps_a_stale_clause(self):
        old = "ページ冒頭の法律番号・公布日が台帳と合わないため使わない"
        rows = [dict(ROW, 施行日="1998-02-18", 備考=old)]
        before = dict(rows[0])
        apply(rows, agreeing())
        self.assertEqual(rows[0], before)

    def test_decree_adoption_drops_a_stale_clause(self):
        base = dict(
            ROW,
            施行期日の原文="この法律は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。",
            備考="附則の施行期日の文を読めない；確定できず",
        )
        first = {"id": "閣法-1-1", "施行日": "1998-04-01", "出典URL": "https://www.mlit.go.jp/a", "原文の引用": "甲法の施行期日を平成十年四月一日とする。"}
        second = {"id": "閣法-1-1", "fetched": True, "law_matches": True, "date": "1998-04-01"}
        rows = [dict(base)]
        apply(rows, {"附則": [], "省庁資料の候補": [first], "候補の再取得": [second]})
        note = rows[0]["備考"]
        self.assertEqual(rows[0]["施行日"], "1998-04-01")
        self.assertIn("省庁の発表で確定（2回の取得で日付が一致、附則の期間内）", note)
        self.assertNotIn("附則の施行期日の文を読めない", note)
        self.assertIn("確定できず", note)
        self.assertEqual(note.count(HISTORY), 1)

    def test_adoption_without_a_stale_clause_adds_no_history(self):
        rows = [dict(ROW, 備考=EGOV_MISSING)]
        apply(rows, agreeing())
        note = rows[0]["備考"]
        self.assertNotIn(HISTORY, note)
        self.assertIn("確定できず", note)
        self.assertIn("無い", note)
        self.assertIn(EGOV_MISSING, note)

    def test_a_similar_negative_sentence_stays(self):
        rows = [dict(ROW, 備考=SIMILAR_NEGATIVE)]
        apply(rows, agreeing())
        note = rows[0]["備考"]
        self.assertIn(SIMILAR_NEGATIVE, note)
        self.assertNotIn(HISTORY, note)

    def test_five_adopted_ledger_notes_do_not_reject_the_current_date(self):
        import csv
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "data/acquired/enforcement-dates/enforcement.csv"
        with path.open(encoding="utf-8", newline="") as f:
            rows = {row["id"]: row for row in csv.DictReader(f)}
        adopted = {
            "閣法-142-20": "1998-04-01",
            "閣法-146-63": "2001-01-06",
            "閣法-162-71": "2005-12-01",
            "閣法-164-53": "2007-04-01",
            "閣法-166-19": "2007-04-01",
        }
        for rid, day in adopted.items():
            note = rows[rid]["備考"]
            self.assertEqual(rows[rid]["施行日"], day)
            self.assertIn("衆議院 制定法律の附則で確定（2系統の引用が一致）", note)
            self.assertIn("確定できず", note)
            self.assertEqual(note.count(HISTORY), 1)
            for clause in (*STALE_CLAUSES, "一つに絞れない"):
                self.assertNotIn(clause, note)
        self.assertIn("ただし書または各号に政令で定める日あり（未確定）", rows["閣法-146-63"]["備考"])
        self.assertIn("ただし書または各号に政令で定める日あり（未確定）", rows["閣法-164-53"]["備考"])
        self.assertEqual(rows["閣法-166-19"]["施行日の候補（; 区切り）"], "2007-04-01")
        self.assertEqual(rows["閣法-154-94"]["施行日"], "")
        self.assertIn(STALE_CLAUSES[0], rows["閣法-154-94"]["備考"])
        self.assertNotIn(HISTORY, rows["閣法-154-94"]["備考"])
        self.assertNotIn("2002-07-04", rows["閣法-154-94"]["施行日"])

    def test_unadopted_candidate_keeps_the_old_clause(self):
        old = "ページ冒頭の法律番号・公布日が台帳と合わないため使わない"
        base = dict(
            ROW,
            施行期日の原文="この法律は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。",
            備考=old,
        )
        first = {"id": "閣法-1-1", "施行日": "1998-04-01", "出典URL": "https://www.mlit.go.jp/a", "原文の引用": "甲法の施行期日を平成十年四月一日とする。"}
        rows = [dict(base)]
        apply(rows, {"附則": [], "省庁資料の候補": [first]})
        self.assertEqual(rows[0]["施行日"], "")
        self.assertIn(old, rows[0]["備考"])
        self.assertNotIn(HISTORY, rows[0]["備考"])
        self.assertIn("施行日に採らない", rows[0]["備考"])


if __name__ == "__main__":
    unittest.main()
