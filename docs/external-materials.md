# 外部資料のタスク別保存

## 目的

個々の調査・実装タスクで開いた PDF、文書、画像、データを、取得元と用途を失わずローカル保存します。

保存した資料は、その内容が正しいことを自動的に意味しません。次の2つを分離します。

- 資料を特定URLから取得・保存した事実
- 資料内の主張が正しいかどうか

## 保存構造

```text
.local/external-materials/
└── <task-id>/
    └── <date>-<sha256-prefix>/
        ├── original.<extension>
        └── record.json
```

`.local/` は Git 追跡対象外です。著作権資料、個人情報、大容量ファイル、限定公開資料をGitHubへ混入させないため、この境界を変更しません。

## 登録手順

1. 承認されたブラウザ経路などで資料をローカルへ保存する。
2. URL、タスクID、資料名、利用目的を付けて登録する。
3. 出力された `record.json` と原本の存在を確認する。

最初に `--dry-run` を付け、保存予定先と入力検証を確認します。

```powershell
python scripts/register_external_material.py `
  --input-file "C:\path\to\downloaded-report.pdf" `
  --source-url "https://example.go.jp/report.pdf" `
  --task-id "policy-review-001" `
  --title "規制改革資料" `
  --purpose "制度変更の根拠確認" `
  --dry-run
```

問題がなければ `--dry-run` を外して登録します。コマンドは `action`、`target`、`dry_run`、`changed`、`verified`、`report_path`、`next_action` をJSONで返します。

## `record.json` の主要項目

- `task_id`: 資料を使ったタスク
- `source_url`: 取得元URL
- `observed_at`: 資料を観測した日時
- `saved_filename`: 保存した原本
- `sha256`: 同一性確認用ハッシュ
- `bytes` / `media_type`: ファイル情報
- `content_verification`: 内容検証状態。初期値は必ず `unverified`
- `source_actor` / `source_event_time`: 未確認なら `unknown`

## 停止線

- `file:` URL、localhost、非公開IPを出典URLとして登録しない。
- secret、credential、認証済み画面の私的内容を保存しない。
- 保存だけで資料内の主張を「確認済み事実」へ昇格しない。
- 外部資料のGit追加、外部共有、公開は別の人間承認を必要とする。
- URLからの自動ダウンロードはこの初版では行わない。ブラウザ側の認証・利用条件・ロボット制御を迂回しない。
