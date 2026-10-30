# treaty-census：条約と承認案件

国会が審議した条約と承認案件（承認を求めるの件）の一覧と審議経過。第142回国会（1998年）以降。

- 出典：衆議院「議案情報」の各回次の一覧（`kaiji{回次}.htm`）と議案ごとの経過ページ。
- 取得：`python3 scripts/fetch_treaty_census.py --out .local/treaty-census --csv data/acquired/treaty-census/treaties.csv`（約15分。原本は `.local/` に残り Git に入れない。取り直しは `--parse-only` で CSV だけ作り直せる）。
- 種別：`条約`（締結の承認）／`承認`（法律の規定に基づく承認。NHK収支予算・出先機関の設置・外為法の措置など）。承諾（予備費）・決算・予算・決議は取らない。
- 列は法律の `bill-census-full/enacted.csv` と同じ命名。条約は修正できないので、議決結果は承認か否か。審議状況が「両院承認」以外（未了など）も残す。
- 継続審査で複数の回次に載る議案は、`(種別, 提出回次, 番号)` で1件にする。
- 結果と類型の付け方は `docs/adr/0023-treaties-and-approvals.md`。
