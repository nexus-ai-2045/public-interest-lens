# oecd-stan：原因の軸（cause-axis）の固定入力

OECD の SDMX API（sdmx.oecd.org）から 2026-10-23 に取った原本 CSV を、`scripts/prepare_oecd_stan.py` で必要な分だけに絞った表です（原本は大きいので Git に入れません。設計決定0022：固定入力は版を固定し、取り直すのは単独の PR）。

| ファイル | 中身 | 原本のデータフロー |
|---|---|---|
| `stan_va.csv` | 付加価値 B1G（V=名目、L=連鎖実質）。産業は _T・J・J58T60・J61・J62_63・C26・M72。値は百万自国通貨 | `OECD.STI.PIE,DSD_STAN@DF_STAN_2025` |
| `employment.csv` | 就業者（TOT_EMP、千人） | `OECD.STI.STP,DSD_MSTI@DF_MSTI` |
| `gdp2000.csv` | 2000年の GDP（購買力平価、百万米ドル）。追い上げの国を外す基準 | 同上 |
| `factors2020.csv` | 成長会計の入力（B1G、就業者 EMP、実質の純資本ストック N11NA、雇用者報酬 D1）。日本は2019年まで | `OECD.STI.PIE,DSD_STAN@DF_STAN`（2020年版） |

- 就業者 EMP は原本に単位が混ざっている（PS・PS_FTE・H・JB）ため、国ごと・産業ごとに PS（無ければ JB）に固定しています。単位が混ざると 2000年と2019年の比が意味を失います。
- 欠けた年は書きません（0で埋めない・補間しない）。
- 使う計算：`scripts/build_cause_axis.py`、説明：`docs/原因の軸.md`。
