# 公益レンズ

公益レンズは、公開された活動記録を、根拠と不確実性を保ったまま比較・探索するための判断支援アプリです。

このリポジトリの MVP（最小実用版）は架空データだけを使用します。人物や団体の「良し悪し」を AI が決めるランキングではありません。画面では、次の4種類を分離して表示します。

- 確認済み事実
- 機械計算
- AI 解釈
- 未確認

## ローカル実行

```powershell
Set-Location app
npm install
npm run dev
```

既定のローカル URL は `http://127.0.0.1:5173` です。

## 検証

```powershell
Set-Location app
npm test
npm run build
npm audit --audit-level=moderate
```

## 文書

- `spec-card.md`: 目的、入力、出力、停止線
- `run-card.md`: 実装・検証・運用の記録
- `human-review-checklist.md`: 人間レビュー項目
- `MIGRATION.md`: 元リポジトリからの切り出し記録

## 公開境界

GitHub リポジトリ作成、push、プルリクエスト、公開、外部共有、実在人物データの導入は、現在会話での明示的な人間承認を別途必要とします。新規 GitHub リポジトリを作る場合は private を既定とします。
