# 国内統計（内閣府SNA・CPI・宿泊旅行統計・労働力調査）の取得記録

取得日: 2026-10-16〜17。取得スクリプトは `scripts/dstat_*.py` と `scripts/dstat_fetch.sh`（同一サイト1.1秒以上あけ、User-Agent に public-interest-lens を入れた）。原本は `.local/domestic-stats/raw/` にあり Git には入れていない。

## 結果

| 項目 | 結果 |
|---|---|
| 1. 内閣府 国民経済計算 経済活動別GDP（名目・実質） | 取れた（2020/2015/2011/2005/2000基準） |
| 2. 総務省統計局 消費者物価指数 品目別 年平均 | 取れた（2025/2020/2015/2010/2005基準） |
| 3. 観光庁 宿泊旅行統計調査 全国 年 | 一部（2011〜2025年。2007〜2010年は未整理） |
| 4. 総務省統計局 労働力調査 産業別就業者数 | 取れた（産業分類の改定ごとに3本） |

## CSV と行数（見出しを除く）

| ファイル | 行数 |
|---|---|
| `data/acquired/domestic-stats/cpi_items_annual_2005base.csv` | 7476 |
| `data/acquired/domestic-stats/cpi_items_annual_2010base.csv` | 8319 |
| `data/acquired/domestic-stats/cpi_items_annual_2015base.csv` | 9100 |
| `data/acquired/domestic-stats/cpi_items_annual_2020base.csv` | 9968 |
| `data/acquired/domestic-stats/cpi_items_annual_2025base.csv` | 9800 |
| `data/acquired/domestic-stats/kanko_lodging_annual.csv` | 45 |
| `data/acquired/domestic-stats/lfs_employed_by_industry_jsic10.csv` | 663 |
| `data/acquired/domestic-stats/lfs_employed_by_industry_jsic11.csv` | 152 |
| `data/acquired/domestic-stats/lfs_employed_by_industry_jsic12-14.csv` | 504 |
| `data/acquired/domestic-stats/sna_gdp_by_industry_2000base.csv` | 1750 |
| `data/acquired/domestic-stats/sna_gdp_by_industry_2005base.csv` | 1470 |
| `data/acquired/domestic-stats/sna_gdp_by_industry_2011base.csv` | 1800 |
| `data/acquired/domestic-stats/sna_gdp_by_industry_2015base.csv` | 1872 |
| `data/acquired/domestic-stats/sna_gdp_by_industry_2020base.csv` | 2232 |

## 表の説明

### sna_gdp_by_industry_*base.csv（基準年ごとに別ファイル）
列: 基準年, 価格, 経済活動, 年, 値, 単位, 出典URL。暦年。名目は10億円。実質は連鎖方式の指数で、その基準の基準年=100（単位列に書いた）。経済活動名は原本の番号付き見出しから空白だけ除いた（例「9.情報通信業」）。小分類は同名が複数あり得るので、行順・番号で見ること。各基準の最終年は取れた最新の確報:
- 2020基準: 2024年度確報の表（1994〜2024年）。
- 2015基準: 2019年度確報（1994〜2019年）。
- 2011基準: 2018年度確報（1994〜2018年）。
- 2005基準: 2014年度確報（1994〜2014年）。
- 2000基準: 2009年度確報（1980〜2009年）。
基準が違う系列はつないでいない。2015基準以前の分類は新しい基準と経済活動の区切りが異なる。

### cpi_items_annual_*base.csv（基準年ごとに別ファイル）
列: 基準年, 品目, 年, 値, 出典URL, 品目符号。全国・年平均の品目別価格指数（総務省統計局が e-Stat に登録した「長期時系列データ 品目別価格指数」の CSV）。基準年=100。含めたのは、類・中分類・小分類など品目符号が1000未満の行すべてと、名前に 通信・電話・電気・宿泊・インターネット・ガス代・ホテル・放送・郵便 を含む品目（全品目は容量のため入れていない）。「通信」「電気代」「宿泊料」「携帯電話通信料」は 2025/2020/2015/2010基準にある（2020基準以降の携帯電話の項目名は「通信料(携帯電話)」、2005基準には携帯電話の項目はない）。同じ名前（例「電気代」）が類と品目の両方にあるので品目符号で区別する。2005基準の品目符号は「類符号」（品目には無い）。各基準の年の範囲: 2025基準 1970〜2025、2020基準 1970〜2025、2015基準 1970〜2021、2010基準 1970〜2016、2005基準 1970〜2011。空欄は原本が空欄（その年にその品目の指数が無い）。

### kanko_lodging_annual.csv
列: 年, 指標, 値, 単位, 出典URL。観光庁「宿泊旅行統計調査」推移表の「旧1-1」「旧2-1」「旧3-1」（年計・全国）。2025年12月までの調査（従業者数による層化）の確定値で、2011〜2025年。単位は人泊。令和8年（2026年）1月分から層化基準が客室数に変わったため、2026年のデータは入れていない。2007〜2010年は年別の集計表（xls）にあるが、今回は整理していない。指標: 延べ宿泊者数、日本人延べ宿泊者数、外国人延べ宿泊者数。出典URL末尾の #旧1-1 などはシート名。

### lfs_employed_by_industry_*.csv（産業分類ごとに別ファイル）
列: 年, 産業, 値, 単位, 出典URL, 産業分類。労働力調査 長期時系列表5（年平均、全国、男女計、万人）。産業分類が改定ごとに違うため別ファイル: jsic10（第10回改定、1953〜2002年）、jsic11（第11回改定、2002〜2009年）、jsic12-14（第12・13・14回改定、2002〜2025年）。つないでいない。jsic12-14 は原本の「長期05」シートを使い、「既公表値」シートは使っていない。空欄は原本が空欄。

## 原本の一覧（URL・sha256・取得日）

| URL | sha256 | 取得日 | 保存名（.local/domestic-stats/raw/） |
|---|---|---|---|
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2024/tables/2024s2n_jp.xlsx | 560a8883941efee581b784219327daa7e03e6a7d4955f04f140f64d19f0118a7 | 2026-10-16 | sna2020_gdp_nominal_2024s2n.xlsx |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2024/tables/2024s2rn_jp.xlsx | 7eae49a39164e2381b18e0d61d9324144095baaa082ec76e26fb3e11f51170ef | 2026-10-16 | sna2020_gdp_real_2024s2rn.xlsx |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2019/tables/2019s2n_jp.xlsx | 495d34f4c991d05d841f76634ca3cd8d3f1570b7ab87c639204c344c95f880ff | 2026-10-16 | sna2015_gdp_nominal_2019s2n.xlsx |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2019/tables/2019s2rn_jp.xlsx | c46022aeff09223441eb8f57683f7b8e74750316d0bb00e9d5f3460a0bff91f8 | 2026-10-16 | sna2015_gdp_real_2019s2rn.xlsx |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h30/tables/30s2n_jp.xlsx | 6c0f9af39ac66470634064958cd717c00f3fac07c6bb96811a72d7feb06f81e5 | 2026-10-16 | sna2011_gdp_nominal_30s2n.xlsx |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h30/tables/30s2rn_jp.xlsx | a239ab83dff2b572dcd6774bfcb2fd8e0b1e5f04c4c47ed712347d021b47623b | 2026-10-16 | sna2011_gdp_real_30s2rn.xlsx |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h26/tables/26s2n_jp.xls | 646eba15b2fe1234ac67e10b73096481049ecb4f857acb071e8e41a513ce583d | 2026-10-16 | sna2005_gdp_nominal_26s2n.xls |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h26/tables/26s2rn_jp.xls | ef41ffe2ff394e89d63348e5f0916082b1bb5c6c811c32d07ddd23d7f3985eac | 2026-10-16 | sna2005_gdp_real_26s2rn.xls |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h21/tables/21s2n_jp.xls | e329286336997c1c110923d619e069a9a3eaf6919e3fd949c8fb39991b5b5ae5 | 2026-10-16 | sna2000_gdp_nominal_21s2n.xls |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h21/tables/21s2rn_jp.xls | 010c8e96479d5c24e3f6fbad9f1fb87834375f7a4f58d40d88a43e69e7e96509 | 2026-10-16 | sna2000_gdp_real_21s2rn.xls |
| https://www.stat.go.jp/data/cpi/2020/csv/zmi2020aa.csv | 960d55d484dd0c98ff107bd766e521cba600d75d0fa0424cfe54eea075e76b77 | 2026-10-16 | cpi2020_zmi2020aa.csv |
| https://www.stat.go.jp/data/cpi/2025/csv/zmi2025aa.csv | d22aa87acdd7e284bb6d4501de9cf484fac77d145db67388d20c9b441d7f6a7b | 2026-10-16 | cpi2025_zmi2025aa.csv |
| https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040482831&fileKind=1 | cfa494f77d7b56469672c11ce97d966dbd54f59f930040ac3cb27729334e6c10 | 2026-10-16 | cpi2025_annual_items_000040482831.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000032103938 | 33fbf128935f2525d8ce3bf7333c8943fa45938b9338a2ad306d617994ae8bec | 2026-10-16 | cpi2020_annual_items_000032103938.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000031431772 | 3bf13084b168e7aa41f5b49d318198fcc166c3c4e7ae23fcf9b4cd24d5502edd | 2026-10-16 | cpi2015_annual_items_000031431772.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000011288549 | da9ce43a1f5467bb3255b4c522da03def2935e9da988b53cd927214f27c4db48 | 2026-10-16 | cpi2010_annual_items_000011288549.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000011288550 | eba41ccc3c594f8d9348d9a6406c0316dbfbd285a6bbef1d04d935e153289027 | 2026-10-16 | cpi2010_annual_items_000011288550.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000011288551 | de2b4fd12d39ffb73cc19fc09a124bdc8d7f37f3cb282e73cd4b81020e4430fb | 2026-10-16 | cpi2010_annual_items_000011288551.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000011288552 | cd3596ec941448ec140c297ab6af00c4dee32bd747e206061f8337eea035c5b8 | 2026-10-16 | cpi2010_annual_items_000011288552.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000011288553 | 0c313b5cf41fb34ca43122257208fe98b993f690bfa0a5b32426130775242abe | 2026-10-16 | cpi2010_annual_items_000011288553.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000002103090 | efc0f550bf2ab3cbf4fbcb46d25c6b35a0b4ad3e155caf6c31deebcfe0ad44e0 | 2026-10-16 | cpi2005_annual_items_000002103090.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000002103091 | 924df60411af597dc1d099c15336edafecbf17d80450909582826f4a6b3d8afb | 2026-10-16 | cpi2005_annual_items_000002103091.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000002103092 | 105b460b4948906380b2a947adf9b086466552934694312adb54b4064429fc95 | 2026-10-16 | cpi2005_annual_items_000002103092.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000002103093 | 961ae80eb4e6f2419d74e650289e12465eb12aef6b0f8019df394eafeca20558 | 2026-10-16 | cpi2005_annual_items_000002103093.csv |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=1&statInfId=000002103094 | 536cf66260da27e445f0829ca1bf65137575431822504242b207684577760703 | 2026-10-16 | cpi2005_annual_items_000002103094.csv |
| https://www.mlit.go.jp/kankocho/content/002026697.xlsx | 53d60b6e5c7adea0d85ea8a4219e47d55f4ed90c6eac0936a2b1ef4ea3eede05 | 2026-10-16 | kanko_suiihyo_002026697.xlsx |
| https://www.mlit.go.jp/kankocho/content/002015008.xlsx | 6c90c808215a1adfafe1a65683a382aa482fbd05c6d386402a2130ea8e1fe566 | 2026-10-16 | kanko_2025_annual_002015008.xlsx |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000001082692 | 8d598c30277027a8f6b0113345f7685f4aa36e15b02d40020b701741ed0f3040 | 2026-10-16 | lfs_5-1_000001082692.xlsx |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000004703169 | 079855eedab089ae8ddf9764e3a998790423b1cd27dac63862ad0c99c75054b8 | 2026-10-16 | lfs_5-2_000004703169.xls |
| https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000001082693 | daf85aaf12adbc9b232bd8677e6a1c28409688a04f6701db8e49703f9cfe67ee | 2026-10-16 | lfs_5-3_000001082693.xls |

### たどった案内ページ
| URL | sha256 | 取得日 | 保存名 |
|---|---|---|---|
| https://www.esri.cao.go.jp/jp/sna/menu.html | 9418a10fa3402ebecc40da856e175855954d3014c77076f90b654866cffebbca | 2026-10-16 | sna_menu.html |
| https://www.stat.go.jp/data/cpi/ | a611fb16be9c1bf4d9faae3865d36146dca2afbd2ef7ccc34f8f9f17ad70daa1 | 2026-10-16 | cpi_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2024/2024_kaku_top.html | b750318661744a7f5d28e3ea9d7bd1b483769dbabe4bd7c3faa599c31788a46f | 2026-10-16 | kaku2024_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2024/2024_kaku_top.html | b750318661744a7f5d28e3ea9d7bd1b483769dbabe4bd7c3faa599c31788a46f | 2026-10-16 | k2.html |
| https://www.esri.cao.go.jp/jp/sna/data/data.html | a2d8fcbb7b6fd711b3cfd58d1bc121a09d85c39cbd30679f4f2b274a8682ec12 | 2026-10-16 | sna_data.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/2019/2019_kaku_top.html | f43d21bff5a199be31192575cf4c162048b95255028dfd43e9b2931fb7e7955c | 2026-10-16 | kaku2019_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h30/h30_kaku_top.html | 84bcc709193391a8e8f8f0aa5a11b52a810908b98bc60b73216c2676221053a9 | 2026-10-16 | kakuh30_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h29/h29_kaku_top.html | 4c9582fdbbcbcbf6918735c371915d7bbe063a22a0b570afcc7258df00d51481 | 2026-10-16 | kakuh29_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h28/h28_kaku_top.html | 276708e43c51fe5ff40613c2f4f27ae733b097b5c27923d2738aa45abb0ebe83 | 2026-10-16 | kakuh28_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h27/h27_kaku_top.html | fbf15c6fd316fac330cdf3df4294b9efc6a1ce8bce812c0faef76f49ff37228d | 2026-10-16 | kakuh27_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h26/h26_kaku_top.html | b427ab9eb9390b9fcf8d9ad42da53defa0b632c251125589086ef2608d640cae | 2026-10-16 | kakuh26_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h25/h25_kaku_top.html | e2d777324a3d5f4ed8638275a456a727cd006eff00c9c1313c42e3c701c7722f | 2026-10-16 | kakuh25_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h24/h24_kaku_top.html | cdac60b3fb9381f7ca1882ee016ef792aada87b328917e262ac62a9c4379680f | 2026-10-16 | kakuh24_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h23/h23_kaku_top.html | 9b3f13a1d620da2e22ce98c40ababd2e8becd48def8d62608ba86cec94ec97fa | 2026-10-16 | kakuh23_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h22/h22_kaku_top.html | 22e6b0bbcd2d7906910581d4eb8458487f24a81a1b9e6b734898434d235f7943 | 2026-10-16 | kakuh22_top.html |
| https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/h21/h21_kaku_top.html | e41b390df4604c5fd86dd4c5d04e996559d1ccb0c286e7bf0c3c2a90085ca3cb | 2026-10-16 | kakuh21_top.html |
| https://www.stat.go.jp/data/cpi/1.html | 22e8e93e081a582702e26e2ac726d779de5e4351b0ed06e1a422bc93aa3e40c5 | 2026-10-16 | cpi_1.html |
| https://www.e-stat.go.jp/stat-search/files?tstat=000001243876 | d6193730a1a0dd34fedef3fe233360c4b4cd9bda2cfa6d8999e0ccbf2eab76c8 | 2026-10-16 | estat_cpi2025_longtime.html |
| https://www.e-stat.go.jp/stat-search/files?tstat=000001243876&toukei=00200573&cycle=0&tclass1=000001243879&layout=datalist&page=1&tclass2val=0 | c968d92144d04c86d02891e31d54b7fcfbf6c686b511418ab8ea9fec60e48a5e | 2026-10-16 | estat_cpi2025_cls879.html |
| https://www.e-stat.go.jp/stat-search/files?tstat=000001243876&toukei=00200573&cycle=0&tclass1=000001243880&tclass2=000001243881&tclass3=000001243883&tclass4=000001243890&layout=datalist&page=1&tclass5val=0 | 1c77de35ef89640c394781d854699143b6231d4249e54ad8b2229580fc0db0c9 | 2026-10-16 | e25_a890.html |
| https://www.e-stat.go.jp/stat-search/files?tstat=000001243876&toukei=00200573&cycle=0&tclass1=000001243880&tclass2=000001243881&tclass3=000001243884&tclass4=000001243887&layout=datalist&page=1&tclass5val=0 | 07b2b304f0954cf6330a7aa07f9fb7b15c315f4cd68417beb31e6a491fd0c2df | 2026-10-16 | e25_a887.html |
| https://www.mlit.go.jp/kankocho/ | 005bcaab4ce12173ef6986304aa11a088ec91e927f56f2f4f7633e3a52cf0491 | 2026-10-16 | kanko_top.html |
| https://www.mlit.go.jp/kankocho/tokei_hakusyo.html | b9a7d8f22d333f7e7146047f7479b5b595ed3007099aae214933159f514449cc | 2026-10-16 | kanko_tokei.html |
| https://www.mlit.go.jp/kankocho/tokei_hakusyo/shukuhakutokei.html | 4dcd58b7b043bb68307f541f2ce7c6ee4fc7985a74eb4dad890fe4199858d64d | 2026-10-16 | kanko_shuku2.html |
| https://www.stat.go.jp/data/roudou/longtime/03roudou.html | e22ce50c86231affecb3af3663edbc235ca6301b899d7a10c8eec50220820a24 | 2026-10-16 | lfs_longtime.html |
| https://www.stat.go.jp/data/roudou/index.html | ca8067d1ba668afac7c706d2a2082c9b5fd9dff21ad3ccb0c442abf67edfe6f7 | 2026-10-16 | lfs_top.html |
| https://www.stat.go.jp/data/roudou/2.html | d69140f0c868ab0614bba7d577dc0f60fd8252574732d36f080f2ab78a2d1ba0 | 2026-10-16 | lfs_2.html |
| https://www.e-stat.go.jp/stat-search/files?tclass=000001226526&cycle=0 | 9917f4368954831308cb0217ddf5e84822142eb3e28542d1360e214cbf0b5105 | 2026-10-16 | lfs_estat_lt.html |

## 取れなかったもの・注意

- 存在しないURLを試した記録（HTTP 404）が manifest.csv にある。内閣府の古い確報ページ名を探した試行（20件）で、値には使っていない。
- 内閣府SNAの2020基準は2024年度確報までの表を使った。四半期速報や、過去の基準の「遡及」系列（簡易遡及など）は取っていない。
- CPIの2005基準・2010基準の年範囲は上のとおりで、それ以降は新しい基準に移っている。
- 観光庁の2007〜2010年、および2026年（層化基準変更後）は未取得。
- e-Stat のAPIキーは使っていない。ファイルは公開ダウンロードのみ。
