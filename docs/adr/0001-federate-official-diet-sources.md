# ADR-0001: 国会データを公式source federationとして取得する

## 状況

国会関連情報は、国会会議録検索システム、衆議院、参議院、e-Gov法令検索、日本法令索引、NDLサーチに分散している。単一sourceだけでは、発言、議案経過、投票、質問答弁、法令改廃、図書館資料を結合できない。

## 選択肢

1. 民間の集約APIだけを使う。
2. 衆参サイトを一括scrapeして独自DBを作る。
3. 公式APIを優先し、各院固有ページを補完sourceとして連携する。

## 決定

選択肢3を採用する。

- 会議録と法令は公式APIをprimary sourceとする。
- 議案、投票、質問答弁、委員会資料は衆参の公式公開面で補完する。
- 図書館資料はNDLサーチAPI、法令沿革は日本法令索引へ接続する。
- 全entityにsource URL、取得時刻、event time、content hash、coverage状態を持たせる。
- raw response、正規化データ、公開表示を分離する。

## 理由

- 公式sourceへの追跡可能性を保てる。
- 単一サイトの掲載開始時期や欠損に依存しない。
- APIがある面でHTML構造変更の影響を減らせる。
- source間の矛盾を上書きせず、並べて検証できる。

## 影響

- source別connectorとcoverage監査が必要になる。
- 同一人物・議案・法令を結ぶidentity reconciliationが必要になる。
- 全件同期には時間、storage、rate limit管理が必要になる。
- 「公式sourceに掲載された」ことと、内容そのものが正しいことを区別できる。

## 再検討条件

- 国会全体を対象とする公式統合APIが提供された場合。
- 現行sourceの利用条件が自動取得を認めなくなった場合。
- source間identity reconciliationの誤結合率が許容値を超えた場合。
