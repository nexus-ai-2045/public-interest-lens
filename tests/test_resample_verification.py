"""抜き取り検証2回目（sample-v2）の検査。

標本が記録した種と手順で作り直せること、初回と重ならないこと、突き合わせの判定が2系統の記録とサイトの値から
機械的に出ること（verdicts.csv を手で書き換えていないこと）を確かめる。
"""
import csv
import json
import unittest
from pathlib import Path

from scripts.resample_verification import SEED_V2, judge

L = Path(__file__).resolve().parents[1] / "data" / "derived" / "evaluation-ledger-v1"
V2 = L / "sample-v2"


def rows(p: Path) -> list[dict]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


SITE = {"類型": "実質改正", "分類": "評価対象", "到達点": "参考額（産業の付加価値の差）", "分野": "金融"}
READ = {"類型": "実質改正", "経済に効くか": "経済に効く", "主な産業分野": "金融", "範囲": "その産業全体"}


class JudgeRules(unittest.TestCase):
    def test_agree_and_match_passes(self):
        self.assertEqual(judge(SITE, READ, dict(READ))[0], "合格")

    def test_institutional_is_read_by_reach(self):
        site = {**SITE, "分類": "評価対象外", "到達点": "保留"}
        # 振り分けの分類が評価対象外でも、到達点が保留ならサイトは「経済に効く」と扱う
        self.assertEqual(judge(site, READ, dict(READ))[0], "合格")
        site = {**SITE, "到達点": "評価対象外"}
        self.assertEqual(judge(site, READ, dict(READ))[0], "不合格")

    def test_narrow_scope_fails_amount(self):
        a = {**READ, "範囲": "産業の一部（狭い特例）"}
        v, diffs, _ = judge(SITE, a, dict(a))
        self.assertEqual(v, "不合格")
        self.assertTrue(any(d.startswith("範囲") for d in diffs))

    def test_split_waits_then_ruling_decides(self):
        b = {**READ, "類型": "定型改正"}
        self.assertEqual(judge(SITE, READ, b)[0], "割れ")
        self.assertEqual(judge(SITE, READ, b, {"類型": "実質改正"})[0], "合格")

    def test_field_and_scope_only_for_amounts(self):
        site = {**SITE, "到達点": "保留"}
        a = {**READ, "主な産業分野": "農林水産", "範囲": "産業の一部（狭い特例）"}
        self.assertEqual(judge(site, a, dict(a))[0], "合格")


class SampleRecord(unittest.TestCase):
    def test_manifest_matches_sample(self):
        m = json.loads((V2 / "manifest.json").read_text(encoding="utf-8"))
        s = rows(V2 / "sample.csv")
        self.assertEqual(m["種"], SEED_V2)
        self.assertEqual(m["標本"], len(s))
        self.assertEqual(sum(v["標本"] for v in m["層ごと"].values()), len(s))

    def test_no_overlap_with_first_sample(self):
        first = {r["id"] for r in rows(L / "sample.csv")}
        self.assertFalse(first & {r["id"] for r in rows(V2 / "sample.csv")})

    def test_verdicts_follow_from_lines(self):
        a = {x["id"]: x for x in json.loads((V2 / "lineA.json").read_text(encoding="utf-8"))}
        b = {x["id"]: x for x in json.loads((V2 / "lineB.json").read_text(encoding="utf-8"))}
        p = V2 / "rulings.json"
        rulings = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        verdicts = rows(V2 / "verdicts.csv")
        self.assertEqual({r["id"] for r in verdicts}, {r["id"] for r in rows(V2 / "sample.csv")})
        for r in verdicts:
            site = {k: r[f"サイト_{k}"] for k in ("類型", "分類", "到達点", "分野")}
            v, _, _ = judge(site, a[r["id"]], b[r["id"]], rulings.get(r["id"], {}).get("値"))
            self.assertEqual(v, r["判定"], r["id"])
            self.assertNotEqual(r["判定"], "割れ", f"{r['id']} は裁定が無い")

    def test_every_failure_is_resolved(self):
        failed = {r["id"] for r in rows(V2 / "verdicts.csv") if r["判定"] == "不合格"}
        res = {r["id"]: r for r in rows(V2 / "resolutions.csv")} if (V2 / "resolutions.csv").exists() else {}
        self.assertEqual(failed - set(res), set(), "決着の無い不合格がある")
        for i in failed:
            self.assertTrue(res[i]["決着"] and res[i]["原因"] and res[i]["理由"], i)


if __name__ == "__main__":
    unittest.main()
