# 根拠値の台帳

- 正本：`ledger.json`（`entries` の配列）。機構の対応表：`mapping.json`。
- 項目・採否の決まり：[評価方法設計書](../../docs/評価方法設計書.md) の4章。
- 検査：`python3 scripts/check_evidence_ledger.py`（テスト `tests/test_evidence_ledger.py`）。
- 追加は PR で。DOI を Crossref で確かめ、収集・照合1・照合2の3者が一致した値だけ `verified`。割れたものは `held`（計算に使わない）。
