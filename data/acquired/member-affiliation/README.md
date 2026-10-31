# 議員の「当時の会派」（2026-10-30 取得）

- 出どころ：国会会議録検索システムの API（`https://kokkai.ndl.go.jp/api/speech`）の発言者所属会派（speakerGroup）。
- 取り方：関与の一覧（`data/derived/allocation-v1/involvements.csv`）に出る（人物ID, 氏名, 年）ごとに、その年のその人の発言を最大100件取り、最も多い会派を `当時の会派` にした（`scripts/fetch_affiliation_at_time.py`）。年の途中で会派が変わった人は多い側になる。発言が無い年は空。`出典URL` はそのまま再現できる検索 URL。
- 使い道：元職の「◯年の会派」の表示（参考の表 members-reference.json の `lastKnownCaucus`）。額の計算には使わない。
- 注意：会派であって党籍ではない（会派名には無所属の議員も含まれる）。
