# 公益レンズ エージェント指示

- ユーザー向け・運用向け文書は日本語を既定とする。
- 架空データと実在データを混在させない。
- 確認済み事実、機械計算、AI 解釈、未確認を分離する。
- 製品目的の正本は `PROJECT_SSOT.md`。国会議員個人の政策判断への責任を評価するワーストランキングを中心機能とする。
- 評価は公開された行動・政策結果への関与に限定する。人格評価、噂による加点、党籍からの個人採決の推定はしない。
- 実在データの評価方法（判定基準）は人間レビューする。1件ごとの出典・反証・個人への帰属の判断は、ファクトと実測だけを材料に2系統の AI が一致したものを採用する（`docs/adr/0007-ai-judgment-facts-and-measurements.md`）。Web公開は現在会話で対象を提示した明示承認後に一括で行う。架空データのテスト成功を実在評価の妥当性と扱わない。
- 出典、観測時刻、対象範囲、不確実性を保持する。
- 個々のタスクで使う外部資料は `scripts/register_external_material.py` で `.local/external-materials/<task-id>/` に保存する。
- 外部資料を保存した事実と、資料内容の正しさを分離する。内容は初期状態を `unverified` とする。
- `.local/`、`.env*`、credential、個人情報を Git に追加しない。
- `main` へ直接 push しない。
- GitHub リポジトリ作成、push、プルリクエスト、公開、外部共有は現在会話での明示承認を必要とする。
- 新規 GitHub リポジトリは private を既定とする。
- 完了前に `npm test`、`npm run build`、`npm audit --audit-level=moderate` を実行する。
- 外部資料登録処理を変更した場合は `python -m unittest discover -s tests -v` も実行する。

## 個人名義を出さない（絶対）

- 持ち主の個人名義（本名、私用のメール、OS のアカウント名、端末名、それらを含むホームのパス）を、チャット・PR・Issue・コミット（名義とメッセージ）・ファイル・共有フォルダ・ログのどこにも書かない。確認のためでも書かない。
- 検査が「照合する名前が無い」などで止まっても、ユーザーに名前を書かせる案や、エージェントが値を書き込む案を出さない。照合する値は `local_identity_guard.py`（repo-preflight の `scripts/`）が実行中の環境から自動で集め、表示も保存もしない。
- 値を表示するコマンド（`whoami`、`id -F`、`echo $HOME`、`git config user.email` など）の出力をチャットやファイルへ貼らない。比べる必要があるときは一致・不一致だけを出す。
- コミットの作成者とコミッターは公開用の名義（nexus-ai-2045 の GitHub noreply）だけにする。書き込み前に `python <repo-preflight>/scripts/local_identity_guard.py --public-name nexus-ai-2045 --public-name nexus_ai config` で確かめ、push 前は同じスクリプトの `check` を使う。
- push 前検査や identity guard を緩めない・回避しない（`--no-verify`、`core.hooksPath` の付け替え、照合リストの無効化をしない）。止まったら、値を出さずに原因の箇所を直す。
