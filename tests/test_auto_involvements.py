"""自動の関与（scripts/build_auto_involvements.py）の閣法の提出者。

閣法は内閣の提出なので、総理大臣1人に付けず、会期を通して在任した閣僚の全員に付ける（設計確定 v2.1）。
条件は app/src/members-reference.ts の cabinetOf と同じで、実データで同じ顔ぶれになることを確かめる。
"""
import csv
import shutil
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import build_auto_involvements as auto
from scripts import check_reference_members as crm


def _bill(session: str, referred: str, kind: str = "閣法", held: str = "") -> dict[str, str]:
    return {"種別": kind, "回次": held or session, "提出回次": session, "付託日_衆": referred}


def _post(name: str, role: str, start: str, end: str = "", group: str = "閣僚") -> dict[str, str]:
    return {"区分": group, "氏名": name, "役職": role, "就任日_西暦": start, "退任日_西暦": end}


CABINET = [
    _post("甲野 一郎", "内閣総理大臣", "2001-01-01", "2002-06-01"),
    _post("乙川 二郎", "財務大臣", "2001-01-01", "2002-06-01"),
    _post("乙川 二郎", "金融担当大臣", "2001-01-01", "2002-06-01"),  # 兼務は1人に数える
    _post("丙山 三郎", "外務大臣", "2001-01-01", "2001-03-01"),  # 会期の途中で退任
    _post("丁田 四郎", "外務大臣", "2001-03-01", "2002-06-01"),  # 会期の途中で就任
    _post("戊井 五郎", "内閣官房副長官", "2001-01-01", "2002-06-01"),  # 閣僚の欄にあるが閣僚ではない
    _post("己原 六郎", "内閣法制局長官", "2001-01-01", "2002-06-01"),
    _post("庚木 七郎", "財務副大臣", "2001-01-01", "2002-06-01", group="副大臣"),
    _post("辛島 八郎", "内閣総理大臣", "2002-06-01"),
    _post("乙川 二郎", "財務大臣", "2002-06-01"),
]


class CabinetsTest(unittest.TestCase):
    def test_cabinet_bill_goes_to_every_minister_serving_through_the_session(self):
        enacted = [_bill("151", "平成13年 2月 1日"), _bill("151", "平成13年 5月10日")]
        self.assertEqual(auto.cabinets(enacted, CABINET)["151"], [("乙川二郎", "財務大臣"), ("甲野一郎", "内閣総理大臣")])

    def test_single_referral_day_keeps_ministers_of_that_day(self):
        enacted = [_bill("151", "平成13年 2月 1日")]
        self.assertEqual([name for name, _ in auto.cabinets(enacted, CABINET)["151"]], ["丙山三郎", "乙川二郎", "甲野一郎"])

    def test_session_where_prime_minister_changes_is_not_assigned(self):
        enacted = [_bill("154", "平成14年 5月 1日"), _bill("154", "平成14年 7月 1日")]
        self.assertNotIn("154", auto.cabinets(enacted, CABINET))

    def test_span_ignores_carried_over_and_non_cabinet_bills(self):
        # 継続審査の閣法（回次が提出回次と違う）と衆法の付託日は、会期の幅に入れない
        enacted = [_bill("151", "平成13年 2月 1日"), _bill("151", "平成14年 7月 1日", held="154"), _bill("151", "平成14年 7月 1日", kind="衆法")]
        self.assertIn("151", auto.cabinets(enacted, CABINET))

    def test_real_sessions_never_give_a_cabinet_bill_to_the_prime_minister_alone(self):
        cabinets = auto.cabinets(auto._read(auto.ENACTED), auto._read(auto.CABINET))
        self.assertTrue(cabinets)
        for session, members in cabinets.items():
            self.assertGreater(len(members), 1, session)
            self.assertEqual(sum(role == "内閣総理大臣" for _, role in members), 1, session)
            self.assertFalse([role for _, role in members if auto.NOT_MINISTER.search(role)], session)


@unittest.skipUnless(shutil.which("node") and (ROOT / "app" / "node_modules" / "vite").exists(), "node か app の依存が無い")
class CabinetSyncWithTypeScriptTest(unittest.TestCase):
    def test_same_ministers_as_members_reference(self):
        """TS（members-reference.ts、#184）が閣法の提出者として配った人と、回次ごとに同じ顔ぶれになる。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attributions.csv"
            crm.build_attributions(path)
            with path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        ts: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            if r["lawId"].startswith("閣法") and r["role"] == "proposer":
                ts[r["lawId"].split("-")[1]].add(auto.norm(r["name"]))
        self.assertTrue(ts)
        cabinets = auto.cabinets(auto._read(auto.ENACTED), auto._read(auto.CABINET))
        for session, names in sorted(ts.items()):
            self.assertEqual({name for name, _ in cabinets.get(session, [])}, names, f"第{session}回")


if __name__ == "__main__":
    unittest.main()
