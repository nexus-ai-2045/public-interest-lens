"""会議録 API からの議員の活動の取得（scripts/fetch_kokkai_member_activity.py）。通信は使わない。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_kokkai_member_activity as fka  # noqa: E402


def _write_inputs(tmp, ranked, ledger):
    """曝露ランキング（点あり＝tier が数）と人物台帳を架空の内容で書く。tier が null の人は対象外。"""
    exposure = Path(tmp) / "exposure.json"
    exposure.write_text(json.dumps({"people": [{"actorId": pid, "tier": tier} for pid, tier in ranked]}, ensure_ascii=False), encoding="utf-8")
    persons = Path(tmp) / "persons.csv"
    persons.write_text("人物ID,氏名\n" + "".join(f"{pid},{name}\n" for pid, name in ledger), encoding="utf-8")
    return exposure, persons


class FetchMemberActivityTest(unittest.TestCase):
    def test_keys_by_person_id_and_skips_namesakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            exposure, persons = _write_inputs(
                tmp, [("山田花", 1), ("森川空（衆・東京3）", 2), ("森川空（参・比例）", 3), ("未ランク太郎", None)],
                [("山田花", "山田花"), ("森川空（衆・東京3）", "森川空"), ("森川空（参・比例）", "森川 空"), ("未ランク太郎", "未ランク太郎")])
            out = Path(tmp) / "out.json"
            # 同姓同名になる前に氏名で取った分が残っている。
            out.write_text(json.dumps({"members": {"森川空": {"recent": []}}}, ensure_ascii=False), encoding="utf-8")
            asked = []
            with mock.patch.object(fka, "activity", side_effect=lambda name, sleep: asked.append(name) or {"recent": []}), \
                    mock.patch.object(sys, "argv", ["x", "--exposure", str(exposure), "--out", str(out), "--counts", str(Path(tmp) / "none.csv"),
                                                  "--persons", str(persons)]):
                fka.main()
            res = json.loads(out.read_text(encoding="utf-8"))["members"]
        # 同姓同名の2人は氏名検索で分けられないので、API に聞かず理由を残す。点なしの人は対象外。
        self.assertEqual(asked, ["山田花"])
        self.assertEqual(sorted(res), sorted(["山田花", "森川空（衆・東京3）", "森川空（参・比例）"]))
        self.assertTrue(res["森川空（参・比例）"]["reason"].startswith("同姓同名"))
        self.assertNotIn("森川空", res)

    def test_namesake_in_ledger_only_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 曝露ランキングで点があるのは片方だけだが、人物台帳では同姓同名が分かれている。
            exposure, persons = _write_inputs(
                tmp, [("山田花", 1), ("森川空（参・比例）", 2)],
                [("山田花", "山田花"), ("森川空", "森川空"), ("森川空（参・比例）", "森川空")])
            out = Path(tmp) / "out.json"
            asked = []
            with mock.patch.object(fka, "activity", side_effect=lambda name, sleep: asked.append(name) or {"recent": []}), \
                    mock.patch.object(sys, "argv", ["x", "--exposure", str(exposure), "--out", str(out),
                                                  "--counts", str(Path(tmp) / "none.csv"), "--persons", str(persons)]):
                fka.main()
            res = json.loads(out.read_text(encoding="utf-8"))["members"]
        self.assertEqual(asked, ["山田花"])
        self.assertTrue(res["森川空（参・比例）"]["reason"].startswith("同姓同名"))


if __name__ == "__main__":
    unittest.main()
