# リリース前の最終レビュー（2026-11-19 準備、2026-11-20 全件実行）

別の AI や別の環境から続きを進めるための入口。

| ファイル | 中身 |
|---|---|
| `00_レビュー資料_本体.md` | 設計 v2.1・設計決定0027 の要点、11-19 の PR、要確認点 K1〜K10、論点5つ、合否の基準（11-19 時点。K の結果は 10 番にある） |
| `01_依頼文_Opus.md` | リポを読める査読者への依頼文 |
| `02_依頼文_ChatGPT_Codex.md` | ChatGPT／Codex に貼る依頼文（単体で読める）。**未実行** |
| `10_全件実行の結果_2026-11-20.md` | `scripts/release_check.py` の全件の結果、K1〜K10 と論点5つの判定、残りの一覧 |
| `11_再査読_Opus_2026-11-20.md` | main 25d47d8 の Opus 再査読。止める指摘0。直してから出す N1〜N4 は #254、後でよい N5〜N8 は #255 |

## 続きのやり方
1. `python3 scripts/install_hooks.py`、`git fetch --unshallow origin`（クラウドの浅い clone のとき）。
2. `python3 scripts/release_check.py`（配信はしない。約10分）。結果は `.local/release-check/`。
3. 残りは `10_全件実行の結果_2026-11-20.md` の5章。ChatGPT／Codex の査読は `02_依頼文_ChatGPT_Codex.md` を貼る。
4. 本番配信はねくの「リリース」の合図で1回（`docs/operations.md`）。
