# 公益レンズ

国会・立法の公開記録から、日本の長期停滞に関わる政策判断と国会議員個人の責任を検証し、ワーストランキングと根拠を`Web`で閲覧するプロジェクトです。目的・配置・境界の正本は [`PROJECT_SSOT.md`](PROJECT_SSOT.md) です。

現在の画面は架空の議員・政策・証拠を用いた算定デモです。実在議員の評価、40〜50年間の全量取得、長期停滞の因果認定は未完了です。

## できること

- 人物のワースト順位、政策別の寄与点、行動、反証、根拠を確認する。
- 期間・分野の重みを変え、基準重みとの順位変化を見る。
- 証拠不足は評価不能とし、未確認情報や`AI`解釈による加点を防ぐ。
- 既存の国会会議録収集器で、公式`API`を逐次取得し、ハッシュと再開位置を非公開保管する。

## ローカル実行と検証

```powershell
cd app
npm ci
npm test
npm run build
npm audit --audit-level=moderate
npm run dev
```

画面は `http://127.0.0.1:5173`。`Python`検証はリポジトリ直下で `python -m unittest discover -s tests -v` を実行します。

## 正本と運用

- [仕様カード](spec-card.md): 入出力・算定の境界。
- [運用手順](docs/operations.md): スモーク・再開・失敗時対応・残務。
- [国会データの取得範囲](docs/diet-data-coverage.md): 公式ソースと取得状態。
- [`ADR` 0002](docs/adr/0002-person-ranking-and-evidence-boundary.md): 人物ランキングへの目的修正。
- [人間レビュー](human-review-checklist.md): 算定方法と実在データ公開の判断。
- [外部資料保存](docs/external-materials.md): 既存登録処理を使う。取得と真偽を分離。
- [移行記録](MIGRATION.md) / [旧実行記録](run-card.md): 過去の由来。

生データは `.local/` に保存し、`Git`や`Web`配信物には含めません。非公開`PR`の検証と、人間による実在評価のレビュー・`Web`公開承認は別です。
