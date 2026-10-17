# 技術を止めた側の一次資料データ（暫定）

新しい技術・サービスを止めた側（所管省庁・審議会の委員の所属・業界団体・天下り・効果の出ない予算・自治体の条例）を、一次資料の URL つきで集めたもの。スレッド「新技術を止めた法律の特定」と「議員の実名ランキング」の材料にする。

- 全行が **webfetch要約・暫定**。クラウドから官公庁へ直接届かないため、WebFetch の要約経由で読んだ。原本との照合（Mac で取得した原本の readback）が済むまで、評価や公開の根拠にしない。
- 個人の氏名は入れない。審議会の発言者名は列ごと落とし、要旨に残った同じ名前も「（氏名）」に伏せた。議員への献金先など実名を含むデータは private 側だけに置く。
- 作り方: `python3 scripts/build_blocking_actors.py --src <共有フォルダ>/blocking-actors`（URL のない行は捨てる）。

| ファイル | 行数 |
|---|---|
| `1_regulatory-requests/council-followup.csv` | 34 |
| `1_regulatory-requests/hotline-h26-h27.csv` | 247 |
| `1_regulatory-requests/hotline-h29-later.csv` | 131 |
| `1_regulatory-requests/hotline.csv` | 79 |
| `1_regulatory-requests/wg-hearings.csv` | 168 |
| `2_shingikai/data-semicon-mobility.csv` | 83 |
| `2_shingikai/finance-telecom-ai.csv` | 96 |
| `2_shingikai/medical.csv` | 55 |
| `2_shingikai/transport-tourism.csv` | 87 |
| `4_amakudari/reemployment.csv` | 125 |
| `5_budget-review/review-findings.csv` | 58 |
| `6_local-ordinances/ordinances.csv` | 64 |
| 合計 | 1227 |

## 系統
1. `1_regulatory-requests`: 規制改革ホットラインの所管省庁回答（対応不可・現行制度下で対応可能）、規制改革会議の実施計画フォローアップ、WG の省庁ヒアリング。
2. `2_shingikai`: 審議会・検討会で反対・慎重を述べた側の所属と区分（業界団体・学者・官僚OB・省庁）。
3. 政治資金（業界の政治団体の寄附先）は議員の実名を含むため、このフォルダには置かない。
4. `4_amakudari`: 内閣人事局の再就職状況（府省→再就職先、氏名なし）。
5. `5_budget-review`: 行政事業レビューで廃止・抜本的改善とされた事業。
6. `6_local-ordinances`: 民泊の上乗せ条例など自治体単位の規制。

## まだ足りないもの
- ホットライン平成27年度の農水・経産・国交・環境の回答と平成30年度以降、WG のスタートアップ・デジタル系の回（WebFetch の回数制限で未取得）。
- 行政事業レビューの予算額・執行額（RS システムの CSV が要る）。
- 天下りの令和4年度以降、政治資金の報告書本体（画像 PDF）。
