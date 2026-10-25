"""scripts/fetch_monetary.py の読み取り（日銀の時系列 API・BIS・IMF・FRED・金融政策決定会合の公表文）。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import fetch_monetary as fm  # noqa: E402


class Annual(unittest.TestCase):
    def test_mean_needs_twelve_months(self):
        monthly = {f"2024{m:02d}": float(m) for m in range(1, 13)} | {"202501": 5.0}
        self.assertEqual(fm.annual(monthly, "mean"), {2024: 6.5})

    def test_december(self):
        self.assertEqual(fm.annual({"2024-11": 1.0, "2024-12": 2.0, "2025-06": 3.0}, "december"), {2024: 2.0})


class Parsers(unittest.TestCase):
    def test_boj(self):
        body = ("STATUS,200\nNEXTPOSITION,\nSERIES_CODE,NAME_OF_TIME_SERIES_J,SURVEY_DATES,VALUES\n"
                "STRACLUCON,コールレート,202412,0.227\nSTRACLUCON,コールレート,202501,\n").encode("cp932")
        series, nxt = fm.parse_boj(body)
        self.assertEqual(series, {"STRACLUCON": {"202412": 0.227}})
        self.assertEqual(nxt, "")

    def test_boj_error_status(self):
        with self.assertRaises(RuntimeError):
            fm.parse_boj("STATUS,400\n".encode("cp932"))

    def test_bis(self):
        body = b"FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\nM,JP,2025-12,0.75\nM,JP,2025-11,\n"
        self.assertEqual(dict(fm.parse_bis(body)), {"JP": {"2025-12": 0.75}})

    def test_imf_drops_projections_and_other_countries(self):
        body = json.dumps({"values": {"PCPIPCH": {"JPN": {"2024": 2.7, "2025": 3.0, "2026": 2.0}, "ZZZ": {"2024": 1.0}}}}).encode()
        self.assertEqual(fm.parse_imf(body, "PCPIPCH", 2025), {"JPN": {2024: 2.7, 2025: 3.0}})

    def test_fred_skips_missing(self):
        body = b"observation_date,IRLTLT01JPM156N\n2024-01-01,0.7\n2024-02-01,.\n"
        self.assertEqual(fm.parse_fred(body), {"2024-01": 0.7})


class Mpm(unittest.TestCase):
    def test_list(self):
        html = ('<tr><td>2026年&nbsp;1月23日</td><td><a href="/mopo/mpmdeci/mpr_2026/k260123a.pdf">当面の金融政策運営について'
                ' [PDF 200KB]</a></td></tr><tr><td>2026年1月23日</td><td><a href="/x.pdf">（参考）資料</a></td></tr>')
        self.assertEqual(fm.parse_mpm_list(html),
                         [("2026-01-23", "https://www.boj.or.jp/mopo/mpmdeci/mpr_2026/k260123a.pdf", "当面の金融政策運営について")])

    def test_statement_two_dissenters_and_note_marks(self):
        text = ("1．日本銀行は、本日、政策委員会・金融政策決定会合において、次回会合までの金融市場調節方針を、以下のとおり"
                "とすることを決定した（賛成７反対（注）２）。\n（注）賛成：植田委員、氷見野委員、内田委員、野口委員、中川委員、"
                "高田委員、小枝委員。反対：浅田委員、佐藤委員。")
        got = fm.parse_statement(text)
        self.assertEqual(got["賛否"], "賛成7反対2")
        self.assertEqual(got["反対"], ["浅田", "佐藤"])
        self.assertEqual(len(got["賛成"]), 7)
        self.assertTrue(got["決定の要旨"].startswith("日本銀行は、本日"))

    def test_statement_unanimous_without_names(self):
        got = fm.parse_statement("日本銀行は、本日、現状維持とすることを決定した（全員一致（注））。")
        self.assertEqual((got["賛否"], got["賛成"], got["反対"]), ("全員一致", [], []))

    def test_statement_no_dissent(self):
        got = fm.parse_statement("日本銀行は、本日、決定した（賛成２反対０）。（注）賛成：速水委員、藤原委員。反対：なし。")
        self.assertEqual((got["賛否"], got["賛成"], got["反対"]), ("賛成2反対0", ["速水", "藤原"], []))
        # 人数が合わない名簿は結ばない
        self.assertEqual(fm.parse_statement("日本銀行は、本日、決定した（賛成９反対０）。（注）賛成：速水委員。反対：なし。")["賛成"], [])

    def test_statement_names_must_match_the_vote(self):
        # 方針は全員一致、別の議案（国債買入れの減額）に反対1。反対者を方針の採決に付けない
        text = ("日本銀行は、本日、金融市場調節方針を以下のとおりとすることを決定した（全員一致）。長期国債買入れを減額していく方針を決定した"
                "（賛成２反対１）（注）。以上（注）賛成：植田委員、氷見野委員。反対：中村委員。中村委員は、…として反対した。")
        got = fm.parse_statement(text)
        self.assertEqual((got["賛否"], got["賛成"], got["反対"]), ("全員一致", [], []))

    def test_statement_absent_and_abstain_close_the_field(self):
        got = fm.parse_statement("日本銀行は、本日、決定した（全員一致（注））。以上（注）賛成：白川委員、須田委員反対：なし欠席：西村委員（参考）")
        self.assertEqual((got["賛成"], got["反対"], got["欠席"]), (["白川", "須田"], [], ["西村"]))
        got = fm.parse_statement("日本銀行は、本日、決定した（賛成２棄権１）（注1）。（注1）賛成：黒田委員、雨宮委員。棄権：政井委員。なお、政井委員は棄権した。")
        self.assertEqual((got["賛否"], got["賛成"], got["棄権"], got["反対"]), ("賛成2棄権1", ["黒田", "雨宮"], ["政井"], []))
        got = fm.parse_statement("日本銀行は、本日、決定した（賛成１反対１（注1））。（注1）賛成：福井委員反対：岩田委員（注2）日本銀行法第15条")
        self.assertEqual(got["反対"], ["岩田"])

    def test_summary_keeps_what_follows_as_below(self):
        text = ("1．日本銀行は、本日、金融市場調節方針を、以下のとおりとすることを決定した（全員一致）。"
                "無担保コールレート（オーバーナイト物）を、0.5%前後で推移するよう促す。2．補完貸付については…")
        self.assertEqual(fm.parse_statement(text)["決定の要旨"],
                         "日本銀行は、本日、金融市場調節方針を、以下のとおりとすることを決定した(全員一致)。無担保コールレート(オーバーナイト物)を、0.5%前後で推移するよう促す。")

    def test_meeting_statement_skips_supplements(self):
        bodies = {"https://www.boj.or.jp/k160921c.pdf": "目で見る金融緩和",
                  "https://www.boj.or.jp/k160921a.htm": "日本銀行は、本日、新しい枠組みを導入することを決定した（賛成７反対２）。"}

        class Cached:
            def get(self, url):
                return bodies[url].encode()
        docs = [("https://www.boj.or.jp/k160921c.pdf", "目で見る金融緩和の「総括的な検証」"),
                ("https://www.boj.or.jp/k160921a.htm", "金融緩和強化のための新しい枠組み")]
        original = fm.statement_text
        fm.statement_text = lambda body, url: body.decode()
        try:
            doc, info = fm.statement_of_meeting(Cached(), docs)
        finally:
            fm.statement_text = original
        self.assertEqual((doc[0], info["賛否"]), ("https://www.boj.or.jp/k160921a.htm", "賛成7反対2"))


class Fred(unittest.TestCase):
    def test_transient_error_fails_the_phase(self):
        class Broken:
            def get(self, url):
                raise fm.urllib.error.HTTPError(url, 503, "busy", None, None)
        with self.assertRaises(fm.urllib.error.HTTPError):
            fm.fetch_fred(Broken())


if __name__ == "__main__":
    unittest.main()
