# 公益レンズ エージェント指示

- ユーザー向け・運用向け文書は日本語を既定とする。
- 架空データと実在データを混在させない。
- 確認済み事実、機械計算、AI 解釈、未確認を分離する。
- 実在人物のランキングや断定的な人格評価を生成しない。
- 出典、観測時刻、対象範囲、不確実性を保持する。
- 個々のタスクで使う外部資料は `scripts/register_external_material.py` で `.local/external-materials/<task-id>/` に保存する。
- 外部資料を保存した事実と、資料内容の正しさを分離する。内容は初期状態を `unverified` とする。
- `.local/`、`.env*`、credential、個人情報を Git に追加しない。
- `main` へ直接 push しない。
- GitHub リポジトリ作成、push、プルリクエスト、公開、外部共有は現在会話での明示承認を必要とする。
- 新規 GitHub リポジトリは private を既定とする。
- 完了前に `npm test`、`npm run build`、`npm audit --audit-level=moderate` を実行する。
- 外部資料登録処理を変更した場合は `python -m unittest discover -s tests -v` も実行する。
