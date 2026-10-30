# treaties-v1：条約と承認案件の結果一覧

`data/acquired/treaty-census/treaties.csv`（541件、第142回国会以降）の1件ごとに、必ず1つの結果と理由を付けた台帳。決め方は `docs/adr/0023-treaties-and-approvals.md`。

生成：`python3 scripts/build_treaty_outcomes.py` → `outcomes.csv`。確認：`tests/test_treaty_census.py`（id の重複なし・理由が空でない・コミット済みが生成結果と同じ・規則に当たらない題名が5%未満）。

結果は 保留（経済への経路がある類型で、外国の研究を調べていないもの）55／測定できない 334／評価対象外 152。経済連携・租税・投資・航空の184件は R58（2026-10-30）で外国の研究を調べ、向きが割れて額を作れないので「測定できない」にした（根拠 `data/evidence/treaties/r58.json`）。経路の符号 TR0〜TR14 と TR99 の定義は `scripts/build_treaty_outcomes.py` の RULES。額・向きの列は無い（作っていない）。
