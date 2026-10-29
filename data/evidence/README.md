# 根拠値の台帳

- 正本：`ledger.json`（`entries` の配列）。機構の対応表：`mapping.json`。
- 項目・採否の決まり：[評価方法設計書](../../docs/評価方法設計書.md) の4章。
- 検査：`python3 scripts/check_evidence_ledger.py`（テスト `tests/test_evidence_ledger.py`）。
- 追加は PR で。DOI を Crossref で確かめ、収集・照合1・照合2の3者が一致した値だけ `verified`。割れたものは `held`（計算に使わない）。

- 現在の中身（ledger-v1）：164件（3者一致 `verified` 127・`held` 37）。`held` は計算に使わない（理由は `held_reason`）。DOI のあるものは Crossref の題名・著者・年が一致したものだけ `verified`。
- `impact_ranking.json`：台帳の効果量から仕組み別の影響度を並べた表（式と読み方は [影響度ランキング](../../docs/影響度ランキング.md)）。深掘りの優先順位の基準。
- 各件の `verification.verified_at` は、原文を取得し3者で照合した日（YYYY-MM-DD、検査で必須）。公的資料は更新されるので、この日付の時点の値として扱う。
- `estimate.low/high` は、原文が区間（信頼区間・報告された範囲）を示したときだけ入れる。別の対象集団・シナリオ・時点の値は `other_values_not_interval` に分ける。

## 候補（candidates.json）
文献調査（2026-10-29）の推定値のうち、調査側の照合が「一致」の行（597件）。収集と1回の照合だけで、台帳の3者照合（盲検の2者が2%以内で一致、Crossref の題名・著者・年）は未了なので、**計算・影響度ランキングには使わない**。検査（`scripts/check_evidence_ledger.py`）は、台帳や mapping が候補を参照したら落とす。
昇格の順番：影響度の上位の機構（ICT・参入障壁・新陳代謝）に効く行から、盲検2者で照合し、通ったものを `ledger.json` の `lit-*`（`literature_row` が元の行）へ入れる。今回は11行を審査し、8件が3者一致、3件が `held`（値の不一致2・読み取り不一致1）。
行ごとの原本・引用は共有フォルダの文献調査の表を参照。バックテストの正解データ（答えの分かっている事例集）は台帳とは別の扱い。

## バックテスト
正解データ `backtest_cases.json`（事例集の一致49件。ラベルは2系統の一致分だけ採用、系統2は `backtest_labels_line2.json`）、対応表 `backtest_mapping.json`、固定した結果 `backtest/`。測定は `python3 scripts/backtest.py`（定義は [設計決定0020](../../docs/adr/0020-backtest-accuracy-definition.md)、結果は [docs/バックテスト.md](../../docs/バックテスト.md) と /methodology）。台帳とは別の扱い。

- `backtest_r50_search.json`：R50（バックテストの本命の事例を文献で足す調査）の記録。8領域で見た候補45件の題名・出典・読めた範囲・棄却理由。採用0件。本文を読めなかった候補は「確認できなかった」と区別して残してある。
- `backtest_foreign_pool.json` / `backtest_foreign_labels.json` / `backtest_foreign_match.json`：v2（R52、[設計決定0021](../../docs/adr/0021-backtest-transplant-v2.md)）の入力。外国の研究57件（事例集27件＋領域ごとの調査30件、効果が正・負・零のどれも入れた）、結果指標の種類・向き・出来事の2系統ラベル、日本の事例ごとの「同種」判定（2系統）。日本の結果は見せずに付けた。
