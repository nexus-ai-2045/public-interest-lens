# `ADR` 0002: 人物ランキングを中心とする製品目的と証拠境界

日付: 2026-09-12。状態: 製品目的はユーザー決定済み。算定方法と実在データ公開はレビュー対象。

## 背景と決定

旧`MVP`の人物ランキングを否定する文言は、本来の目的を制約していた。ユーザーが国会議員個人のワーストランキングを中心機能と明示したため、目的を `PROJECT_SSOT.md` に正本化する。

順位を先に決めて理由を後付けせず、政策単位の悪影響評価、因果根拠の評価係数、個人の確認できる関与、分野重みを分離する。算定は `app/src/ranking.ts` に一本化する。同じ人物・政策の重複入力は拒否し、未確認や`AI`解釈だけの入力は順位に加算しない。

## 算定の限界

初期方式は複合指標のシナリオ計算。係数は研究による推定確率ではない。得点は政策件数に依存する累積値であり、100点満点や経済損失額ではない。未収集の政策、在職期間、権限差、良い政策の効果を補正した総合的な人物評価でもない。

基準重みと変更後の順位を併記する。証拠不足は評価不能として表示する。全件性は公式ソースごとに別途検証し、検索終了や`API`スモークを全議員の網羅と呼ばない。

## 先行概念と根拠

- `OECD/JRC`『`Handbook` `on` `Constructing` `Composite` `Indicators`』: 指標の構成、重み、不確実性、感度分析の既存概念を採用する。新しい因果推論法を発明したと主張しない。
  [`OECD`の複合指標ハンドブック](https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators-methodology-and-user-guide_9789264043466-en.html)
- 欧州委員会`JRC`『`Step` 8: `Sensitivity` `analysis`』: 仮定変更に対する順位変動の点検を参考にする。今回の基準重み比較は限定的な点検で、全面的な感度分析ではない。
  [欧州委員会の感度分析ガイド](https://knowledge4policy.ec.europa.eu/composite-indicators/toolkit_en/navigation-page/10-step-guide_en/step-8-sensitivity-analysis_en)
- 国立国会図書館の検索用`API`仕様: 会議録の取得契約として再利用する。
  [国立国会図書館の`API`仕様](https://kokkai.ndl.go.jp/api.html)

いずれも2026-09-12に公式ページを確認。政治家への具体的評価はこれらの資料から導いていない。

## 回帰検出と修復

目的を否定する旧文言を正本文書に再導入した場合は `tests/test_product_contract.py` が失敗する。数値・参照・順位の不整合は `ranking.test.ts`、取得の再開・欠落は `test_fetch_diet_minutes.py` で検出する。修正後に同じ検査を再実行し、未解決は `docs/operations.md` に担当・再開条件付きで残す。
