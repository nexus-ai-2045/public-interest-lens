"""議員の活動の公開ファイル（scripts/build_member_activity.py）の人物の結び方。架空の名前だけを使う。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_member_activity as bma


class BuildMemberActivityTest(unittest.TestCase):
    def run_build(self, members, roles, persons):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "members.json").write_text(json.dumps({"members": members}, ensure_ascii=False), encoding="utf-8")
            (root / "src" / "diet.json").write_text("{}", encoding="utf-8")
            (root / "src" / "roles.json").write_text(json.dumps(roles, ensure_ascii=False), encoding="utf-8")
            (root / "persons.csv").write_text("人物ID,氏名\n" + "".join(f"{i},{n}\n" for i, n in persons), encoding="utf-8")
            with mock.patch.object(bma, "SOURCE", root / "src"), mock.patch.object(bma, "MEMBERS", root / "members.json"), \
                    mock.patch.object(bma, "PERSONS", root / "persons.csv"):
                return bma.build("2026-01-01T00:00:00Z")

    def test_name_key_is_rejected_when_ledger_splits_the_name(self):
        role = [{"category": "党", "title": "架空役", "period": "", "url": "https://www.jimin.jp/x", "source": ""}]
        members = [{"id": "森川空（参・比例）", "name": "森川空"}]
        persons = [("森川空", "森川空"), ("森川空（参・比例）", "森川空")]
        # 議員ページには片方しか載っていないが、台帳で分かれているので氏名のキーは受けない。
        with self.assertRaises(ValueError):
            self.run_build(members, {"森川空": role}, persons)
        out = self.run_build(members, {"森川空（参・比例）": role}, persons)
        self.assertEqual(list(out["members"]), ["森川空（参・比例）"])
        # 分かれていない名前は氏名のキーで結ぶ。
        out = self.run_build([{"id": "山田花", "name": "山田花"}], {"山田 花": role}, [("山田花", "山田花")])
        self.assertEqual(list(out["members"]), ["山田花"])


if __name__ == "__main__":
    unittest.main()
