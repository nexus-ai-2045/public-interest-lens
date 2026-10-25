import csv
import json
from collections import Counter
import subprocess
import sys
import tempfile
from unittest import mock
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_law_overviews as overviews  # noqa: E402
import split_shared_speeches as split  # noqa: E402
SPEECHES = ROOT / "data" / "acquired" / "bill-speeches" / "speeches.csv"
SEGMENTS = SPEECHES.parent / "segments.csv"
OVERVIEWS = ROOT / "data" / "derived" / "law-overviews-v1" / "overviews.csv"
from _data_gate import requires_data  # noqa: E402


class LawOverviewsTest(unittest.TestCase):
    def setUp(self):
        self.speeches = {row["id"]: row for row in csv.DictReader(SPEECHES.open(encoding="utf-8"))}
        self.overviews = list(csv.DictReader(OVERVIEWS.open(encoding="utf-8")))
        self.segments = {(row["id"], row["区分"]): row for row in csv.DictReader(SEGMENTS.open(encoding="utf-8"))}

    @requires_data("speeches")
    def test_summaries_have_their_source(self):
        for row in self.overviews:
            source = self.speeches[row["id"]]
            if row["何をする"] or row["狙い"]:
                self.assertTrue(source["説明の抜粋"], row["id"])
            if row["反対側の心配"]:
                self.assertTrue(source["反対の抜粋"], row["id"])

    @requires_data("speeches")
    def test_bills_sharing_a_speech_use_only_their_own_segment(self):
        for url, columns, kind in (("説明のURL", ("何をする", "狙い"), "説明"), ("反対のURL", ("反対側の心配",), "反対")):
            uses = Counter(row[url] for row in self.speeches.values() if row[url])
            for row in self.overviews:
                source = self.speeches[row["id"]]
                if not source[url] or uses[source[url]] < 2 or not any(row[column] for column in columns):
                    continue
                # 発言の全文からこの法案の部分を切り出して要約したものだけが残る
                self.assertIn((source["id"], kind), self.segments, row["id"])
                self.assertEqual(self.segments[(source["id"], kind)]["URL"], source[url], row["id"])

    @requires_data("speeches")
    def test_bill_does_not_carry_the_summary_of_the_bill_explained_before_it(self):
        # 閣法-164-22（地方交付税法）は、同じ発言で先に説明された閣法-164-21（地方税法）の中身を載せない
        row = next(item for item in self.overviews if item["id"] == "閣法-164-22")
        for word in ("三兆円", "定率減税", "住民税"):
            self.assertNotIn(word, row["何をする"] + row["狙い"])

    @requires_data("speeches")
    def test_segments_start_with_their_own_title(self):
        for (law_id, kind), segment in self.segments.items():
            title = self.speeches[law_id]["題名"].removesuffix("案")
            self.assertIn(title, segment["抜粋"][:400], law_id)
            self.assertGreaterEqual(len(segment["抜粋"]), 120, law_id)

    @requires_data("speeches")
    def test_segment_starts_at_its_own_heading_not_a_passing_mention(self):
        # 閣法-150-12：民事再生法の説明の途中で「同時に提出いたしております外国倒産…法律案と相まって」と触れている所から切らない
        text = ("○大臣 民事再生法等の一部を改正する法律案につきまして、その趣旨を御説明いたします。"
                "そこで、この法律案は、個人債務者の再生手続の特則を設けるとともに、同時に提出いたしております外国倒産処理手続の承認援助に関する法律案と相まって、国際倒産法制を整備するものであります。"
                "続いて、外国倒産処理手続の承認援助に関する法律案につきまして、その趣旨を御説明いたします。" + "外国で始まった倒産手続を国内でも認めて、債務者の財産を守る手続を定めるものであります。" * 3)
        body = split.segment(text, "外国倒産処理手続の承認援助に関する法律案", ["民事再生法等の一部を改正する法律案"], 1200, [])
        self.assertTrue(body.startswith("続いて、外国倒産処理手続"), body[:40])
        row = self.segments.get(("閣法-150-12", "説明"))
        if row:
            self.assertNotIn("住宅ローン", row["抜粋"][:200])

    @requires_data("speeches")
    def test_bill_whose_speeches_describe_other_bills_is_left_blank(self):
        # 反対討論は別の法案（防衛庁設置法及び自衛隊法の一部を改正する法律案）のものなので空のまま
        row = next(item for item in self.overviews if item["id"] == "閣法-142-110")
        self.assertEqual(row["反対側の心配"], "")
        self.assertNotIn(("閣法-142-110", "反対"), self.segments)

    @requires_data("speeches")
    def test_debate_about_another_bill_is_not_a_concern_of_this_law(self):
        # 閣法-169-6 は暫定税率の再議決の動議、閣法-171-10 は地方交付税法の改正、閣法-174-6 は予算への反対討論を拾っていた
        rows = {item["id"]: item for item in self.overviews}
        for law_id in ("閣法-169-6", "閣法-171-10", "閣法-174-6"):
            self.assertEqual(rows[law_id]["反対側の心配"], "", law_id)

    @requires_data("speeches")
    def test_joint_heading_with_another_bill_is_not_this_laws_segment(self):
        # 閣法-155-47 の反対討論は「機構法並びに中小企業総合事業団法及び機械類信用保険法の廃止法案について」とまとめて述べていて、
        # 信用保険の廃止は別の法案（閣法-155-46）の中身なので、この法律の懸念にしない
        text = ("次に、独立行政法人中小企業基盤整備機構法並びに中小企業総合事業団法及び機械類信用保険法の廃止法案についてです。"
                + "機械類信用保険制度などを廃止する一方で、中小企業政策の後退を招くものです。" * 4)
        self.assertEqual(split.segment(text, "独立行政法人中小企業基盤整備機構法案", [], 600, []), "")
        self.assertNotIn(("閣法-155-47", "反対"), self.segments)
        row = next(item for item in self.overviews if item["id"] == "閣法-155-47")
        self.assertNotIn("信用保険", row["反対側の心配"])

    @requires_data("speeches")
    def test_split_reads_the_speeches_fetched_in_parallel_too(self):
        # fetch_bill_speeches.py --out speeches-*.csv で並べて取った分も、概要づくりと同じく切り出しの対象にする
        with tempfile.TemporaryDirectory() as folder:
            header = "id,題名\n"
            (Path(folder) / "speeches.csv").write_text(header + "a,甲法案\n", encoding="utf-8")
            (Path(folder) / "speeches-2.csv").write_text(header + "b,乙法案\n", encoding="utf-8")
            (Path(folder) / "segments.csv").write_text("id,区分\n", encoding="utf-8")
            self.assertEqual(sorted(row["id"] for row in split.read_speeches(Path(folder))), ["a", "b"])

    @requires_data("speeches")
    def test_overviews_are_not_built_without_the_verification(self):
        # 別の読み手の照合結果が無いまま「照合した」印つきの台帳を作らない
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_law_overviews.py"), "a", "b"], capture_output=True)
        self.assertEqual(result.returncode, 2)

    @requires_data("speeches")
    def test_missing_or_empty_folders_do_not_overwrite_the_overviews(self):
        # 照合結果のフォルダが無い・空のときは、台帳を書かずに止める
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            out = folder / "overviews.csv"
            ok = '{"id": "A", "何をする": "ok"}\n'
            with mock.patch.multiple(overviews, OUT=out, SEGMENTS=folder / "segments.csv"):
                # 要約のフォルダが空・壊れた行だけ・壊れた行が混じっている
                (folder / "verify" / "a.jsonl").write_text(ok, encoding="utf-8")
                for text in ("", '{"id": "A", "何をする": "甲"\n', '{"id": "A"}\n{"id": "B"\n'):
                    (folder / "ov" / "a.jsonl").write_text(text, encoding="utf-8")
                    self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2, text)
                (folder / "ov" / "a.jsonl").write_text('{"id": "A"}\n', encoding="utf-8")
                (folder / "verify" / "a.jsonl").unlink()
                # 切り出しがあるのに、切り出しの要約が1件も無い
                (folder / "segments.csv").write_text("id,区分,抜粋,URL,取得日時\nA,説明,甲,u,\n", encoding="utf-8")
                (folder / "verify" / "a.jsonl").write_text(ok, encoding="utf-8")
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2)
                (folder / "segments.csv").unlink()
                (folder / "verify" / "a.jsonl").unlink()
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "nothing")), 2)
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2)
                (folder / "verify" / "a.jsonl").write_text("\n", encoding="utf-8")
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2)
                # 壊れた行だけの出力や、壊れた行が混じった出力、id の無い判定だけのものでも止める
                for text in ('{"id": "A", "何をする": "ok"\n', '{"id": "A", "何をする": "ok"}\n{"id": "B"\n', '{"何をする": "ok"}\n[]\n'):
                    (folder / "verify" / "a.jsonl").write_text(text, encoding="utf-8")
                    self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2, text)
            self.assertFalse(out.exists())

    @requires_data("speeches")
    def test_partial_verification_does_not_overwrite_the_overviews(self):
        # 照合が途中で止まり、行は正しいが件数が足りない出力では、台帳を書かずに止める
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            speeches = folder / "speeches.csv"
            with speeches.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明の抜粋", "説明のURL", "反対の抜粋", "反対のURL"])
                writer.writeheader()
                for number in range(10):
                    writer.writerow({"id": f"L{number}", "題名": f"{number}法案", "説明の抜粋": "説明", "説明のURL": f"u{number}", "反対の抜粋": "", "反対のURL": ""})
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            (folder / "ov" / "a.jsonl").write_text("".join(json.dumps({"id": f"L{n}", "何をする": "する"}, ensure_ascii=False) + "\n" for n in range(10)), encoding="utf-8")
            seen = {"字数": 2, "指紋": overviews.digest("説明")}
            verdict = {"id": "L0", "何をする": "ok", "照合した要約": {"何をする": "する"}, "照合した抜粋": {"何をする": seen}, "説明の発言": "ok", "照合した発言": {"説明": seen}}
            (folder / "verify" / "a.jsonl").write_text(json.dumps(verdict, ensure_ascii=False) + "\n", encoding="utf-8")
            out = folder / "overviews.csv"
            with mock.patch.multiple(overviews, SPEECHES=speeches, SEGMENTS=folder / "segments.csv", OUT=out):
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2)
            self.assertFalse(out.exists())

    @requires_data("speeches")
    def test_partial_summaries_do_not_overwrite_the_overviews(self):
        # 要約が途中で止まり、材料のある法案の一部しか要約が無い出力では、台帳を書かずに止める
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            speeches = folder / "speeches.csv"
            with speeches.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明の抜粋", "説明のURL", "反対の抜粋", "反対のURL"])
                writer.writeheader()
                for number in range(10):
                    writer.writerow({"id": f"L{number}", "題名": f"{number}法案", "説明の抜粋": "説明", "説明のURL": f"u{number}", "反対の抜粋": "", "反対のURL": ""})
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            (folder / "ov" / "a.jsonl").write_text(json.dumps({"id": "L0", "何をする": "する"}, ensure_ascii=False) + "\n", encoding="utf-8")
            seen = {"字数": 2, "指紋": overviews.digest("説明")}
            verdict = {"id": "L0", "何をする": "ok", "照合した要約": {"何をする": "する"}, "照合した抜粋": {"何をする": seen}, "説明の発言": "ok", "照合した発言": {"説明": seen}}
            (folder / "verify" / "a.jsonl").write_text(json.dumps(verdict, ensure_ascii=False) + "\n", encoding="utf-8")
            out = folder / "overviews.csv"
            with mock.patch.multiple(overviews, SPEECHES=speeches, SEGMENTS=folder / "segments.csv", OUT=out):
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2)
            self.assertFalse(out.exists())

    @requires_data("speeches")
    def test_partial_segment_summaries_do_not_overwrite_the_overviews(self):
        # 切り出しの要約が途中で止まり、切り出しのある法案の一部しか要約が無い出力では、台帳を書かずに止める
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            speeches = folder / "speeches.csv"
            segments = folder / "segments.csv"
            with speeches.open("w", encoding="utf-8", newline="") as handle, segments.open("w", encoding="utf-8", newline="") as seg:
                writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明の抜粋", "説明のURL", "反対の抜粋", "反対のURL"])
                writer.writeheader()
                parts = csv.DictWriter(seg, fieldnames=["id", "区分", "抜粋", "URL", "取得日時"])
                parts.writeheader()
                for number in range(10):
                    writer.writerow({"id": f"L{number}", "題名": f"{number}法案", "説明の抜粋": "まとめた説明", "説明のURL": "u", "反対の抜粋": "", "反対のURL": ""})
                    parts.writerow({"id": f"L{number}", "区分": "説明", "抜粋": f"{number}の説明", "URL": "u", "取得日時": ""})
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            (folder / "ov" / "a.jsonl").write_text("".join(json.dumps({"id": f"L{n}"}) + "\n" for n in range(10)), encoding="utf-8")
            (folder / "seg" / "a.jsonl").write_text(json.dumps({"id": "L0", "何をする": "する"}, ensure_ascii=False) + "\n", encoding="utf-8")
            verdicts = [{"id": f"L{n}", "説明の発言": "ok", "照合した発言": {"説明": {"字数": 3, "指紋": overviews.digest(f"{n}の説")}}} for n in range(10)]
            (folder / "verify" / "a.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts), encoding="utf-8")
            out = folder / "overviews.csv"
            with mock.patch.multiple(overviews, SPEECHES=speeches, SEGMENTS=segments, OUT=out):
                self.assertEqual(overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify")), 2)
            self.assertFalse(out.exists())

    @requires_data("speeches")
    def test_found_speech_without_a_verdict_is_not_shown(self):
        # 要約が空の欄の発言は、別の読み手が「この法律の発言」と確かめたときだけ示す（照合結果が欠けていたら示さない）
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            speeches = folder / "speeches.csv"
            with speeches.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明の抜粋", "説明のURL", "反対の抜粋", "反対のURL"])
                writer.writeheader()
                writer.writerow({"id": "A", "題名": "甲法案", "説明の抜粋": "甲の説明", "説明のURL": "u1", "反対の抜粋": "反対", "反対のURL": "u2"})
                writer.writerow({"id": "B", "題名": "乙法案", "説明の抜粋": "乙の説明", "説明のURL": "u3", "反対の抜粋": "反対", "反対のURL": "u4"})
                writer.writerow({"id": "C", "題名": "丙法案", "説明の抜粋": "丙の説明", "説明のURL": "u5", "反対の抜粋": "", "反対のURL": ""})
                writer.writerow({"id": "D", "題名": "丁法案", "説明の抜粋": "丁と戊の説明", "説明のURL": "u6", "反対の抜粋": "", "反対のURL": ""})
                writer.writerow({"id": "E", "題名": "戊法案", "説明の抜粋": "丁と戊の説明", "説明のURL": "u6", "反対の抜粋": "", "反対のURL": ""})
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            (folder / "ov" / "a.jsonl").write_text('{"id": "A"}\n{"id": "B"}\n{"id": "C"}\n{"id": "D"}\n{"id": "E"}\n', encoding="utf-8")
            seen = {"字数": 4, "指紋": overviews.digest("乙の説明")}
            other = {"字数": 2, "指紋": overviews.digest("反対")}
            verdicts = [{"id": "B", "説明の発言": "ok", "反対の発言": "other", "照合した発言": {"説明": seen, "反対": other}},
                        # 前の抜粋に対する "other" も使わない（いまの発言を別の議題と決めつけず、確かめていないものとする）
                        {"id": "A", "反対の発言": "other", "照合した発言": {"反対": {"字数": 2, "指紋": overviews.digest("前の")}}},
                        # 前の抜粋に対する "ok" は、いまの抜粋には使わない
                        {"id": "C", "説明の発言": "ok", "照合した発言": {"説明": {"字数": 4, "指紋": overviews.digest("前の抜粋")}}}]
            (folder / "verify" / "a.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts), encoding="utf-8")
            out = folder / "overviews.csv"
            with mock.patch.multiple(overviews, SPEECHES=speeches, SEGMENTS=folder / "segments.csv", OUT=out, MISSING_LIMIT=1.0):
                overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify"))
            rows = {row["id"]: row for row in csv.DictReader(out.open(encoding="utf-8"))}
            self.assertEqual(rows["A"]["確かめていない発言"], "説明・反対")
            self.assertEqual(rows["A"]["別の議題の発言"], "")
            self.assertEqual(rows["B"]["確かめていない発言"], "")
            self.assertEqual(rows["B"]["別の議題の発言"], "反対")
            self.assertEqual(rows["C"]["確かめていない発言"], "説明")
            # ほかの法案と共有する発言でも、照合が無ければ示さない（D と E は同じ発言 u6 を材料にしている）
            self.assertEqual(rows["D"]["確かめていない発言"], "説明")

    @requires_data("speeches")
    def test_stale_verdict_does_not_approve_a_new_summary(self):
        # 照合結果は、読み手が見た要約の文と抜粋に結びつける。要約や抜粋が後で変わったら、古い "ok" で載せない
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            speeches = folder / "speeches.csv"
            with speeches.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明の抜粋", "説明のURL", "反対の抜粋", "反対のURL"])
                writer.writeheader()
                for law_id in ("A", "B", "C"):
                    writer.writerow({"id": law_id, "題名": f"{law_id}法案", "説明の抜粋": "甲の説明。続き", "説明のURL": f"u{law_id}", "反対の抜粋": "", "反対のURL": ""})
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            (folder / "ov" / "a.jsonl").write_text("".join(json.dumps({"id": law_id, "何をする": "甲をする"}, ensure_ascii=False) + "\n" for law_id in "ABC"), encoding="utf-8")
            seen = {"字数": 5, "指紋": overviews.digest("甲の説明。")}
            verdicts = [
                {"id": "A", "何をする": "ok", "照合した要約": {"何をする": "甲をする"}, "照合した抜粋": {"何をする": seen}},
                {"id": "B", "何をする": "ok", "照合した要約": {"何をする": "前の文"}, "照合した抜粋": {"何をする": seen}},
                {"id": "C", "何をする": "ok", "照合した要約": {"何をする": "甲をする"}, "照合した抜粋": {"何をする": {"字数": 5, "指紋": overviews.digest("前の抜粋")}}},
            ]
            (folder / "verify" / "a.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts), encoding="utf-8")
            out = folder / "overviews.csv"
            with mock.patch.multiple(overviews, SPEECHES=speeches, SEGMENTS=folder / "segments.csv", OUT=out, MISSING_LIMIT=1.0):
                overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify"))
            rows = {row["id"]: row for row in csv.DictReader(out.open(encoding="utf-8"))}
            self.assertEqual(rows["A"]["何をする"], "甲をする")
            self.assertEqual(rows["B"]["何をする"], "")
            self.assertEqual(rows["C"]["何をする"], "")

    @requires_data("speeches")
    def test_segment_from_an_old_speech_url_is_not_used(self):
        # 発言を取り直して URL が変わったら、前の URL から切り出した部分の要約は使わない
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            speeches = folder / "speeches.csv"
            with speeches.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明の抜粋", "説明のURL", "反対の抜粋", "反対のURL"])
                writer.writeheader()
                for law_id in ("A", "B"):
                    writer.writerow({"id": law_id, "題名": f"{law_id}法案", "説明の抜粋": "AとBの説明", "説明のURL": "new", "反対の抜粋": "", "反対のURL": ""})
            segments = folder / "segments.csv"
            with segments.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "区分", "抜粋", "URL", "取得日時"])
                writer.writeheader()
                writer.writerow({"id": "A", "区分": "説明", "抜粋": "Aの部分", "URL": "old", "取得日時": ""})
                writer.writerow({"id": "B", "区分": "説明", "抜粋": "Bの部分", "URL": "new", "取得日時": ""})
            for name in ("ov", "seg", "verify"):
                (folder / name).mkdir()
            (folder / "ov" / "a.jsonl").write_text('{"id": "A"}\n{"id": "B"}\n', encoding="utf-8")
            (folder / "seg" / "a.jsonl").write_text('{"id": "A", "何をする": "Aをする"}\n{"id": "B", "何をする": "Bをする"}\n', encoding="utf-8")
            verdicts = [{"id": law_id, "何をする": "ok", "照合した要約": {"何をする": f"{law_id}をする"},
                         "照合した抜粋": {"何をする": {"字数": 4, "指紋": overviews.digest(f"{law_id}の部分")}}} for law_id in "AB"]
            (folder / "verify" / "a.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts), encoding="utf-8")
            out = folder / "overviews.csv"
            with mock.patch.multiple(overviews, SPEECHES=speeches, SEGMENTS=segments, OUT=out, MISSING_LIMIT=1.0):
                overviews.main(str(folder / "ov"), str(folder / "seg"), str(folder / "verify"))
            rows = {row["id"]: row for row in csv.DictReader(out.open(encoding="utf-8"))}
            self.assertEqual(rows["A"]["何をする"], "")
            self.assertEqual(rows["B"]["何をする"], "Bをする")

    @requires_data("speeches")
    def test_empty_fingerprint_does_not_match_any_excerpt(self):
        # 0字の指紋（空文字列の sha256）は、どの抜粋の頭とも同じになるので、照合したものとして受け入れない
        empty = overviews.digest("")
        self.assertFalse(overviews.matches({"字数": 0, "指紋": empty}, ["甲の説明"]))
        self.assertFalse(overviews.matches({"指紋": empty}, ["甲の説明"]))
        self.assertFalse(overviews.matches({"字数": "2", "指紋": overviews.digest("甲の")}, ["甲の説明"]))
        self.assertFalse(overviews.matches({"字数": 9, "指紋": overviews.digest("甲の説明")}, ["甲の説明"]))
        self.assertTrue(overviews.matches({"字数": 2, "指紋": overviews.digest("甲の")}, ["甲の説明"]))

    @requires_data("speeches")
    def test_failed_fetch_keeps_the_previous_segment(self):
        # 発言の全文が一時的に取れなくても（例外・空の応答とも）、前回切り出した部分を消さない
        def fail(*_):
            raise OSError("timeout")

        for patch in ({"get": fail}, {"get": lambda *_: {"speechRecord": []}}):
            with self.subTest(patch=patch), tempfile.TemporaryDirectory() as folder:
                folder = Path(folder)
                speeches, enacted, out = folder / "speeches.csv", folder / "enacted.csv", folder / "segments.csv"
                url = "https://kokkai.ndl.go.jp/txt/X/1"
                with speeches.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["id", "題名", "説明のURL", "反対のURL"])
                    writer.writeheader()
                    writer.writerow({"id": "A", "題名": "甲法案", "説明のURL": url, "反対のURL": ""})
                    writer.writerow({"id": "B", "題名": "乙法案", "説明のURL": url, "反対のURL": ""})
                enacted.write_text("題名\n甲法案\n乙法案\n", encoding="utf-8")
                with out.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=split.FIELDS)
                    writer.writeheader()
                    writer.writerow({"id": "A", "区分": "説明", "抜粋": "前回の部分", "URL": url, "取得日時": "t"})
                with mock.patch.multiple(split, SPEECHES=speeches, ENACTED=enacted, OUT=out, OUT_DIR=folder / "a" / "b" / "c", **patch), \
                        mock.patch.object(sys, "argv", ["split"]):
                    split.main()
                rows = list(csv.DictReader(out.open(encoding="utf-8")))
                self.assertEqual([row["抜粋"] for row in rows], ["前回の部分"])

if __name__ == "__main__":
    unittest.main()
