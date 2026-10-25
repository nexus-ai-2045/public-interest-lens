# Vercelへの公開手順

更新日: 2026-10-17。公開版ビルドの設定は`PR` #42でマージ済みです。`Vercel`のプロジェクトはまだ無いので、所有者が画面で`Import`します。

## 先に知っておくこと

- 公開版ビルド（`VITE_PUBLIC_SITE=true`）は、端末専用の入口を出しません。試作版の注記と訂正窓口を全画面に出します。
- 実名の人物の点数は、金融再生プログラム1件（`/policies`、公開はユーザー承認済み）だけに出ます。それ以外の人物の点数や配分額は出しません。
- `/ranking` は実データの法律ランキングです。`app/public/distribution/ranking.json`（`scripts/build_public_ranking.py` で生成）を読みます。額のある法律は全件を、確かさ（高・中・低・参考）つきで載せます。参考の額は確かな額と別の区画に分けます。額のない法律も、結果と理由を全件（成立した法律の全数）一覧に載せます。法律単位の結果の全件公開は 2026-10-17 のユーザー承認で、承認の記録（日付・範囲・メモ）を `ranking.json` の `approval` に残します（`--approve-all-laws --approved-at` で渡す）。議員の実名はこのファイルに入れません（別承認）。
- 架空データのデモは `/demo` に移しました。
- 訂正・異議は[訂正・異議の手順](corrections.md)で受け付けます。

## Importの手順

1. `Vercel`にログインし、`Add New` から `Project` を選びます。
2. `nexus-ai-2045/public-interest-lens` のリポジトリを選び、`Import` します。
3. `Root Directory` を `app` にします。ここが違うと設定が効きません。
4. ほかの項目は変えずに `Deploy` を押します。

## ビルド設定

設定は`app/vercel.json`にあり、画面で入れ直す必要はありません。

| 項目 | 値 |
|---|---|
| フレームワーク | `vite` |
| インストール | `npm ci` |
| ビルド | `VITE_PUBLIC_SITE=true npm run build` |
| 出力先 | `dist` |
| `rewrites` | `assets/`と`distribution/`以外を`/index.html`へ戻す（`/history`などの直リンク用） |

## デプロイ後に確かめる画面

公開URLで次を開き、表示を目で確かめます。

| パス | 確かめること |
|---|---|
| `/` | 開く。全画面に試作版の注記と訂正窓口が出る |
| `/history` | 直リンクで開く（`rewrites`が効いている） |
| `/policies` | 開く。公開事例が読める |
| `/actors` | 開く。採点がない |
| `/ranking` | 開く。件数の絞り込み、確かな額の法律、参考の額（別の区画）、額の出ていない法律の一覧（絞り込み・検索・ページ送り）が出る。議員の名前が出ていない |
| `/demo` | 「この機能は公開版に含まれていません」と出る（ナビ・フッターからはリンクしない） |
| `/records` | 「この機能は公開版に含まれていません」と出る |
| `/evaluation` | 「この機能は公開版に含まれていません」と出る |

端末専用の入口やファイル読込欄が出ていたら、公開版ビルドになっていません。`Root Directory`とビルドログの`VITE_PUBLIC_SITE=true`を確かめます。

## 法律ランキングの更新

1. 派生データ（`data/derived/*-triage-v2/`）が変わったら、`python3 -m scripts.build_public_ranking --approve-all-laws --approved-at 2026-10-17` を流し直します（承認日は承認の記録のとおり）。
2. `tests/test_public_ranking.py` が、コミットした `ranking.json` と入力の一致を確かめます。`app/src/public-bundle.test.ts` が、公開ビルドに承認外の額・人物の欄・非公開フォルダの文字列が無いことを確かめます。

## プレビューのデプロイを止める（2026-10-17）

無料枠は1日100回までのデプロイで、作業ブランチのプレビューがこの枠を使い切り、本番の反映が止まった。そのため `app/vercel.json` の `git.deploymentEnabled` で、`claude/` と `report/` のブランチのデプロイを止めている。main へのマージだけがデプロイされる。プレビューで確かめたいときは、その PR だけ一時的に外す。
