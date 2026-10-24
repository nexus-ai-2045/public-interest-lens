"""会議録 API からの議員の活動の取得（scripts/fetch_kokkai_member_activity.py）。通信は使わない。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_kokkai_member_activity as fka  # noqa: E402


class FetchMemberActivityTest(unittest.TestCase):
    def test_keys_by_person_id_and_skips_namesakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            members = Path(tmp) / "members.json"
            members.write_text(json.dumps({"members": [
                {"id": "山田花", "name": "山田花"},
                {"id": "森川空（衆・東京3）", "name": "森川空"},
                {"id": "森川空（参・比例）", "name": "森川 空"},
            ]}, ensure_ascii=False), encoding="utf-8")
            out = Path(tmp) / "out.json"
            # 同姓同名になる前に氏名で取った分が残っている。
            out.write_text(json.dumps({"members": {"森川空": {"recent": []}}}, ensure_ascii=False), encoding="utf-8")
            asked = []
            with mock.patch.object(fka, "activity", side_effect=lambda name, sleep: asked.append(name) or {"recent": []}), \
                    mock.patch.object(sys, "argv", ["x", "--members", str(members), "--out", str(out), "--counts", str(Path(tmp) / "none.csv"),
                                                  "--persons", str(Path(tmp) / "none.csv")]):
                fka.main()
            res = json.loads(out.read_text(encoding="utf-8"))["members"]
        # 同姓同名の2人は氏名検索で分けられないので、API に聞かず理由を残す。
        self.assertEqual(asked, ["山田花"])
        self.assertEqual(sorted(res), sorted(["山田花", "森川空（衆・東京3）", "森川空（参・比例）"]))
        self.assertTrue(res["森川空（参・比例）"]["reason"].startswith("同姓同名"))
        self.assertNotIn("森川空", res)

    def test_namesake_in_ledger_only_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            members = Path(tmp) / "members.json"
            # 議員ページには片方だけが載っているが、人物台帳では同姓同名が分かれている。
            members.write_text(json.dumps({"members": [
                {"id": "山田花", "name": "山田花"},
                {"id": "森川空（参・比例）", "name": "森川空"},
            ]}, ensure_ascii=False), encoding="utf-8")
            persons = Path(tmp) / "persons.csv"
            persons.write_text("人物ID,氏名\n山田花,山田花\n森川空,森川空\n森川空（参・比例）,森川空\n", encoding="utf-8")
            out = Path(tmp) / "out.json"
            asked = []
            with mock.patch.object(fka, "activity", side_effect=lambda name, sleep: asked.append(name) or {"recent": []}), \
                    mock.patch.object(sys, "argv", ["x", "--members", str(members), "--out", str(out),
                                                  "--counts", str(Path(tmp) / "none.csv"), "--persons", str(persons)]):
                fka.main()
            res = json.loads(out.read_text(encoding="utf-8"))["members"]
        self.assertEqual(asked, ["山田花"])
        self.assertTrue(res["森川空（参・比例）"]["reason"].startswith("同姓同名"))


if __name__ == "__main__":
    unittest.main()
