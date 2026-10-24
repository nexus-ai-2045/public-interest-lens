# 成立法の全件一覧と海外統計（取得報告、2026-10-17）

`scripts/fetch_shugiin_bill_census.py` と `scripts/fetch_intl_stats.py` で取得した結果です。原本（HTML・CSV）は Git に入れず、URL・sha256・HTTP の結果を各 `manifest.csv` に残しています。

## 1. 成立法の全件一覧（`data/acquired/bill-census-full/`）

- 出典：衆議院「議案情報」の回次ごとの一覧（第142〜222回）と、成立分の経過ページ。
- `listing.csv`：一覧の全行 8,953 行（継続審査で同じ議案が複数の回次に載るため、重複を含みます）。
- `enacted.csv`：成立した法律 3,415 本（種別・提出回次・番号で重複を除いた数）。閣法 2,720、衆法 606、参法 89。
- 法律番号が取れたもの 3,414 本、公布日が取れたもの 3,414 本。
- 衆議院の会派別賛否が載っているもの 1,128 本（経過ページに記載がある回次だけ）。
- 第141回以前は議案情報に一覧がありません（404）。成立法の一覧は衆議院「制定法律」から別に取りました（第77〜141回、`data/acquired/bill-census-old/`、`docs/reports/cloud-webfetch-fetch-2026-10-17.md`）。
- 「新規か改正か」は題名が「〜の一部を改正する法律案」で終わるかどうかだけで機械的に付けています。

## 2. 海外統計（`data/acquired/intl-stats/`）

- `intl-stats.csv`：18,797 行、13 か国（AUS・CAN・DEU・ESP・FRA・GBR・ITA・JPN・KOR・NLD・NOR・SWE・USA）、38 指標、1960〜2025 年。
- 出典：OECD 物価統計（DF_PRICES_ALL、品目別 CPI）と世界銀行 WDI。各行に出典 URL があります。
- 欠けた年は空欄のまま（0 で埋めていません）。定義の違う系列はつないでいません。

指標ごとの行数:

| 指標 | 行数 |
|---|---|
| CPI:CP01 | 690 |
| CPI:CP02 | 455 |
| CPI:CP03 | 416 |
| CPI:CP04 | 455 |
| CPI:CP041 | 542 |
| CPI:CP041T043 | 412 |
| CPI:CP041T043X042 | 395 |
| CPI:CP042 | 308 |
| CPI:CP043 | 391 |
| CPI:CP044 | 382 |
| CPI:CP045 | 485 |
| CPI:CP045_0722 | 683 |
| CPI:CP05 | 416 |
| CPI:CP06 | 438 |
| CPI:CP07 | 401 |
| CPI:CP0722 | 458 |
| CPI:CP08 | 455 |
| CPI:CP09 | 416 |
| CPI:CP10 | 401 |
| CPI:CP11 | 415 |
| CPI:CP12 | 401 |
| CPI:GD | 371 |
| CPI:SERV | 397 |
| CPI:SERVXCP041_042_0432 | 225 |
| CPI:SERVXCP041_0432 | 182 |
| CPI:_T | 722 |
| CPI:_TXCP01_NRG | 679 |
| WB:GB.XPD.RSDV.GD.ZS | 344 |
| WB:IT.NET.USER.ZS | 453 |
| WB:NV.AGR.TOTL.ZS | 547 |
| WB:NV.IND.MANF.ZS | 547 |
| WB:NV.SRV.TOTL.ZS | 547 |
| WB:NY.GDP.MKTP.CD | 858 |
| WB:NY.GDP.MKTP.KD | 858 |
| WB:NY.GDP.PCAP.KD | 858 |
| WB:NY.GDP.PCAP.PP.KD | 468 |
| WB:SL.TLF.TOTL.IN | 468 |
| WB:SP.POP.TOTL | 858 |
