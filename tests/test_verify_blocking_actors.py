import unittest
from pathlib import Path

from scripts.fetch_blocking_originals import html_text
from scripts.verify_blocking_actors import CONFIRMED, PROVISIONAL, apply_status, decide, line_a_row, norm, row_hash

ORIGINAL = norm(
    "受付番号 260425001 受付日 平成26年4月25日 提案事項 総量規制の緩和 提案主体 個人 所管省庁 金融庁 "
    "対応の分類 対応不可 総量規制は、借り手の返済能力を超える貸付けを抑制するための制度であり、"
    "改正貸金業法のフォローアップにおいても見直しが必要となる実態は確認されていない。"
)


def doc(text=ORIGINAL):
    return {"text": text, "starts": [0], "sha": "x", "pdf": True}


ROW = {
    "受付番号": "260425001", "提案事項": "総量規制の緩和", "所管省庁": "金融庁", "対応分類": "対応不可",
    "回答の理由（要旨）": "総量規制は返済能力の範囲に借入を抑える制度で、改正貸金業法のフォローアップでも見直しが必要な実態は確認されなかった。",
    "ページ": "不明", "確度": PROVISIONAL,
}


class LineATest(unittest.TestCase):
    def test_matching_row(self):
        self.assertEqual(line_a_row("1_regulatory-requests/hotline.csv", ROW, doc())["系統A"], "一致")

    def test_wrong_label(self):
        r = dict(ROW, 対応分類="現行制度下で対応可能")
        res = line_a_row("1_regulatory-requests/hotline.csv", r, doc())
        self.assertEqual(res["系統A"], "不一致")
        self.assertIn("対応分類", res["理由"])

    def test_missing_number(self):
        r = dict(ROW, 受付番号="999999999")
        self.assertEqual(line_a_row("1_regulatory-requests/hotline.csv", r, doc())["誤りの型"], "値が原本に無い")


class DecideTest(unittest.TestCase):
    def test_needs_two_ai_readers(self):
        self.assertEqual(decide({"系統A": "一致"}, {"判定": "一致"}, {"判定": "一致"})[0], "確認済み")
        # ページ違いが残る行は、中身が一致でも保留
        v, kind, _ = decide({"系統A": "一致", "誤りの型": "ページ違い", "理由": "記載p.6・原本p.8"}, {"判定": "一致"}, {"判定": "一致"})
        self.assertEqual((v, kind), ("保留", "ページ違い"))
        v, kind, _ = decide({"系統A": "一致"}, {"判定": "一致"})
        self.assertEqual((v, kind), ("保留", "2人目のAIの読み待ち"))
        v, _, why = decide({"系統A": "一致"}, {"判定": "一致"}, {"判定": "不一致", "理由": "原本は対応可能"})
        self.assertEqual(v, "保留")
        self.assertIn("原本は対応可能", why)

    def test_disagree_is_held_with_reason(self):
        v, kind, why = decide({"系統A": "一致"}, {"判定": "不一致", "誤りの型": "分類違い", "理由": "原本は対応可能"})
        self.assertEqual((v, kind), ("保留", "分類違い"))
        self.assertIn("原本は対応可能", why)

    def test_no_original(self):
        self.assertEqual(decide({"系統A": "原本なし", "理由": "x"}, None)[0], "未照合")

    def test_apply_status(self):
        rel = "1_regulatory-requests/hotline.csv"
        rows = [dict(ROW)]
        st = {row_hash(rel, ROW): {"照合": "確認済み", "誤りの型": ""}}
        apply_status(None, rel, list(ROW), rows, st)
        self.assertEqual(rows[0]["確度"], CONFIRMED)


class HtmlTextTest(unittest.TestCase):
    def test_shift_jis(self):
        raw = '<html><meta charset="Shift_JIS"><script>x</script><p>民泊の条例</p></html>'.encode("cp932")
        self.assertEqual(html_text(raw).strip(), "民泊の条例")


class MaskAndStatusTest(unittest.TestCase):
    def test_mask_names_hides_person_before_title(self):
        from scripts.verify_blocking_actors import mask_names
        self.assertEqual(mask_names("小川参考人の発言"), "（氏名略）参考人の発言")
        self.assertNotIn("佐々", mask_names("佐々木委員は"))
        self.assertNotIn("鈴木", mask_names("鈴木 太郎 委員"))
        self.assertEqual(mask_names("検討委員会の議論"), "検討委員会の議論")

    def test_decide_masks_kind_and_line_a_reason(self):
        _, kind, why = decide({"系統A": "一致", "理由": ""}, {"判定": "不一致", "誤りの型": "井上委員の発言を取り違え", "理由": ""})
        self.assertNotIn("井上", kind)

    def test_apply_status_labels_and_keeps_note_on_unverified_rows(self):
        from pathlib import Path
        rel = "2_shingikai/x.csv"
        a = {"出典URL": "https://example.go.jp/a.pdf", "要旨": "x", "確度": "webfetch要約・暫定（発言者特定不可）"}
        b = {"出典URL": "https://example.go.jp/a.pdf", "要旨": "y", "確度": PROVISIONAL}
        c = {"出典URL": "https://example.go.jp/a.pdf", "要旨": "z", "確度": CONFIRMED}
        st = {row_hash(rel, a): {"照合": "未照合", "誤りの型": ""}, row_hash(rel, b): {"照合": "保留", "誤りの型": "抜粋が別の箇所"}}
        apply_status(Path("x"), rel, list(a), [a, b, c], st)
        self.assertEqual(a["確度"], "webfetch要約・暫定（発言者特定不可）")
        self.assertEqual(b["確度"], "保留：抜粋が別の箇所")
        self.assertEqual(c["確度"], PROVISIONAL)


class LawCitationTest(unittest.TestCase):
    def test_parse_citation(self):
        from scripts.check_blocking_laws_egov import parse_citation
        self.assertEqual(parse_citation("農地法第2条、第3条"), [("農地法", "2"), ("農地法", "3")])
        self.assertEqual(parse_citation("道路運送法第七十八条の二"), [("道路運送法", "78_2")])

    def test_title_with_comma_is_not_split(self):
        from scripts.check_blocking_laws_egov import check_row
        title = "医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律"
        cat = [{"id": "X", "type": "Act", "title": title, "abbrev": [], "repeal": None}]
        verdict, note = check_row(title + "第14条", cat, {"X": {"14"}}, 0)
        self.assertEqual(verdict, "実在（条も確認）")

    def test_same_law_subordinate_is_checked(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "職業安定法", "abbrev": [], "repeal": None},
               {"id": "R", "type": "MinisterialOrdinance", "title": "職業安定法施行規則", "abbrev": [], "repeal": None}]
        verdict, note = check_row("職業安定法第33条の3、同施行規則第25条の3", cat, {"A": {"33_3"}, "R": {"24"}}, 0)
        self.assertEqual(verdict, "条が見つからない")
        self.assertIn("職業安定法施行規則第25条の3=現行に無い", note)
        verdict, _ = check_row("職業安定法第33条の3、同施行規則第25条の3", cat, {"A": {"33_3"}, "R": {"25_3"}}, 0)
        self.assertEqual(verdict, "実在（条も確認）")

    def test_notice_beside_law_is_unverified(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "銀行法", "abbrev": [], "repeal": None}]
        verdict, note = check_row("銀行法第10条、主要行等向けの総合的な監督指針", cat, {"A": {"10"}}, 0)
        self.assertEqual(verdict, "一部未確認（条例・附則・告示など）", note)

    def test_unparsed_part_is_unverified(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "地方税法", "abbrev": [], "repeal": None}]
        verdict, note = check_row("地方税法第22条、固定資産税", cat, {"A": {"22"}}, 0)
        self.assertEqual(verdict, "一部未確認（条例・附則・告示など）", note)
        self.assertIn("固定資産税=未確認", note)

    def test_ordinance_is_not_counted_as_verified(self):
        from scripts.check_blocking_laws_egov import check_row
        self.assertEqual(check_row("京都市旅館業条例", [], {}, 0)[0], "一部未確認（条例・附則・告示など）")

    def test_dot_list_range_and_suppl(self):
        from scripts.check_blocking_laws_egov import SUPPL, parse_citation
        self.assertEqual(parse_citation("農地法第30条・第32条"), [("農地法", "30"), ("農地法", "32")])
        self.assertEqual(parse_citation("民法第7条〜第9条"), [("民法", "7"), ("民法", "8"), ("民法", "9")])
        self.assertEqual(parse_citation("老人福祉法第5条、同法附則第6条の2")[1], ("同法", SUPPL))

    def test_etc_inside_law_part_is_leftover(self):
        from scripts.check_blocking_laws_egov import parse_citation
        for s in ("介護保険法等", "道路運送法第22条等", "特許法第107条第5項、第195条第8項等", "薬機法改正案"):
            rest = []
            parse_citation(s, rest)
            self.assertEqual(rest, [s.split("、")[-1]] if "、" in s else [s])
        rest = []
        parse_citation("医療法等の一部を改正する法律第3条", rest)
        self.assertEqual(rest, [])
        parse_citation("道路交通法第2条第1項第9号、第3条ただし書", rest)
        self.assertEqual(rest, [])

    def test_browser_kit_binds_row_to_its_own_original(self):
        kit = (Path(__file__).resolve().parents[1] / "scripts/browser/blocking_verify_kit.js").read_text(encoding="utf-8")
        self.assertIn("getk('doc:'+x.url)", kit)  # 読み手の抜粋は行の出典URLの原本からだけ取る
        self.assertIn("d.sha===x.sha", kit)
        self.assertIn("at:new Date().toISOString()", kit)  # 原本を取った時刻を残す
        self.assertIn("M.V!==V", kit)  # 読み手に見せる版は、束を作ったときの版だけ
        self.assertIn("V=M.V+'@'+M.ref", kit)  # 版に CSV の ref も付ける
        self.assertIn("'版|'+window.RUN_V+'|'+window.RUN_REF", kit)

    def test_bracket_bill_and_other_ordinance_are_leftovers(self):
        from scripts.check_blocking_laws_egov import parse_citation
        rest = []
        parse_citation("旅館業法、住宅宿泊事業法（案）", rest)
        self.assertEqual(rest, ["(案)"])
        rest = []
        parse_citation("農地法第3条（許可要件）", rest)
        self.assertEqual(rest, [])
        for draft in ("旅館業法（改正案）", "旅館業法（省令案）"):
            rest = []
            parse_citation(draft, rest)
            self.assertEqual(len(rest), 1, draft)
        for name in ("旅館業法（提案名）", "旅館業法（答申案件）"):
            rest = []
            parse_citation(name, rest)  # 「案」を含むだけの語は草案の印ではない
            self.assertEqual(rest, [], name)

    def test_old_title_resolves_only_when_history_has_it(self):
        import tempfile
        from unittest import mock
        from scripts import check_blocking_laws_egov as e
        old = "住民基本台帳の一部の写しの閲覧及び住民票の写し等の交付に関する省令"
        cur = {"id": "360M50000008028", "type": "MinisterialOrdinance", "title": "新しい題名", "abbrev": [], "repeal": None}
        for history, found in (([old, "新しい題名"], True), (["新しい題名"], False)):
            cat = [dict(cur)]
            with tempfile.TemporaryDirectory() as d, \
                    mock.patch.object(e, "get_json", return_value={"revisions": [{"law_title": t} for t in history]}):
                e.add_old_titles(cat, Path(d), 0)
            self.assertEqual(e.resolve(old, cat) is not None, found)
            if found:
                self.assertEqual(e.resolve(old, cat)["id"], cur["id"])

    def test_sentence_boundary_and_same_law_order(self):
        from scripts.check_blocking_laws_egov import parse_citation
        self.assertEqual([n for n, _ in parse_citation("家庭用品品質表示法第3条。有害物質を含有する家庭用品の規制に関する法律第4条")],
                         ["家庭用品品質表示法", "有害物質を含有する家庭用品の規制に関する法律"])

    def test_same_law_cabinet_order_name(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "水質汚濁防止法", "abbrev": [], "repeal": None},
               {"id": "C", "type": "CabinetOrder", "title": "水質汚濁防止法施行令", "abbrev": [], "repeal": None}]
        verdict, note = check_row("水質汚濁防止法第3条、同法施行令第1条", cat, {"A": {"3"}, "C": {"1"}}, 0)
        self.assertEqual(verdict, "実在（条も確認）", note)

    def test_same_rule_resolves_to_formal_name(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "労働安全衛生法", "abbrev": [], "repeal": None},
               {"id": "R", "type": "MinisterialOrdinance", "title": "労働安全衛生規則", "abbrev": [], "repeal": None}]
        verdict, note = check_row("労働安全衛生法第20条、同規則第51条", cat, {"A": {"20"}, "R": {"51"}}, 0)
        self.assertEqual(verdict, "実在（条も確認）", note)

    def test_every_citation_in_a_part(self):
        from scripts.check_blocking_laws_egov import parse_citation
        self.assertEqual(parse_citation("行政書士法第1条の2（第19条も参照）"), [("行政書士法", "1_2"), ("行政書士法", "19")])
        self.assertEqual(parse_citation("民法第7条〜第90条"), [("民法", str(n)) for n in range(7, 91)])
        self.assertEqual(parse_citation("民法第843条第1項・第4項"), [("民法", "843")])

    def test_same_ministerial_ordinance(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "労働安全衛生法", "abbrev": [], "repeal": None},
               {"id": "R", "type": "MinisterialOrdinance", "title": "労働安全衛生規則", "abbrev": [], "repeal": None}]
        verdict, note = check_row("労働安全衛生法第20条、同省令第19条の22", cat, {"A": {"20"}, "R": {"19_22"}}, 0)
        self.assertEqual(verdict, "実在（条も確認）", note)


class MergeRowTest(unittest.TestCase):
    A = {"系統A": "一致", "原本sha256": "s1", "理由": ""}
    OK = {"判定": "一致"}

    def test_reader_answers_need_matching_pin(self):
        from scripts.verify_blocking_actors import merge_row
        self.assertEqual(merge_row(self.A, self.OK, self.OK, "s1")[2][0], "確認済み")
        self.assertNotEqual(merge_row(self.A, self.OK, self.OK, None)[2][0], "確認済み")
        self.assertNotEqual(merge_row(self.A, self.OK, self.OK, "s2")[2][0], "確認済み")

    def test_answer_from_other_version_is_dropped(self):
        from scripts.verify_blocking_actors import merge_row
        old = {"判定": "一致", "原本sha256": "s0"}
        self.assertNotEqual(merge_row(self.A, old, self.OK, "s1")[2][0], "確認済み")

    def test_batch_answer_without_version_is_dropped(self):
        from scripts.verify_blocking_actors import merge_row
        hashless = {"判定": "一致", "行ハッシュ": "h"}
        self.assertNotEqual(merge_row(self.A, hashless, self.OK, "s1")[2][0], "確認済み")

    def test_duplicate_rows_are_held(self):
        from scripts.verify_blocking_actors import merge_row
        v, kind, _ = merge_row(self.A, self.OK, self.OK, "s1", dup=2)[2]
        self.assertEqual((v, kind), ("保留", "重複行"))


class SnapshotTest(unittest.TestCase):
    def test_changed_rows_move_old_answers_away(self):
        import json
        import tempfile
        from pathlib import Path
        from scripts.verify_blocking_actors import write_snapshot
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            (w / "b-results").mkdir()
            (w / "b-results" / "a.json").write_text("[]", encoding="utf-8")
            (w / "snapshot.json").write_text(json.dumps({"x.csv|3": "oldhash"}), encoding="utf-8")
            (w / "b-batches").mkdir()
            write_snapshot(w)
            self.assertFalse((w / "b-results").exists())
            self.assertFalse((w / "b-batches").exists())
            self.assertEqual(len(list(w.glob("old-snapshot-*/b-results/a.json"))), 1)
            # 同じ古い対応にもう一度戻して作り直しても、別の退かし先になる
            (w / "b-results").mkdir()
            (w / "snapshot.json").write_text(json.dumps({"x.csv|3": "oldhash"}), encoding="utf-8")
            write_snapshot(w)
            self.assertEqual(len(list(w.glob("old-snapshot-*/b-results"))), 2)

    def test_new_pin_keeps_answers(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        from scripts import verify_blocking_actors as v
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            rows = [("x/a.csv", 1, {"出典URL": "u1", "v": "1"})]
            with mock.patch.object(v, "load_rows", return_value=rows):
                (w / "lineA.csv").write_text("出典URL,原本sha256\nu1,s1\n", encoding="utf-8")
                v.write_snapshot(w)
                sid = json.loads((w / "snapshot.json").read_text(encoding="utf-8"))["__版__"]
                (w / "b-results").mkdir()
                (w / "lineA.csv").write_text("出典URL,原本sha256\nu1,s1\nu2,s2\n", encoding="utf-8")
                v.write_snapshot(w)  # 新しい URL の版が増えただけ
                self.assertTrue((w / "b-results").exists())
                snap = json.loads((w / "snapshot.json").read_text(encoding="utf-8"))
                self.assertEqual((snap["__版__"], snap["__原本__"]["u2"]), (sid, "s2"))
                (w / "lineA.csv").write_text("出典URL,原本sha256\nu1,s9\nu2,s2\n", encoding="utf-8")
                v.write_snapshot(w)  # 既にある原本の版が変わった
                self.assertFalse((w / "b-results").exists())
                snap = json.loads((w / "snapshot.json").read_text(encoding="utf-8"))
                self.assertNotEqual(snap["__版__"], sid)  # 行が同じでも、退かす前の答えの版とは別になる
                gen = snap["__版__"]
                (w / "b-results").mkdir()
                (w / "lineA.csv").write_text("出典URL,原本sha256\nu1,s9\nu2,s2\nu3,s3\n", encoding="utf-8")
                v.write_snapshot(w)  # 世代を持ったまま、新しい URL の版を足すだけ
                self.assertTrue((w / "b-results").exists())
                self.assertEqual(json.loads((w / "snapshot.json").read_text(encoding="utf-8"))["__版__"], gen)

    def test_article_time_only_when_fetched(self):
        from scripts.check_blocking_laws_egov import check_row
        cat = [{"id": "A", "type": "Act", "title": "農地法", "abbrev": [], "repeal": None}]
        got: list = []
        check_row("農地法", cat, {}, 0, got)
        self.assertEqual(got, [])
        got = []
        check_row("農地法第3条", cat, {"A": {"3"}, ("観測", "A"): "2026-10-17T00:00:00Z"}, 0, got)
        self.assertEqual(got, ["2026-10-17T00:00:00Z"])

    def test_browser_version_must_match_snapshot_and_csv_ref(self):
        import subprocess
        from scripts import verify_blocking_actors as v
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=v.ROOT).stdout.strip()
        snap = {f"{rel}|{i}": v.row_hash(rel, r) for rel, i, r in v.load_rows()}
        snap[v.SNAP_ID_KEY] = v.snapshot_id(snap)
        clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(v.DATA)], cwd=v.ROOT).returncode == 0
        if clean:
            self.assertTrue(v.answer_version_ok(snap, f"{snap[v.SNAP_ID_KEY]}@{head}"))
        self.assertFalse(v.answer_version_ok(snap, f"{snap[v.SNAP_ID_KEY]}@0000000"))  # 無い ref
        self.assertFalse(v.answer_version_ok(snap, f"違う版@{head}"))
        self.assertFalse(v.answer_version_ok(snap, snap[v.SNAP_ID_KEY]))  # ref の無い新しい答えは受け付けない
        self.assertTrue(v.answer_version_ok(snap, snap[v.SNAP_ID_KEY], legacy=True))  # 一覧に載った照合前の答え
        shifted = dict(snap)
        shifted["x/a.csv|1"] = "0" * 16  # ref の CSV と行の対応が違う
        self.assertFalse(v.ref_matches(shifted, head))

    def test_import_a_refuses_without_matching_version_line(self):
        import json
        import tempfile
        from scripts import verify_blocking_actors as v
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            (w / "snapshot.json").write_text(json.dumps({"x/a.csv|1": "h", v.SNAP_ID_KEY: "abc"}), encoding="utf-8")
            t = w / "a.txt"
            for body in ("x/a.csv|1|一致|||1|1|0\n", "版|違う|0000000\nx/a.csv|1|一致|||1|1|0\n"):
                t.write_text(body, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    v.cmd_import_a(w, [t], "2026-10-18")
            self.assertFalse((w / "lineA.csv").exists())

    def test_answer_binds_to_snapshot_hash_not_current_line(self):
        import json
        import tempfile
        from pathlib import Path
        from scripts.verify_blocking_actors import load_b
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            (w / "b-results").mkdir()
            (w / "snapshot.json").write_text(json.dumps({"x.csv|3": "oldhash", "__版__": "v1"}), encoding="utf-8")
            a = w / "b-results" / "a.json"
            a.write_text(json.dumps([{"ファイル": "x.csv", "行": 3, "判定": "一致", "版": "v1"}]), encoding="utf-8")
            import hashlib
            listed = {("b-results", "a.json", hashlib.sha256(a.read_bytes()).hexdigest(), "v1")}
            self.assertEqual(list(load_b(w, legacy=listed)), ["oldhash"])
            # ref の無い版は、照合前の答えの一覧に中身ごと載っていなければ結び付けない
            self.assertEqual(list(load_b(w, legacy=set())), [])
            a.write_text(json.dumps([{"ファイル": "x.csv", "行": 3, "判定": "不一致", "版": "v1"}]), encoding="utf-8")
            self.assertEqual(list(load_b(w, legacy=listed)), [])
            # 版の無い答え・別の版の答えは、行に結び付けない
            (w / "b-results" / "a.json").write_text(json.dumps([{"ファイル": "x.csv", "行": 3, "判定": "一致"},
                                                                {"ファイル": "x.csv", "行": 3, "判定": "一致", "版": "v0"}]), encoding="utf-8")
            self.assertEqual(list(load_b(w, legacy=set())), [])

    def test_legacy_answer_list_has_only_plain_versions(self):
        from scripts import verify_blocking_actors as v
        listed = v.load_legacy_answers()
        self.assertTrue(listed)
        self.assertTrue(all("@" not in ver for _, _, _, ver in listed))


if __name__ == "__main__":
    unittest.main()
