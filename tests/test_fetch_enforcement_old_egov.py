import csv
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import fetch_enforcement_old_egov as f


def laws(*items):
    """/laws の応答の形（既存スクリプトが読む項目）。items = (law_id, law_num, title)"""
    return {"laws": [{"law_info": {"law_id": i, "law_num": n}, "revision_info": {"law_title": t}} for i, n, t in items]}


def revs(*items):
    """/law_revisions の応答の形。items = (revision_id, amendment_law_num, enforcement_date)"""
    return {"law_info": {}, "revisions": [
        {"law_revision_id": r, "amendment_law_num": n, "amendment_enforcement_date": d} for r, n, d in items]}


class FakeClient:
    """URL → (status, data)。登録の無い URL は 404（e-Gov に無い）。引いた URL を記録する。"""

    def __init__(self, table):
        self.table, self.calls = table, []

    def get(self, url):
        self.calls.append(url)
        return self.table.get(url, (404, None))


def row(num, title, prom="1976-03-31"):
    return {"回次": "77", "法律番号": "5", "法令番号": num, "公布日": prom, "題名": title,
            "出典URL": "", "一覧URL": ""}


NEW = "昭和五十一年法律第四号"
AMD = "昭和五十一年法律第五号"


class PureFunctionTests(unittest.TestCase):
    def test_target_candidates(self):
        self.assertEqual(f.target_candidates("租税特別措置法の一部を改正する法律"), [["租税特別措置法"]])
        self.assertEqual(f.target_candidates("地方税法等の一部を改正する法律"), [["地方税法等", "地方税法"]])
        self.assertEqual(
            f.target_candidates("都市公園等整備緊急措置法及び都市公園法の一部を改正する法律"),
            [["都市公園等整備緊急措置法及び都市公園法"], ["都市公園等整備緊急措置法"], ["都市公園法"]])
        self.assertEqual(f.target_candidates("国民の福祉を図るための児童福祉法の一部を改正する法律")[0][1], "児童福祉法")
        self.assertEqual(f.target_candidates("昭和五十年度の稲作転換奨励補助金等についての所得税及び法人税の臨時特例に関する法律"), [])

    def test_parse_laws_and_pickers(self):
        ls = f.parse_laws_response(laws(("A", "昭和五十一年法律第四号", "甲法"), ("B", "昭和五十一年法律第四十号", "乙法")))
        self.assertEqual(f.pick_by_law_num(ls, "昭和五十一年法律第四号"), "A")
        self.assertIsNone(f.pick_by_law_num(ls, "昭和五十一年法律第九号"))
        self.assertEqual(f.pick_by_title(ls, "乙法"), ["B"])
        self.assertEqual(f.parse_laws_response(None), [])
        self.assertEqual(f.parse_laws_response({"laws": []}), [])

    def test_original_and_amendment_dates(self):
        own = f.parse_law_num(NEW)
        r = revs(("r3", "昭和六十年法律第一号", "1985-04-01"), ("r1", None, "1976-04-01"))
        self.assertEqual(f.original_enforcement(r, own), (["1976-04-01"], ""))
        d, note = f.original_enforcement(revs(("r3", "昭和六十年法律第一号", "1985-04-01")), own)
        self.assertEqual(d, [])
        self.assertIn("初めの版が無い", note)
        self.assertEqual(f.original_enforcement(revs(("r1", NEW, "1976-05-01")), own)[0], ["1976-05-01"])
        r2 = revs(("a", AMD, "1976-04-01"), ("b", AMD, "1977-01-01"), ("c", "昭和五十一年法律第六号", "1976-09-09"))
        self.assertEqual(f.amendment_enforcement(r2, f.parse_law_num(AMD)), ["1976-04-01", "1977-01-01"])
        self.assertEqual(f.amendment_enforcement({"revisions": [{"amendment_law_num": AMD}]}, f.parse_law_num(AMD)), [])

    def test_calendar_invalid_dates_and_undated_originals(self):
        self.assertFalse(f._valid_date("1976-99-99"))
        self.assertTrue(f._valid_date("1976-04-01"))
        own = f.parse_law_num(NEW)
        # 初めの版の候補に施行日の無い版があれば、取れた日を確定しない
        dates, note = f.original_enforcement(revs(("a", None, "1976-02-20"), ("b", NEW, None)), own)
        self.assertEqual(dates, [])
        self.assertIn("1976-02-20", note)
        # 暦にない日は施行日として扱わず、途中で止まらない
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("T", "昭和三十二年法律第二十六号", "租税特別措置法"))),
            f.revisions_url("T"): (200, revs(("x", AMD, "1976-99-99"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        self.assertEqual(res["date"], "")

    def test_pick_earliest(self):
        self.assertEqual(f.pick_earliest(["1976-04-01"], "1976-03-31"), ("1976-04-01", []))
        d, notes = f.pick_earliest(["1977-01-01", "1976-04-01", "1976-04-01"], "1976-03-31")
        self.assertEqual(d, "1976-04-01")
        self.assertIn("複数の版が一致", notes[0])
        d, notes = f.pick_earliest(["1970-01-01"], "1976-03-31")
        self.assertEqual(d, "")
        self.assertIn("公布日", notes[0])
        self.assertEqual(f.pick_earliest([]), ("", []))


class ResolveTests(unittest.TestCase):
    def test_route_a_new_law(self):
        client = FakeClient({
            f.law_num_url(NEW): (200, laws(("351AC0000000004", NEW, "稲作転換法"))),
            f.revisions_url("351AC0000000004"): (200, revs(("r2", "昭和六十年法律第一号", "1985-04-01"), ("r1", None, "1976-02-20"))),
        })
        res = f.resolve(client, row(NEW, "昭和五十年度の稲作転換奨励補助金等についての所得税及び法人税の臨時特例に関する法律", "1976-02-20"))
        self.assertEqual((res["date"], res["kind"], res["route"]), ("1976-02-20", f.KIND_ORIGINAL, f.ROUTE_A))
        self.assertEqual(len(client.calls), 2)

    def test_route_b_amendment_law(self):
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("332AC0000000026", "昭和三十二年法律第二十六号", "租税特別措置法"))),
            f.revisions_url("332AC0000000026"): (200, revs(("x", AMD, "1976-04-01"), ("y", "昭和五十二年法律第三号", "1977-04-01"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        self.assertEqual((res["date"], res["kind"], res["route"]), ("1976-04-01", f.KIND_AMEND, f.ROUTE_B))
        self.assertEqual(client.calls[0], f.law_num_url(AMD))  # まず (a)

    def test_route_b_checks_every_same_name_law(self):
        # 同名の現行法令が複数あるとき、先頭に版が無くても2番目以降で一致すれば取る
        client = FakeClient({
            f.law_title_url("甲法"): (200, laws(("A1", "昭和二十年法律第一号", "甲法"), ("A2", "昭和二十一年法律第二号", "甲法"))),
            f.revisions_url("A1"): (200, revs(("y", "昭和五十二年法律第三号", "1977-04-01"))),
            f.revisions_url("A2"): (200, revs(("x", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "甲法の一部を改正する法律"))
        self.assertEqual((res["date"], res["route"]), ("1976-04-01", f.ROUTE_B))
        self.assertIn(f.revisions_url("A2"), client.calls)
        # 同名の片方の履歴を取れないと、そちらに早い版があるかもしれないので確定しない
        client = FakeClient({
            f.law_title_url("甲法"): (200, laws(("A1", "昭和二十年法律第一号", "甲法"), ("A2", "昭和二十一年法律第二号", "甲法"))),
            f.revisions_url("A2"): (200, revs(("x", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "甲法の一部を改正する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("1976-04-01", res["reason"])

    def test_route_b_ignores_same_name_laws_made_later(self):
        # 改正法より後に公布された同名の法令（令和七年法律第七十号など）は照合の対象にしない
        client = FakeClient({
            f.law_title_url("甲法"): (200, laws(("A1", "昭和二十年法律第一号", "甲法"), ("A9", "令和七年法律第七十号", "甲法"))),
            f.revisions_url("A1"): (200, revs(("x", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "甲法の一部を改正する法律"))
        self.assertEqual((res["date"], res["route"]), ("1976-04-01", f.ROUTE_B))
        self.assertNotIn(f.revisions_url("A9"), client.calls)

    def test_route_b_matching_version_without_date_is_not_confirmed(self):
        # 同名の片方に当該法令番号の版があるのに施行日が空なら、もう片方の日を確定しない
        client = FakeClient({
            f.law_title_url("甲法"): (200, laws(("A1", "昭和二十年法律第一号", "甲法"), ("A2", "昭和二十一年法律第二号", "甲法"))),
            f.revisions_url("A1"): (200, revs(("y", AMD, None))),
            f.revisions_url("A2"): (200, revs(("x", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "甲法の一部を改正する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("1976-04-01", res["reason"])
        self.assertTrue(any("施行日が無い" in n for n in res["notes"]))

    def test_late_dates_stay_candidates(self):
        # 公布日から2年より後の日（後年の版・未施行の仮の日）は確定しない
        client = FakeClient({
            f.law_num_url(NEW): (200, laws(("L", NEW, "某法"))),
            f.revisions_url("L"): (200, revs(("r1", None, "2017-04-01"))),
        })
        res = f.resolve(client, row(NEW, "某法", "1977-05-20"))
        self.assertEqual(res["date"], "")
        self.assertIn("2017-04-01 は候補", res["reason"])
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("L", "n", "租税特別措置法"))),
            f.revisions_url("L"): (200, revs(("x", AMD, "2117-12-31"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("2117-12-31 は候補", res["reason"])
        self.assertFalse(f.too_late("1978-03-31", "1976-03-31"))
        self.assertTrue(f.too_late("1978-04-01", "1976-03-31"))

    def test_route_b_earliest_of_several(self):
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("L", "n", "租税特別措置法"))),
            f.revisions_url("L"): (200, revs(("x", AMD, "1977-01-01"), ("y", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        # 段階施行の可能性があり、主な施行日を決められないので確定しない（最も早い日は候補）
        self.assertEqual(res["date"], "")
        self.assertIn("1976-04-01 は候補", res["reason"])
        self.assertTrue(any("複数の版が一致" in n for n in res["notes"]))
        # 同じ日の版が複数あるだけなら確定する
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("L", "n", "租税特別措置法"))),
            f.revisions_url("L"): (200, revs(("x", AMD, "1976-04-01"), ("y", AMD, "1976-04-01"))),
        })
        self.assertEqual(f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))["date"], "1976-04-01")

    def test_route_b_etc_title_and_parts(self):
        client = FakeClient({
            f.law_title_url("地方税法"): (200, laws(("T", "n", "地方税法"))),
            f.revisions_url("T"): (200, revs(("x", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "地方税法等の一部を改正する法律"))
        # 「等」で省いた改正対象は照合できないので確定しない。地方税法側の日は候補として理由に残す
        self.assertEqual(res["date"], "")
        self.assertIn("1976-04-01", res["reason"])
        client = FakeClient({
            f.law_title_url("都市公園法"): (200, laws(("P", "n", "都市公園法"))),
            f.revisions_url("P"): (200, revs(("x", AMD, "1976-06-01"))),
        })
        res = f.resolve(client, row(AMD, "都市公園等整備緊急措置法及び都市公園法の一部を改正する法律"))
        # 片方の対象しか照合できないときは確定しない（欠けた側の方が早いかもしれない）。取れた日は候補として理由に残す
        self.assertEqual(res["date"], "")
        self.assertIn("1976-06-01", res["reason"])
        self.assertTrue(any("都市公園等整備緊急措置法" in n and "無い" in n for n in res["notes"]))
        client = FakeClient({
            f.law_title_url("都市公園等整備緊急措置法"): (200, laws(("Q", "n", "都市公園等整備緊急措置法"))),
            f.revisions_url("Q"): (200, revs(("x", AMD, "1976-05-01"))),
            f.law_title_url("都市公園法"): (200, laws(("P", "n", "都市公園法"))),
            f.revisions_url("P"): (200, revs(("x", AMD, "1976-06-01"))),
        })
        res = f.resolve(client, row(AMD, "都市公園等整備緊急措置法及び都市公園法の一部を改正する法律"))
        # 全部の対象が照合できても、対象ごとに日が違えば主な施行日を決められないので確定しない
        self.assertEqual(res["date"], "")
        self.assertIn("1976-05-01 は候補", res["reason"])

    def test_a_found_without_original_falls_to_b(self):
        client = FakeClient({
            f.law_num_url(AMD): (200, laws(("Z", AMD, "何か"))),
            f.revisions_url("Z"): (200, revs(("r", "昭和六十年法律第一号", "1985-04-01"))),
            f.law_title_url("租税特別措置法"): (200, laws(("L", "n", "租税特別措置法"))),
            f.revisions_url("L"): (200, revs(("x", AMD, "1976-04-01"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        self.assertEqual((res["date"], res["route"]), ("1976-04-01", f.ROUTE_B))
        self.assertTrue(any("取れない" in n for n in res["notes"]))

    def test_c_not_in_egov(self):
        res = f.resolve(FakeClient({}), row(NEW, "昭和五十年度の稲作転換奨励補助金等についての臨時特例に関する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("特定できない", res["reason"])
        out = f.result_to_row(row(NEW, "題名"), res)
        self.assertEqual(out["施行日"], "")
        self.assertIn(f.R16, out["備考"])
        self.assertEqual(list(out), f.OUT_COLS)

    def test_c_no_matching_revision(self):
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("L", "n", "租税特別措置法"))),
            f.revisions_url("L"): (200, revs(("y", "昭和五十二年法律第三号", "1977-04-01"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("版が無い", res["reason"])
        self.assertIn(f.R16, f.result_to_row(row(AMD, "x"), res)["備考"])

    def test_c_target_missing_and_before_promulgation(self):
        res = f.resolve(FakeClient({}), row(AMD, "存在しない法の一部を改正する法律"))
        self.assertIn("e-Gov に無い", res["reason"])
        client = FakeClient({
            f.law_title_url("租税特別措置法"): (200, laws(("L", "n", "租税特別措置法"))),
            f.revisions_url("L"): (200, revs(("x", AMD, "1970-01-01"))),
        })
        res = f.resolve(client, row(AMD, "租税特別措置法の一部を改正する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("公布日より前", res["reason"])

    def test_bad_law_num(self):
        res = f.resolve(FakeClient({}), row("不明", "甲法の一部を改正する法律"))
        self.assertEqual(res["date"], "")
        self.assertIn("読めない", res["reason"])

    def test_fetch_failure_is_not_marked_r16(self):
        out = f.result_to_row(row(NEW, "x"), {"date": "", "kind": "", "route": "", "urls": [], "notes": ["e"], "reason": f.FETCH_FAILED})
        self.assertNotIn("R16", out["備考"])


class _Body:
    status = 200

    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ClientTests(unittest.TestCase):
    def test_unreadable_200_is_set_aside_and_fetched_again(self):
        # HTTP 200 の HTML は控えに残さず、通信失敗として次の実行で取り直す
        url = f.law_num_url(NEW)
        html = mock.MagicMock(status=200)
        html.__enter__.return_value = html
        html.read.return_value = b"<html>busy</html>"
        with tempfile.TemporaryDirectory() as d:
            client = f.Client(Path(d) / "raw", Path(d) / "manifest.csv", 0, Path(d) / "materials")
            with mock.patch.object(urllib.request, "urlopen", return_value=html), mock.patch.object(f.time, "sleep"):
                with self.assertRaises(f.FetchError):
                    client.get(url)
            self.assertIsNone(client.cached(url))
            self.assertFalse((Path(d) / "manifest.csv").exists())
            with mock.patch.object(urllib.request, "urlopen", return_value=_Body({"laws": []})):
                self.assertEqual(client.get(url), (200, {"laws": []}))
            self.assertIsNotNone(client.cached(url))

    def test_dry_run_check_does_not_move_a_broken_copy(self):
        url = f.law_num_url(NEW)
        with tempfile.TemporaryDirectory() as d:
            client = f.Client(Path(d) / "raw", Path(d) / "manifest.csv", 0, Path(d) / "materials")
            p = client._path(url)
            p.parent.mkdir(parents=True)
            p.write_bytes(b"<html>busy</html>")
            self.assertIsNone(client.cached(url, repair=False))
            self.assertTrue(p.exists())

    def test_other_copy_of_the_same_url_is_registered(self):
        # 控えの置き場を変えて同じ URL の別の本文を使うときも、manifest にその本文を登録する
        url = f.law_num_url(NEW)
        with tempfile.TemporaryDirectory() as d:
            manifest, materials = Path(d) / "manifest.csv", Path(d) / "materials"
            for raw, body in (("raw1", {"laws": []}), ("raw2", {"laws": [], "x": 1})):
                client = f.Client(Path(d) / raw, manifest, 0, materials)
                p = client._path(url)
                p.parent.mkdir(parents=True)
                p.write_text(json.dumps(body), encoding="utf-8")
                client.get(url)
                client.get(url)  # 同じ本文は2度登録しない
            rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({r["sha256"] for r in rows}), 2)

    def test_prior_manifest_keeps_the_first_fetch_time(self):
        # 控えから manifest を作り直すとき、前の manifest に同じ URL・置き場所・中身の行があれば HTTP と取得時刻を引き継ぐ
        url = f.law_num_url(NEW)
        with tempfile.TemporaryDirectory() as d:
            raw, materials = Path(d) / "raw", Path(d) / "materials"
            body = json.dumps({"laws": []}).encode("utf-8")
            client = f.Client(raw, Path(d) / "m1.csv", 0, materials)
            p = client._path(url)
            p.parent.mkdir(parents=True)
            p.write_bytes(body)
            prior = Path(d) / "prior.csv"
            with prior.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(f.MANIFEST_COLS)
                w.writerow([url, f._rel(p), f.hashlib.sha256(body).hexdigest(), 200, "2026-10-18T09:00:00+00:00", "x"])
            client = f.Client(raw, Path(d) / "m2.csv", 0, materials, prior=prior)
            client.get(url)
            row = next(csv.DictReader((Path(d) / "m2.csv").open(encoding="utf-8")))
            self.assertEqual((row["http"], row["fetched_at"]), ("200", "2026-10-18T09:00:00+00:00"))


class CliTests(unittest.TestCase):
    def write_input(self, d):
        p = Path(d) / "in.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["回次", "法律番号", "法令番号", "公布日", "題名", "出典URL", "一覧URL"])
            w.writerow(["77", "4", NEW, "1976-02-20", "稲作転換の臨時特例に関する法律", "", ""])
            # 会期が年をまたぐと法律番号が振り直され、（回次, 法律番号）が重なる。法令番号で区別する
            w.writerow(["77", "4", AMD, "1976-03-31", "租税特別措置法の一部を改正する法律", "", ""])
        return p

    def test_dry_run_makes_no_requests_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_input(d)
            out, raw = Path(d) / "out", Path(d) / "raw"
            buf, err = io.StringIO(), io.StringIO()
            with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("通信した")) as m, \
                    redirect_stdout(buf), redirect_stderr(err):
                rc = f.main(["--input", str(p), "--out-dir", str(out), "--raw-dir", str(raw), "--dry-run", "--limit", "2"])
            self.assertEqual(rc, 0)
            m.assert_not_called()
            self.assertFalse(out.exists())
            self.assertFalse(raw.exists())
            self.assertIn("law_num=", buf.getvalue())
            self.assertIn("租税特別措置法", buf.getvalue())

    def test_run_resume_and_limit(self):
        table = {
            f.law_num_url(NEW): laws(("N", NEW, "稲作")),
            f.revisions_url("N"): revs(("r", None, "1976-02-20")),
        }
        with tempfile.TemporaryDirectory() as d:
            p = self.write_input(d)
            out = Path(d) / "out"
            args = ["--input", str(p), "--out-dir", str(out), "--raw-dir", str(Path(d) / "raw"), "--sleep", "0"]

            def fake(req, timeout=0):
                if req.full_url not in table:
                    raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"{}"))
                return _Body(table[req.full_url])

            materials = Path(d) / "materials"
            with mock.patch.object(urllib.request, "urlopen", side_effect=fake) as m, \
                    mock.patch.object(f, "MATERIALS", materials), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(f.main(args + ["--limit", "1"]), 0)
                first_calls = m.call_count
                rows = list(csv.DictReader((out / "enforcement_old.csv").open(encoding="utf-8")))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["施行日"], "1976-02-20")
                self.assertEqual(f.main(args), 0)  # 全件。最初の1本の URL は取り直さない
                rows = list(csv.DictReader((out / "enforcement_old.csv").open(encoding="utf-8")))
                self.assertEqual(len(rows), 2)
                self.assertEqual([r["法令番号"] for r in rows], [NEW, AMD])
                self.assertEqual(rows[1]["施行日"], "")
                self.assertIn(f.R16, rows[1]["備考"])
                urls = [c.args[0].full_url for c in m.call_args_list]
                self.assertEqual(len(urls), len(set(urls)))
                self.assertGreater(m.call_count, first_calls)
            man = list(csv.DictReader((out / "manifest.csv").open(encoding="utf-8")))
            self.assertEqual(list(man[0]), f.MANIFEST_COLS)
            self.assertEqual(len(man), len(set(r["url"] for r in man)))
            # リポジトリの外の控えはファイル名だけを残し、原本は外部資料として登録する（初期状態 unverified）
            self.assertTrue(all("/" not in r["path"] for r in man))
            records = {r.parent.name: json.loads(r.read_text(encoding="utf-8"))
                       for r in (materials / f.TASK_ID).glob("*/record.json")}
            self.assertEqual({r["material_id"] for r in man}, set(records))
            self.assertTrue(all(r["content_verification"] == "unverified" for r in records.values()))

    def test_fetch_failure_keeps_the_previous_result(self):
        # 別の控えの置き場で通信に失敗しても、前回取れた施行日を消さない
        table = {f.law_num_url(NEW): laws(("N", NEW, "稲作")), f.revisions_url("N"): revs(("r", None, "1976-02-20"))}
        with tempfile.TemporaryDirectory() as d:
            p = self.write_input(d)
            out = Path(d) / "out"
            args = ["--input", str(p), "--out-dir", str(out), "--sleep", "0", "--limit", "1"]

            def fake(req, timeout=0):
                return _Body(table[req.full_url])

            with mock.patch.object(f, "MATERIALS", Path(d) / "materials"), mock.patch.object(f.time, "sleep"), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with mock.patch.object(urllib.request, "urlopen", side_effect=fake):
                    self.assertEqual(f.main(args + ["--raw-dir", str(Path(d) / "raw")]), 0)
                with mock.patch.object(urllib.request, "urlopen", side_effect=urllib.error.URLError("down")):
                    # 5本続かない単発の失敗でも、未取得が残れば非ゼロで終える
                    self.assertEqual(f.main(args + ["--raw-dir", str(Path(d) / "raw2")]), 1)
            rows = list(csv.DictReader((out / "enforcement_old.csv").open(encoding="utf-8")))
            self.assertEqual([(r["法令番号"], r["施行日"]) for r in rows], [(NEW, "1976-02-20")])

    def test_help(self):
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()) as buf:
            f.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--dry-run", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
