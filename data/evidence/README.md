# 根拠値の台帳

- 正本：`ledger.json`（`entries` の配列）。機構の対応表：`mapping.json`。
- 項目・採否の決まり：[評価方法設計書](../../docs/評価方法設計書.md) の4章。
- 検査：`python3 scripts/check_evidence_ledger.py`（テスト `tests/test_evidence_ledger.py`）。
- 追加は PR で。DOI を Crossref で確かめ、収集・照合1・照合2の3者が一致した値だけ `verified`。割れたものは `held`（計算に使わない）。

- 現在の中身（ledger-v1）：153件（3者一致 `verified` 119・`held` 34）。`held` は計算に使わない（理由は `held_reason`）。DOI のあるものは Crossref の題名・著者・年が一致したものだけ `verified`。
- `impact_ranking.json`：台帳の効果量から仕組み別の影響度を並べた表（式と読み方は [影響度ランキング](../../docs/影響度ランキング.md)）。深掘りの優先順位の基準。
- 各件の `verification.verified_at` は、原文を取得し3者で照合した日（YYYY-MM-DD、検査で必須）。公的資料は更新されるので、この日付の時点の値として扱う。
- `estimate.low/high` は、原文が区間（信頼区間・報告された範囲）を示したときだけ入れる。別の対象集団・シナリオ・時点の値は `other_values_not_interval` に分ける。
