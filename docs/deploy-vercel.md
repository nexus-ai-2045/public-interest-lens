# Vercelへの公開手順

更新日: 2026-10-16。公開版ビルドの設定は`PR` #42でマージ済みです。`Vercel`のプロジェクトはまだ無いので、所有者が画面で`Import`します。

## 先に知っておくこと

- 公開版ビルド（`VITE_PUBLIC_SITE=true`）は、端末専用の入口を出しません。試作版の注記と訂正窓口を全画面に出します。
- 評価済みの実名は金融再生プログラム1件だけです。人物の採点はありません。
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
| `/ranking` | 開く。架空データのデモとわかる |
| `/records` | 「この機能は公開版に含まれていません」と出る |
| `/evaluation` | 「この機能は公開版に含まれていません」と出る |

端末専用の入口やファイル読込欄が出ていたら、公開版ビルドになっていません。`Root Directory`とビルドログの`VITE_PUBLIC_SITE=true`を確かめます。
