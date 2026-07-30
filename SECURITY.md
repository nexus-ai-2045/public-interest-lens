# セキュリティ方針

## 対象

公益レンズのアプリ、データモデル、評価ロジック、運用文書を対象とします。

## 境界

- secret、token、Discord credential、GitHub token、`.env` を commit しない。
- 非公開の由来本文や個人情報を commit しない。
- 実在人物の評価データを、人間レビューなしに追加・公開しない。
- AI 解釈を確認済み事実として表示しない。
- GitHub リポジトリ作成、push、プルリクエスト、公開、外部共有、repository visibility の変更は、現在会話での明示承認なしに行わない。
- 新規 GitHub リポジトリは private を既定とする。

## 報告

公開前は、露出するファイル、commit history、README、license、secret scan、personal path scan、人間レビュー状況を確認します。
