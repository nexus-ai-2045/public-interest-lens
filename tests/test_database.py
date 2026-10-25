"""データベース（scripts/build_database.py）とグラフ用の集計 charts.json を確かめる。

charts.json が古いまま main に入ると /numbers の数字がほかのページと食い違う。
直し方：python3 scripts/build_database.py（または scripts/rebuild_public.py）を回し、charts.json をコミットする。
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import build_database, compare_db, query_db

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "app" / "public" / "distribution"
from _data_gate import requires_data  # noqa: E402


class DatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "db.sqlite"
        build_database.build(cls.path, write_charts=False)
        cls.con = sqlite3.connect(cls.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()
        cls.tmp.cleanup()

    def one(self, sql: str, *args):
        return self.con.execute(sql, args).fetchone()[0]

    def test_inputs_digest_covers_every_file_read(self) -> None:
        read = {str(f.relative_to(ROOT)) for f in build_database.READ_FILES}
        self.assertTrue(any(r.startswith("data/acquired/domestic-stats/") for r in read), "指標の CSV がハッシュの対象にない")
        self.assertIn("data/derived/allocation-v1/votes.csv", read)
        self.assertIn("app/public/distribution/world-gdp.json", read)

    def test_org_action_dates_keep_the_estimate_mark(self) -> None:
        rows = self.con.execute("SELECT acted_on, acted_on_text FROM org_actions WHERE acted_on_text LIKE '%推定%'").fetchall()
        self.assertTrue(rows, "推定の印つきの日付が見つからない")
        for acted_on, text in rows:
            self.assertIn("推定", text)

    def test_points_keep_their_own_source_when_it_differs(self) -> None:
        import csv
        path = ROOT / "data" / "acquired" / "more-stats" / "npl_fsa_all_banks.csv"
        if not path.exists():
            self.skipTest("不良債権の表が無い")
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        urls = {r["出典URL"] for r in rows}
        self.assertGreater(len(urls), 1)
        got = {u for (u,) in self.con.execute(
            "SELECT DISTINCT coalesce(p.source_url, s.source_url) FROM points p JOIN series s USING (series_id) WHERE s.dataset = 'more-stats/npl_fsa_all_banks.csv'")}
        self.assertEqual(got, urls)

    def test_period_kind_prefers_the_explicit_breakdown(self) -> None:
        self.assertEqual(build_database.period_kind("暦年", "暦年・年度別空港管理状況調書", "乗降客数"), "暦年")
        self.assertEqual(build_database.period_kind("年度", "暦年・年度別空港管理状況調書", "乗降客数"), "年度")
        self.assertEqual(build_database.period_kind("", "年度の集計", ""), "年度")
        self.assertEqual(build_database.period_kind("", "", ""), "暦年")

    def test_world_gdp_keeps_each_series_source(self) -> None:
        world = json.loads((DIST / "world-gdp.json").read_text(encoding="utf-8"))
        for c in world["countries"]:
            for key in c["series"]:
                url = self.one("SELECT source_url FROM series WHERE series_id = ?", f"world-gdp:{c['code']}:{key}")
                self.assertEqual(url, c["sourceUrls"][key], f"{c['code']} {key}")
                unit = self.one("SELECT unit FROM series WHERE series_id = ?", f"world-gdp:{c['code']}:{key}")
                self.assertNotEqual(unit, key, "単位に系列キーが入っている")
                note = self.one("SELECT note FROM series WHERE series_id = ?", f"world-gdp:{c['code']}:{key}")
                self.assertIn(c["provider"], note)
                self.assertIn("推計", note)

    def test_all_enacted_laws_and_published_amounts(self) -> None:
        ranking = json.loads((DIST / "ranking.json").read_text(encoding="utf-8"))
        self.assertEqual(self.one("SELECT COUNT(*) FROM laws"), ranking["counts"]["enacted"])
        self.assertEqual(self.one("SELECT COUNT(*) FROM laws WHERE outcome = '額'"), ranking["counts"]["published"])
        self.assertEqual(self.one("SELECT COUNT(*) FROM laws WHERE certainty IN ('高','中','低')"), ranking["counts"]["confirmed"])
        self.assertEqual(self.one("SELECT COUNT(*) FROM decisions WHERE kind = '法律'"), ranking["counts"]["enacted"])

    def test_foreign_keys_hold(self) -> None:
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_observation_sizes_match_published_laws(self) -> None:
        self.assertEqual(self.one("SELECT SUM(n_laws) FROM observations"), self.one("SELECT COUNT(*) FROM laws WHERE outcome = '額'"))

    def test_allocations_add_up_to_each_law_share(self) -> None:
        """人・会派・名前不明の配分の合計は、法律の分（観測の額を本数で割ったもの）に一致する（最大剰余法）。"""
        members = json.loads((DIST / "members.json").read_text(encoding="utf-8"))
        for law in members["laws"]:
            # 反対票（oppose）は法律の額の配分とは別に数える（設計決定0014）。
            total = self.one("SELECT SUM(median) FROM allocations WHERE law_id = ? AND role != 'oppose'", law["id"])
            expected = abs(int(law["amount"]["median"] / law["observationLaws"]))
            self.assertLessEqual(abs(total - expected), 2, law["id"])

    def test_fractions_do_not_exceed_one(self) -> None:
        """役職の帳簿と行動の行で割合を二重に数えない。反対票を除いた割合の合計は1を超えない。"""
        over = self.con.execute(
            "SELECT law_id, SUM(fraction) FROM allocations WHERE role != 'oppose' GROUP BY law_id HAVING SUM(fraction) > 1.000001").fetchall()
        self.assertEqual(over, [])

    def test_every_allocated_law_has_its_vote_and_actions(self) -> None:
        """人に配った法律には、参議院の票数と、根拠の行動（一次資料つき）がデータベースにある（自動の関与・反対票を含む）。"""
        missing = self.con.execute(
            "SELECT DISTINCT a.law_id FROM allocations a LEFT JOIN sangiin_votes v USING (law_id) WHERE a.recipient_kind = 'person' AND v.law_id IS NULL").fetchall()
        self.assertEqual(missing, [])
        for role, action in (("vote", "vote"), ("oppose", "oppose")):
            orphan = self.con.execute(
                "SELECT a.law_id, a.recipient_id FROM allocations a WHERE a.role = ? AND NOT EXISTS (SELECT 1 FROM involvements i WHERE i.law_id = a.law_id AND i.person_id = a.recipient_id AND i.action = ? AND i.source_id IS NOT NULL) LIMIT 5",
                (role, action)).fetchall()
            self.assertEqual(orphan, [], role)

    def test_member_scores_match_members_json(self) -> None:
        members = json.loads((DIST / "members.json").read_text(encoding="utf-8"))
        for m in members["members"][:50]:
            self.assertEqual(self.one("SELECT net_median FROM member_scores WHERE ledger = '確か' AND person_id = ?", m["id"]), m["net"]["median"], m["id"])

    def test_spec_versions_are_loaded(self) -> None:
        versions = {c: v for c, v in self.con.execute("SELECT component, version FROM method_versions")}
        self.assertEqual(versions["loss"], "loss-rule-v1")
        self.assertEqual(versions["allocation-v0"], "causal-shapley-v1")
        self.assertRegex(self.one("SELECT value FROM meta WHERE key = 'spec'"), r"^method-spec-v\d+\.\d+$")

    def test_registry_statuses(self) -> None:
        statuses = {s for (s,) in self.con.execute("SELECT DISTINCT status FROM source_registry")}
        self.assertLessEqual(statuses, {"取得済み", "取得できる（未取得）", "通信先の許可待ち", "サイトが拒否（経路を探す）"})
        self.assertGreater(self.one("SELECT COUNT(*) FROM source_registry WHERE category = '金融政策'"), 0)

    def test_fiscal_tables_are_filled(self) -> None:
        if not (ROOT / "data" / "acquired" / "fiscal" / "fiscal_flows.csv").exists():
            self.skipTest("財政の表が無い")
        # 為替介入は実施日ごとの決定と額
        self.assertGreater(self.one("SELECT COUNT(*) FROM decisions WHERE kind = '為替'"), 300)
        self.assertEqual(self.one("SELECT COUNT(*) FROM decisions d WHERE kind = '為替' AND NOT EXISTS (SELECT 1 FROM decision_amounts a WHERE a.decision_id = d.decision_id)"), 0)
        # 主要経費別（合計・内訳を除く）を足すと、表の「合計」と合う（年度・段階ごと）
        rows = self.con.execute("""
            SELECT f.fiscal_year, f.stage, SUM(f.amount), t.amount FROM fiscal_flows f
            JOIN fiscal_flows t ON t.fiscal_year = f.fiscal_year AND t.stage = f.stage AND t.account = f.account AND t.category = '主要経費別（合計）' AND t.item = '合計'
            WHERE f.account = '一般会計' AND f.category = '主要経費別' GROUP BY f.fiscal_year, f.stage""").fetchall()
        self.assertGreater(len(rows), 200)
        for year, stage, total, published in rows:
            self.assertAlmostEqual(total / published, 1, places=3, msg=f"{year} {stage}")
        # 当初・補正の行は予算の決定に結びつく
        self.assertEqual(self.one("SELECT COUNT(*) FROM fiscal_flows WHERE account = '一般会計' AND stage IN ('当初', '補正') AND decision_id IS NULL"), 0)
        self.assertEqual(self.one("SELECT COUNT(*) FROM decisions WHERE kind = '国策' AND decision_id LIKE '国策-honebuto-%' AND decided_on IS NULL"), 0)
        self.assertGreater(self.one("SELECT COUNT(*) FROM fiscal_flows WHERE account = '地方（純計）' AND item = '地方交付税'"), 4)

    def test_series_keep_notes_that_differ_by_year(self) -> None:
        note = self.one("SELECT note FROM series WHERE series_id = 'kanko:訪日外国人旅行消費額'")
        self.assertIn("試算値", note)  # 2020〜2022年だけの注記も、年を付けて残す
        self.assertIn("確報", note)

    @requires_data("industry_va")
    def test_series_have_points(self) -> None:
        self.assertEqual(self.one("SELECT COUNT(*) FROM series s WHERE NOT EXISTS (SELECT 1 FROM points p WHERE p.series_id = s.series_id)"), 0)
        self.assertGreater(self.one("SELECT COUNT(*) FROM points WHERE series_id LIKE 'oecd-t6:JPN:%'"), 100)

    def test_every_named_query_runs(self) -> None:
        params = {"person": "麻生太郎", "law": "閣法-196-2", "label": "総合", "series": "cpi:2020基準:0001", "country": "JPN", "industry": "J",
                  "kind": "法律", "from": "2000-01-01", "to": "2001-12-31", "limit": "5"}
        for name, (_, sql) in query_db.load_queries().items():
            cols, _ = query_db.run(self.con, sql, params)
            self.assertTrue(cols, name)

    def test_compare_same_db_reports_no_change(self) -> None:
        text = compare_db.compare(self.path, self.path, top=5)
        self.assertIn("- なし", text)
        self.assertNotIn("圏外", text)

    def test_committed_charts_are_current(self) -> None:
        committed = json.loads((DIST / "charts.json").read_text(encoding="utf-8"))
        fresh = build_database.charts(self.con, self.one("SELECT value FROM meta WHERE key = 'spec'"))
        fresh["inputs"] = build_database.inputs_digest(build_database.CHART_INPUTS)
        self.assertEqual(committed, fresh, "charts.json が古い。python3 scripts/build_database.py で作り直す")


if __name__ == "__main__":
    unittest.main()
