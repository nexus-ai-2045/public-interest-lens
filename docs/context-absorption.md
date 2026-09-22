# 公益レンズ関連タスクの照合・回収

観測日: 2026-09-20（`Asia/Tokyo`）。これは確認できた範囲の台帳であり、全履歴網羅や残務ゼロの宣言ではない。製品目的の正本は `PROJECT_SSOT.md`、実装・`PR`の状態はこの`branch`と `docs/operations.md`。

## 対象・境界

- `project`: 公益レンズ
- `canonical_repo`: `nexus-ai-2045/public-interest-lens`（`PRIVATE`）
- `scope`: 同製品の会話・公式資料 `intake`・政策評価設計・取得基盤・既存`PR`および未完了作業の照合。
- `excluded`: 人格や私生活の評価、出典不明の責任帰属、無監視の全量取得、`merge`、公開、`release`、外部投稿。
- `goal`: 個人ランキングを中心とする目的と既存資産を正本化し、実装・取得・根拠検証・人間判断の残務を担当と再開条件つきで残す。
- `done_when`: 正本と機械検査を同じ実装に結び、許可された非公開`PR`状態までの事実を回収。人間レビューと旧タスクの未読範囲を隠さない。
- `external_boundary`: ユーザーが実装・`PR`まで依頼した非公開`repo`の範囲。公開・`merge`等は別承認。
- `return_path`: この実装タスク。旧タスクの全履歴と未移管の判断は本タスクへ戻す。

## 候補・証拠・判断

| 種類 | 候補 | 確認結果 | 状態 / 扱い |
|---|---|---|---|
| `Codex` `source` `task` | `codex://threads/019f9828-f509-7753-a4e1-508fe4981315`「公益レンズ」 | 複数の本文区間を確認。40〜50年の国会・立法公開情報、政策経路と停滞への影響検証、国会議員個人のワーストランキング、一般向け`Web`というユーザー決定を確認。会議録`API`・公式情報の取得を依頼した履歴も確認。旧タスクから本タスクへ公式資料・取得器作業を渡す記録がある | 関連部分は本書・`PROJECT_SSOT.md`・`docs/diet-data-coverage.md`へ整理。より古い本文ページは`API`エラー後に未読。`source` `task`はアーカイブしない |
| `Codex` `implementation` `task` | 「`Locate` `public-interest-lens`」（このタスク） | `PR` #1後続の専用実装`branch`。新旧の目的・`API`収集器・架空`UI`を統合中 | 現行実装と非公開`PR`の所有者 |
| `GitHub` `PR` | `nexus-ai-2045/public-interest-lens` `PR` #1 | 2026-09-20の`live` `read`: `MERGED`、`main`へ反映済み | この`PR`の当初実装は完了。今回の変更は別`PR`に分ける |
| `Diet` `data` `foundation` `worktree` | `.codex/worktrees/public-interest-lens/diet-data-foundation` とその作業内容 | 過去ターンで5ファイルをこの製品の実装`checkout`へ取り込んだという記録あり。収集器テストに `checkpoint` 障害・`metadata`改ざんの再開検査追加 | 今回の`checkout`の実ファイル・`diff`確認と元`worktree`保全確認が必要。再コピーしない |
| 内閣府資料 | 対象会合の`HTML` 1件＋`PDF` 16件 | 2026-09-13に旧 `.local` の`record` 17件、保存原本`SHA-256`一致17/17、18,024,253 `bytes`を`live`再検証した記録あり | 取得・`hash`一致は内容検証・著作権判断・公開承認ではない。ローカル非公開のまま |
| `Discord`由来`intake` | 旧タスクが示した`DCB` `intake` / `capture` | 保存済み`summary`には、一定範囲の可視`capture`・反復走査は成功したが、`API` `full` `capture`・添付原本は未確認とある | `raw` `Discord`本文・ユーザー`ID`・チャンネル識別子は複製しない。`coverage`と権利確認を完了扱いしない |
| 他タスク候補 | `Codex`の最近/固定された一覧、アーカイブ一覧 | 2026-09-20に直近・固定タスク66件を照合し、`source` `task`以外の明確な同テーマ候補はなし。アーカイブ一覧の連続26ページ（1,250件）のタイトル/要約も検索し、完全一致候補は0件 | 追加ページ確認は`App` `server` `tool` `error`。調査終了時の`cursor`を`durable`に保存しておらず、再開時は一覧先頭からやり直す必要がある。全件・残務ゼロとは言えない |

## 原構想と技術責務

- 主対象は政治・制度情報を判断する一般市民。入口はテーマ・議員・政策・ニュース等に広げ、根拠を辿る分析面へ集約する構想がある。
- 中心機能は個人別のワーストランキング。出席数・提出法案・個人採決・役職・発言など、確認可能な行動で政策への帰属を組む。
- 政策の結果、因果仮説、評価者が置く重み、個人への帰属、反証、未確認を分離する。係数合計は因果効果や確率ではない。
- 噂・`SNS`は発見経路に限り、一次根拠が検証されるまで加点しない。
- `NDL`国会会議録`API`は発言・会議録の入力。衆参の立法・採決、`e-Gov`法令、日本法令索引、`NDL`サーチは別の公式`source`。検索`API`の件数は全議員/政策の網羅証明ではない。
- 元タスクには`Figma`/対話型製品構築スキルの作成という過去話題もある。製品の評価ロジックとは別責務であり、既存 `public-product-dialogue` スキルの正本へ戻す。現状そのスキルの生存・配布状態は未確認なので再作成しない。

## `Fan-in`済み・未済み

確認済みの候補発見や「`handoff` `sent`」は、本文全履歴の取得、旧タスク停止受理、アーカイブ、`PR`更新と区別する。

| 論点 | 次の担当 | 次の操作と完了条件 | 停止条件 / 返却先 |
|---|---|---|---|
| 旧タスク本文の残り・末尾`cursor` | 本タスク`owner` | `Codex` `read_thread` が再稼働したら既知`cursor`から続き全ページを読み、公益レンズ関連決定を分類して本書へ追記 | `pagination`取得不能・必要範囲の上限到達は`partial`。旧タスクと本タスクへ返す。推測でアーカイブしない |
| 古い`Codex/ChatGPT` `project`・`archive`の残り | 本タスク`owner` | `thread` `list`全ページと各アーカイブページを横断、タイトル一致だけでなく本文を`read`して候補を分類 | 未読・本文不可・埋め込みだけの候補は`candidate/blocked`として残す。`global` `no-more-work`と断定しない |
| 継続タスクへの元タスク引継ぎ | 本タスク`owner` | `Deep` `Link`先本文で送信と受理を`readback`。既読・停止・残務移管が確認できるまでは旧タスクを保全 | `send_message`が不可能でも旧`task`を`unarchive`/ `archive`せず、本タスクへ返す |
| 実装`checkout`の正本 | 本タスク`owner` | `canonical` `checkout`と `.repos` `implementation` `clone`の`remote/HEAD/status/WIP`を実測。差分を保った専用`branch` 1本へ集約し、`PR`の`target` `checkout`を1つに定める | `dirty`/不一致/所有者不明ならコピー・`reset`しない。対象を本タスクへ返す |
| 議員同定と実在データ | 政策評価`owner`＋ねく | 実名・在任期・役職・個人採決・政策結果・全証拠の`schema`と訂正手順、人レビューを成立後にだけ実データ版を有効化 | `fixture` `flag`だけを外す経路は止める。人間レビューへ戻す |
| 全件同期運用 | データ運用`owner` | 公式`source`別の範囲、`rate` `limit`、容量、停止・再開・更新`watermark`、結果回収を`bounded` `job`で実地検証後に開始 | 数十時間級の全件取得・常時`runner`・通知の安全保証がない間は無制限実行しない |
| このブランチの変更 | 実装`owner` | `tests/build/audit/E2E`、`preflight`、`PRIVATE`/非`default/fast-forward`再確認後に`commit/push/PR`。新`HEAD`の`CI`、`review`、`mergeability`を回収 | 機械検査は人レビュー・`merge/public`許可ではない。人間レビュー前で停止 |

## 調査打ち切り条件

同じ`Codex` `thread`本文`API`が`cursor` `{"requestedThreadId":"019f9828-f509-7753-a4e1-508fe4981315","rolloutOrdinal":2101,"includeAnchor":false,"scope":{"kind":"turns"}}` 以降で複数回失敗したため、その経路の反復を停止している。旧`task`本文は`partial`。復旧条件は読み取り専用`thread` `API`が全ページを返すこと。最近/固定66件と`archive`の1,250件だけを照合し、残り`archive`は未検索。検索した各層・`cursor`・本文`read` `status`を追記し、同じ候補の循環探索を避ける。現状「テーマの残務0」「関連タスクなし」「旧タスクの自己アーカイブ安全」とは判定しない。
