# リポジトリ切り出し記録

## 由来

- source repository: `nexus-ai-2045/discord-to-product`
- source local branch: `codex/public-interest-lens-20260728`
- source commit: `41c8220`
- source path: `products/public-interest-lens`
- extracted_at: `2026-07-30`（Asia/Tokyo）

## 切り出し方針

既存のアプリ、設計画像、仕様カード、実行カード、人間レビュー項目を独立リポジトリへ複製する。非公開の由来記録は `.local/intakes/` に複製し、Git 追跡対象外を維持する。

元リポジトリ内の製品ディレクトリは、独立リポジトリの検証が完了するまで削除しない。削除する場合は、元リポジトリ側の独立した変更として実施する。

## 境界

この記録はローカル切り出しのみを示す。GitHub リポジトリ作成、push、プルリクエスト、公開、外部共有は実施していない。
# 追加統合（2026-09-12）

同じ独立リポジトリの未コミット `codex/diet-data-foundation` 作業から、会議録収集器、テスト、公式ソース一覧、coverage文書、ADR 0001を取り込んだ。元の作業ツリーと非公開保管物は維持する。現在の目的は `PROJECT_SSOT.md`、差分の検証記録は `docs/operations.md` を参照。
