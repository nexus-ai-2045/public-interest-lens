# 貢献の手順

目的の正本は [目的と責務](PROJECT_SSOT.md)、算定契約は `app/src/ranking.ts` です。既存の収集器・資料登録処理・テストを優先し、同じ役割の実装を増やさないでください。

## ローカルで確認する

必要な環境は `Node.js` 22以上と `Python` 3.12以上です。画面の起動は [案内](README.md)、有限の資料取得と復旧は [運用手順](docs/operations.md)を参照してください。

リポジトリ直下で収集・資料登録のテストを実行します。

```powershell
python -m unittest discover -s tests -v
```

画面側は `app/` で検証します。

```powershell
cd app
npm ci
npm test
npm run build
npm audit --audit-level=moderate
npx playwright install chromium
npm run test:e2e
```

## 変更とレビュー

- 一つの変更目的ごとにブランチとプルリクエストを分け、目的・差分・検証結果・未確認点を日本語で記載してください。
- 不具合修正では、可能な範囲で修正前に失敗する回帰テストを追加してください。
- 架空データと実資料を混在させないでください。記録不足を0点や個人の不活動として扱わないでください。
- 個人の賛否を党籍から補完せず、所属・訪問・発言だけで実績点を付けないでください。
- 実在人物の評価、評価方法の変更、サイト公開は、根拠・反証・訂正手順を確認する別の人間レビュー対象です。
- `main`への直接送信、履歴書換え、マージ、公開、設定変更をテスト成功だけで許可されたと判断しないでください。

## 保存してよい情報

原資料・取得結果・認証情報・私的なタスク参照は`Git`へ追加しないでください。原資料は既存の登録処理で `.local/` に保管します。公開資料であっても、取得と転載許可は別の確認です。

コードのライセンスは [ライセンス](LICENSE)（`MIT`）です。外部資料の転載権は含みません。脆弱性や秘密情報の報告は [セキュリティ方針](SECURITY.md)の手順に従い、公開の問題報告へ詳細を貼らないでください。

## スクリプト化と方針変更時の見直し（ねく 2026-10-30）

- 2回以上くり返す処理は `scripts/` にスクリプトとして置く（手順をチャットや PR 本文にだけ残さない）。
- 計算やデータの方針を変えたら、同じ PR か直後の PR で、関係するスクリプトをリファクタする。古い前提のコードは消し、`ruff check <変えたファイル>` とテストを通す。
- 評価の検証は `python3 scripts/build_evaluation_ledger.py build` → `scripts/compare_verification.py` → `scripts/report_verification.py` の順。ロジック検査は `scripts/check_evaluation_logic.py`（`tests/test_evaluation_logic.py` が基準より増えたら落とす）。
