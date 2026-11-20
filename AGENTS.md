# 公益レンズ エージェント指示

## 最初に読む（どの AI・どの環境からでも、この順で）

1. **残務と次の一手**：issue #240（状況まとめ）と、その子の issue。判断待ちには「判断待ち」とおすすめが書いてある
2. **引き継ぎ**：[docs/引き継ぎ.md](docs/引き継ぎ.md)（配信の手順、数え方の決め、書き方の作法、環境の制約、音声入力の誤変換の表）
3. **ルールの正本**：[docs/進め方.md](docs/進め方.md)（優先順位、作業の流れ、完了の定義5つ）
4. 資料：[docs/reports/handoff-2026-11-20/](docs/reports/handoff-2026-11-20/README.md)

今の状態（2026-11-20）：計算仕様 v3.0。議員の欄（曝露ランキング）は画面で隠したまま。全件の当て直しはこのリポジトリの外で実施中で、結果を受け取ったら #235 の残りをここで行う。リリースまでの順番は #240 の「リリースまでの道筋」。

守る規則：
- コミットの名義は nexus_ai（nexus-ai-2045 の GitHub noreply）。push の前に `python3 scripts/preflight.py` を通す（repo-preflight をこのリポジトリの隣に clone しておく）。
- PR 本文・issue・コミットに、会話の場のリンク、セッションの行、`Co-Authored-By` 行を入れない。PR の題名と見出しは日本語。
- 本番配信は、所有者の「リリース」の合図で1回だけ。手順は docs/引き継ぎ.md 1章。
- テストは `python3 scripts/local_verify.py` で回す（`.github/workflows/verify.yml` の `run:` をそのまま読むので、CI と順番が食い違わない）。生成物を作らずに `pytest` を全部回すと、`app/public/distribution/*.json` が無くて失敗・エラーが出る（2026-11-20 に確認）。

## 共通の指示

- ユーザー向け・運用向け文書は日本語を既定とする。
- 架空データと実在データを混在させない。
- 確認済み事実、機械計算、AI 解釈、未確認を分離する。
- 製品目的の正本は `PROJECT_SSOT.md`。国会議員個人の政策判断への責任を評価するワーストランキングを中心機能とする。
- 評価は公開された行動・政策結果への関与に限定する。人格評価、噂による加点、党籍からの個人採決の推定はしない。
- 実在データの評価方法（判定基準）は人間レビューする。1件ごとの出典・反証・個人への帰属の判断は、ファクトと実測だけを材料に2系統の AI が一致したものを採用する（`docs/adr/0007-ai-judgment-facts-and-measurements.md`）。Web公開は、法律の結果は全件・常時承認、議員は公人として実名で全員公開とする（2026-10-17 ユーザー指示、`docs/adr/0008-publish-everything-with-certainty-marks.md`）。1件ごとの承認の代わりに、出典チェック・議員ページの公開前検査・個人名義検査が赤なら取り込まない。この範囲を超える公開（私生活の情報、新しい種類の実在データ）は、現在会話で対象を提示した明示承認を要する。架空データのテスト成功を実在評価の妥当性と扱わない。
- 出典、観測時刻、対象範囲、不確実性を保持する。
- 個々のタスクで使う外部資料は `scripts/register_external_material.py` で `.local/external-materials/<task-id>/` に保存する。
- 外部資料を保存した事実と、資料内容の正しさを分離する。内容は初期状態を `unverified` とする。
- `.local/`、`.env*`、credential、個人情報を Git に追加しない。
- `main` へ直接 push しない。
- GitHub リポジトリ作成、push、プルリクエスト、公開、外部共有は現在会話での明示承認を必要とする。
- 新規 GitHub リポジトリは private を既定とする。
- 完了前に `npm test`、`npm run build`、`npm audit --audit-level=moderate` を実行する。
- 外部資料登録処理を変更した場合は `python -m unittest discover -s tests -v` も実行する。

## ルールと、それを強制する仕組み

くり返したミスは、文書ではなく検査で止める。訂正されたら、ここに行を足し、同じ変更の中で検査を足す。強制が「なし」の行は、判断が要るもの。

| ルール | 強制する仕組み | 落ちる場所 |
|---|---|---|
| コミットの名義は nexus_ai（GitHub noreply）、個人名義を出さない | repo-preflight の `local_identity_guard.py`（commit-msg・pre-commit・pre-push のフック）と preflight の workflow | 手元のコミット・push、CI |
| コミットにセッション行・共著者行を入れない | `scripts/strip_commit_trace.py`（prepare-commit-msg で自動で外す）と repo-preflight の名義検査 | 手元のコミット、CI |
| PR の題名と本文の見出しは日本語 | `scripts/check_pr_text.py`（`.github/workflows/pr-text.yml`）、dependabot は `commit-message.prefix` で日本語から始める | CI。手元は `python3 scripts/check_pr_text.py --title "…" --body-file 本文.md` |
| scripts の入口は `--help` を解釈する（渡すと本番の処理が走るのを防ぐ） | `tests/test_scripts_parse_help.py`（例外の一覧は持たない） | pytest |
| 試験の skip は一覧にあるものだけ | `tests/allowed_skips.txt` と `tests/test_run_tests_parallel_skips.py` | pytest |
| 固定定数・撤回した方式・完了の条件が文書と実装でそろう | `scripts/check_design_consistency.py --strict` | CI の verify |
| CI と同じ順で検査する | `scripts/local_verify.py`（verify.yml を読む） | 手元 |
| 本番配信は所有者の「リリース」で1回 | `vercel.json` の `git.deploymentEnabled: false`（Git からの自動配信を止めてある） | 配信されない |
| open PR は8本まで、同じ作業の PR を2本出さない | なし（同じ題名の PR が #257/#260、#259/#262 で2本ずつ出た。強制のしかたは所有者の判断待ち） | — |
| PR 本文に道具の自動フッターを残さない（進め方 3章10） | なし（直近40本中17本に残る。サーバーが付け直すかを確かめてから決める） | — |

## 個人名義を出さない（絶対）

- 持ち主の個人名義（本名、私用のメール、OS のアカウント名、端末名、それらを含むホームのパス）を、チャット・PR・Issue・コミット（名義とメッセージ）・ファイル・共有フォルダ・ログのどこにも書かない。確認のためでも書かない。
- 検査が「照合する名前が無い」などで止まっても、ユーザーに名前を書かせる案や、エージェントが値を書き込む案を出さない。照合する値は `local_identity_guard.py`（repo-preflight の `scripts/`）が実行中の環境から自動で集め、表示も保存もしない。
- 値を表示するコマンド（`whoami`、`id -F`、`echo $HOME`、`git config user.email` など）の出力をチャットやファイルへ貼らない。比べる必要があるときは一致・不一致だけを出す。
- コミットの作成者とコミッターは公開用の名義（nexus-ai-2045 の GitHub noreply）だけにする。書き込み前に `python <repo-preflight>/scripts/local_identity_guard.py --public-name nexus-ai-2045 --public-name nexus_ai config` で確かめ、push 前は同じスクリプトの `check` を使う。
- push 前検査や identity guard を緩めない・回避しない（`--no-verify`、`core.hooksPath` の付け替え、照合リストの無効化をしない）。止まったら、値を出さずに原因の箇所を直す。
