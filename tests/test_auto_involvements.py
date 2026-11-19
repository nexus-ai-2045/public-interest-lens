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
    _post("乙川 二郎*", "金融担当大臣", "2001-01-01", "2002-06-01"),  # 兼務は1人に数える。名簿の脚注の印（*）は同じ人
    _post("丙山 三郎", "外務大臣", "2001-01-01", "2001-03-01"),  # 会期の途中で退任
    _post("丁田 四郎", "外務大臣", "2001-03-01", "2002-06-01"),  # 会期の途中で就任
    _post("戊井 五郎", "内閣官房副長官", "2001-01-01", "2002-06-01"),  # 閣僚の欄にあるが閣僚ではない
    _post("己原 六郎", "内閣法制局長官", "2001-01-01", "2002-06-01"),
    _post("庚木 七郎", "財務副大臣", "2001-01-01", "2002-06-01", group="副大臣"),
    _post("壬生 九郎", "法務大臣", "2001-01-01", "2001-04-01"),  # 印の有無が途中で変わっても、通して在任した同じ人
    _post("壬生 九郎*", "法務大臣", "2001-04-01", "2002-06-01"),
    _post("辛島 八郎", "内閣総理大臣", "2002-06-01"),
    _post("乙川 二郎", "財務大臣", "2002-06-01"),
]
THROUGH = [("乙川二郎", "財務大臣・金融担当大臣"), ("壬生九郎", "法務大臣"), ("甲野一郎", "内閣総理大臣")]


class CabinetsTest(unittest.TestCase):
    def test_cabinet_bill_goes_to_every_minister_serving_through_the_session(self):
        enacted = [_bill("151", "平成13年 2月 1日"), _bill("151", "平成13年 5月10日")]
        self.assertEqual(auto.cabinets(enacted, CABINET)["session"]["151"], THROUGH)

    def test_concurrent_posts_do_not_depend_on_roster_row_order(self):
        enacted = [_bill("151", "平成13年 2月 1日"), _bill("151", "平成13年 5月10日")]
        self.assertEqual(auto.cabinets(enacted, CABINET[::-1])["session"]["151"], THROUGH)

    def test_single_referral_day_keeps_ministers_of_that_day(self):
        enacted = [_bill("151", "平成13年 2月 1日")]
        self.assertEqual([name for name, _ in auto.cabinets(enacted, CABINET)["session"]["151"]], ["丙山三郎", "乙川二郎", "壬生九郎", "甲野一郎"])

    def test_session_where_prime_minister_changes_uses_the_cabinet_of_the_referral_day(self):
        enacted = [_bill("154", "平成14年 5月 1日"), _bill("154", "平成14年 7月 1日")]
        got = auto.cabinets(enacted, CABINET)
        self.assertNotIn("154", got["session"])  # 回次では内閣を決められない
        self.assertEqual([name for name, _ in got["day"]["2002-05-01"]], ["丁田四郎", "乙川二郎", "壬生九郎", "甲野一郎"])
        self.assertEqual(got["day"]["2002-07-01"], [("乙川二郎", "財務大臣"), ("辛島八郎", "内閣総理大臣")])

    def test_span_ignores_carried_over_and_non_cabinet_bills(self):
        # 継続審査の閣法（回次が提出回次と違う）と衆法の付託日は、会期の幅に入れない
        enacted = [_bill("151", "平成13年 2月 1日"), _bill("151", "平成14年 7月 1日", held="154"), _bill("151", "平成14年 7月 1日", kind="衆法")]
        self.assertIn("151", auto.cabinets(enacted, CABINET)["session"])

    def test_real_cabinets_never_give_a_cabinet_bill_to_the_prime_minister_alone(self):
        got = auto.cabinets(auto._read(auto.ENACTED), auto._read(auto.CABINET))
        self.assertTrue(got["session"])
        for where, members in [*got["session"].items(), *got["day"].items()]:
            self.assertGreater(len(members), 1, where)
            self.assertEqual(sum(role.startswith(auto.PRIME_MINISTER) for _, role in members), 1, where)
            self.assertFalse([role for _, role in members if auto.NOT_MINISTER.search(role)], where)
            self.assertFalse([name for name, _ in members if "*" in name], where)
            self.assertEqual(len({name for name, _ in members}), len(members), where)

    def test_built_rows_have_one_row_per_minister_and_no_house(self):
        rows, votes = auto.build()
        decide = [r for r in rows if r["行動"] == "decide" and r["法律ID"].startswith("閣法")]
        for law in {r["法律ID"] for r in decide}:
            mine = [r for r in decide if r["法律ID"] == law]
            self.assertGreater(len(mine), 1, law)
            self.assertEqual(len({r["人物ID"] or r["氏名"] for r in mine}), len(mine), law)
            self.assertEqual(sum(r["立場区分"] == "prime_minister" for r in mine), 1, law)
            self.assertEqual({r["院"] for r in mine}, {""}, law)


@unittest.skipUnless(shutil.which("node") and (ROOT / "app" / "node_modules" / "vite").exists(), "node か app の依存が無い")
class CabinetSyncWithTypeScriptTest(unittest.TestCase):
    def test_same_ministers_as_members_reference(self):
        """TS（members-reference.ts）が閣法の提出者として配った人と、法律ごとに同じ顔ぶれになる（総理大臣が替わる回次は付託日の内閣）。

        TS は向きが未確定の法律を人に配らないので、照らすのは配った閣法だけ。配った閣法が無いと何も確かめないので、単体テストで同じ決まりを別に確かめる
        （app/src/members-reference.test.ts と、下の CabinetsTest）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attributions.csv"
            crm.build_attributions(path)
            with path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        ts: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            if r["lawId"].startswith("閣法") and r["role"] == "proposer":
                ts[r["lawId"]].add(auto.canonical(r["name"]))
        enacted = {f"{r['種別']}-{r['提出回次']}-{r['番号']}": r for r in auto._read(auto.ENACTED)}
        cabinets = auto.cabinets(list(enacted.values()), auto._read(auto.CABINET))
        for law, names in sorted(ts.items()):
            bill = enacted[law]
            referred = auto.wareki(bill["付託日_衆"]) if bill["回次"] == bill["提出回次"] else ""
            expected = cabinets["session"].get(bill["提出回次"]) or cabinets["day"].get(referred, [])
            self.assertEqual({name for name, _ in expected}, names, law)


if __name__ == "__main__":
    unittest.main()
