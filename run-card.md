---
title: "公益レンズ run card"
type: run-card
status: local-verified
spec_card: "spec-card.md"
target_repo: "public-interest-lens"
target_branch: "codex/repository-extraction"
created: 2026-07-28
owner: nexus_ai
human_review_required: true
external_action: private_draft_pr_created
---

# 公益レンズ 実行カード

## Scope

公開事実、機械計算、AI 解釈、未確認を分離し、重みを利用者が調整できる架空データのローカル MVP。

## Tags

`@intake` `@design` `@security` `@tdd` `@implement` `@verify` `@ops` `@github` `@human-review` `@cleanup`

## Design

- [x] 判断支援でありランキングではないことを主画面に表示。
- [x] 比較、評価軸、根拠、時系列を一画面で接続。
- [x] ImageGen のコンセプトと実装スクリーンショットを保存。

## Research

- [x] Discord の指定2メッセージを既存の内部ブラウザで確認。
- [x] 由来 URL と可視本文の要約を追跡対象外に保存。
- [x] 個々のタスクで開く外部資料を `.local/external-materials/` に原本とmanifestで保存する仕組みを追加。
- [ ] 実データ接続に使う公式 API と利用条件は未調査。

## Security

- [x] Discord URL、発言者、本文を公開 Git 履歴から除外。
- [x] 実在人物のデータを使わない。
- [x] AI 解釈を確認済み事実として表示しない。
- [x] 認証情報や外部送信を必要としないローカル構成。

## TDD

- [x] 重み付き計算とゼロ重みの境界テストを先に作成。
- [x] 根拠4分類の表示ラベルをテスト。
- [x] 6テストが通過。
- [x] 外部資料登録のURL制約、タスクID制約、原本コピー、SHA-256、manifestをテスト。

## Implementation

- [x] `codex/public-interest-lens-20260728` worktree で実装。
- [x] React、TypeScript、Vite で MVP を実装。
- [x] 仕様、運用、人間レビュー、GitHub 計画を同梱。

## Verification

- [x] `npm test`: 6 tests passed。
- [x] `npm run build`: production build passed。
- [x] `npm audit --audit-level=moderate`: 0 vulnerabilities。
- [x] `python -m unittest discover -s tests -v`: 外部資料登録の6 tests passed。
- [x] `python -m py_compile`: 登録スクリプトとテストの構文検証 passed。
- [x] `--dry-run`: 保存予定をJSONで返し、`changed: false` を確認。
- [x] 内部ブラウザで見出し、比較表、主体選択、根拠フィルターを確認。

## Operations

```powershell
Set-Location app
npm install
npm run dev
```

- readiness: `http://127.0.0.1:5173` の title が `公益レンズ` で、比較表が1件表示される。
- external-material readiness: `python -m unittest discover -s tests -v` が通り、登録先が `.local/external-materials/<task-id>/` になる。
- rollback: 独立リポジトリの変更だけを戻す。`.local/intakes/` は非公開記録として別管理する。
- 既知の制約: データは架空。実データの正確性、網羅性、更新性は `unknown`。

## GitHub Plan

- [x] PR に含めるもの、含めないもの、人間レビュー項目を文書化。
- [x] Private repo作成・push・Draft PR #1作成を現在会話の明示承認後に実施
- [ ] Merge is waiting for human explicit approval
- [ ] Public release, share, Discord post, send, and repository visibility changes are external actions gated by human explicit approval
- [ ] Computer Use requires explicit approval

## Cleanup

- [x] `node_modules/`、`dist/`、`.local/` は Git 追跡対象外。
- [x] 誤って作成した入れ子の一時ディレクトリを削除。
- [ ] 人間レビュー後、不要になった専用 worktree を削除。

## Evidence

```text
vitest v4.1.10: 1 file, 6 tests passed
vite v7.3.6: 1579 modules transformed, build passed
npm audit: 0 vulnerabilities
in-app browser: title=公益レンズ, table count=1, evidence filter 6 -> 5
GitHub: nexus-ai-2045/public-interest-lens (private), Draft PR #1
```
