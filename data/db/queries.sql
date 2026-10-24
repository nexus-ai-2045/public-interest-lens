-- よく使う問い合わせ。scripts/query_db.py が「-- name:」ごとに読み、:引数 を埋めて実行する。
-- 例：python3 scripts/query_db.py 議員の内訳 person=麻生太郎

-- name: 議員の内訳
-- この人に配った額を、法律・役割ごとに（確かな額。向きは side：loss＝国賊側、benefit＝国士側）
SELECT a.law_id, l.title, l.side, l.certainty, a.role, round(a.fraction, 6) AS fraction, a.median AS 中央値の円, a.low AS 下限の円, a.high AS 上限の円, o.n_laws AS 同じ観測の本数
FROM allocations a JOIN laws l USING (law_id) LEFT JOIN observations o ON o.observation_id = l.observation_id
WHERE a.recipient_kind = 'person' AND a.recipient_id = :person
ORDER BY a.median DESC;

-- name: 議員の行動
-- この人の一次資料つきの行動（算入しなかったものも理由つき）
SELECT i.law_id, l.title, i.house, i.action, i.position, i.title_then, i.acted_on, s.url, i.counted, i.excluded_reason
FROM involvements i JOIN laws l USING (law_id) LEFT JOIN sources s USING (source_id)
WHERE i.person_id = :person ORDER BY i.acted_on;

-- name: 法律の配り先
-- 1本の法律の額を、だれにどれだけ配ったか（人・衆議院の賛成会派・名前不明の賛成票）
SELECT a.recipient_kind, a.recipient_id, a.role, round(a.fraction, 6) AS fraction, a.median AS 中央値の円
FROM allocations a WHERE a.law_id = :law ORDER BY a.median DESC;

-- name: 法律
-- 1本の法律の額・確かさ・印・一次資料
SELECT l.*, (SELECT group_concat(note, ' ／ ') FROM law_notes n WHERE n.law_id = l.law_id) AS 印,
       (SELECT group_concat(s.url, ' ') FROM law_sources ls JOIN sources s USING (source_id) WHERE ls.law_id = l.law_id) AS 一次資料
FROM laws l WHERE l.law_id = :law;

-- name: 年ごとの額
-- 施行年ごとの本数と、観測を本数で割った額の合計（確かさ別）
SELECT CAST(substr(l.enforced_on, 1, 4) AS INTEGER) AS 施行年, l.certainty AS 確かさ, l.side,
       COUNT(*) AS 本数, SUM(l.median / o.n_laws) AS 観測を割った額の合計
FROM laws l JOIN observations o ON o.observation_id = l.observation_id
WHERE l.outcome = '額' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- name: 議員の順位
-- 確かな額の順位（純額の小さい順＝国賊側が上）
SELECT s.rank, p.name, s.net_median AS 純額, s.loss_median AS 失わせた額, s.credit_median AS 生んだ額, s.chair_veto_rank AS 委員長も拒否権者のときの順位
FROM member_scores s JOIN people p USING (person_id) WHERE s.ledger = '確か' ORDER BY s.rank LIMIT :limit;

-- name: 会派の賛否
-- 衆議院の会派ごとに、賛成・反対した法律の本数と、確かな額（高・中・低）の法律の分の合計（配分ではない）
SELECT s.party_id, s.stance, COUNT(*) AS 本数,
       SUM(CASE WHEN l.side = 'loss' AND l.certainty IN ('高','中','低') THEN l.median / o.n_laws END) AS 国賊側の額,
       SUM(CASE WHEN l.side = 'benefit' AND l.certainty IN ('高','中','低') THEN l.median / o.n_laws END) AS 国士側の額
FROM law_party_stances s JOIN laws l USING (law_id) LEFT JOIN observations o ON o.observation_id = l.observation_id
GROUP BY 1, 2 ORDER BY 3 DESC;

-- name: 系列
-- 指標の系列を名前で探す（例：label=消費者物価指数 総合）
SELECT series_id, country, label, breakdown, price_basis, unit, base_year, period_kind,
       (SELECT min(period) || '〜' || max(period) FROM points p WHERE p.series_id = s.series_id) AS 期間, note AS 注記
FROM series s WHERE s.label LIKE '%' || :label || '%' ORDER BY series_id LIMIT 50;

-- name: 系列の値
SELECT p.period, p.value, coalesce(p.source_url, s.source_url) AS 出典 FROM points p JOIN series s USING (series_id) WHERE series_id = :series ORDER BY p.period;

-- name: 産業の付加価値
-- OECD 表6 の、国・産業の名目と実質（連鎖）と暗黙のデフレーター（名目÷実質×100）
SELECT v.period, v.value AS 名目, r.value AS 実質_連鎖, round(100.0 * v.value / r.value, 3) AS デフレーター
FROM points v JOIN points r ON r.period = v.period AND r.series_id = 'oecd-t6:' || :country || ':' || :industry || ':LR'
WHERE v.series_id = 'oecd-t6:' || :country || ':' || :industry || ':V' ORDER BY v.period;

-- name: 団体の行動
-- 止めた側の記録を、団体ごとに件数で
SELECT org_id, dataset, COUNT(*) AS 件数, group_concat(DISTINCT stance) AS 立場 FROM org_actions GROUP BY 1, 2 ORDER BY 3 DESC LIMIT :limit;

-- name: 決定
-- 決定（法律・国策・判決…）を種類と期間で
SELECT decision_id, country, kind, title, decided_on, effective_on, decided_by FROM decisions
WHERE kind = :kind AND decided_on BETWEEN :from AND :to ORDER BY decided_on;

-- name: 主要経費別
-- 一般会計の主要経費別の額（兆円）を年度・段階（当初・補正・決算）ごとに。内訳・合計を除くので、足すと「合計」になる
SELECT fiscal_year AS 年度, stage AS 段階, item AS 経費, ROUND(amount / 1e12, 3) AS 兆円 FROM fiscal_flows
WHERE account = '一般会計' AND category = '主要経費別'
  AND fiscal_year BETWEEN CAST(substr(:from, 1, 4) AS INTEGER) AND CAST(substr(:to, 1, 4) AS INTEGER)
ORDER BY fiscal_year, stage, amount DESC;

-- name: 財政の合計
-- 一般会計の歳出の合計（当初・補正・決算）と、歳入の公債金・租税、地方の純計（兆円）を年度ごとに並べる
SELECT fiscal_year AS 年度,
  ROUND(SUM(CASE WHEN account = '一般会計' AND stage = '当初' AND category = '主要経費別（合計）' AND item = '合計' THEN amount END) / 1e12, 2) AS 当初,
  ROUND(SUM(CASE WHEN account = '一般会計' AND stage = '補正' AND category = '主要経費別（合計）' AND item = '合計' THEN amount END) / 1e12, 2) AS 補正,
  ROUND(SUM(CASE WHEN account = '一般会計' AND stage = '決算' AND category = '主要経費別（合計）' AND item = '合計' THEN amount END) / 1e12, 2) AS 決算,
  ROUND(SUM(CASE WHEN item = '公債金' THEN amount END) / 1e12, 2) AS 公債金,
  ROUND(SUM(CASE WHEN item = '租税及印紙収入' THEN amount END) / 1e12, 2) AS 租税,
  ROUND(SUM(CASE WHEN account = '地方（純計）' AND item = '歳入合計' THEN amount END) / 1e12, 2) AS 地方の歳入
FROM fiscal_flows GROUP BY fiscal_year ORDER BY fiscal_year;

-- name: 特別会計の主要経費別
-- 特別会計の主要経費別（兆円、平成20年度〜）。足し上げが表の合計と合わない年度は入っていない。
-- 特別会計の額は純計ではない（一般会計からの繰入が重なる）ので、一般会計と足さない。補正は補正による増減額
SELECT fiscal_year AS 年度, stage AS 段階, item AS 経費, ROUND(amount / 1e12, 3) AS 兆円 FROM fiscal_flows
WHERE account = '特別会計' AND category = '主要経費別'
  AND fiscal_year BETWEEN CAST(substr(:from, 1, 4) AS INTEGER) AND CAST(substr(:to, 1, 4) AS INTEGER)
ORDER BY fiscal_year, stage, amount DESC;

-- name: 国債
-- 国債の発行額（種類別）・普通国債残高・国債費（兆円）と比率（%）。stage：決算＝実績、補正＝補正後の見込み、当初＝当初の見込み。
-- 国債費は当初予算の額（一般会計の主要経費「国債費」と重なる）。区分「国債発行額の内訳」は特例債のうち数で、足すと二重
SELECT fiscal_year AS 年度, stage AS 実績の別, category AS 区分, item AS 項目,
  CASE WHEN unit = '%' THEN amount ELSE ROUND(amount / 1e12, 3) END AS 値, CASE WHEN unit = '%' THEN '%' ELSE '兆円' END AS 単位
FROM fiscal_flows WHERE account = '国債（一般会計・特別会計）'
  AND fiscal_year BETWEEN CAST(substr(:from, 1, 4) AS INTEGER) AND CAST(substr(:to, 1, 4) AS INTEGER)
ORDER BY fiscal_year, category, item;

-- name: 地方の歳入
-- 地方財政（普通会計・純計）の歳入決算額（兆円）。地方交付税・国庫支出金・地方債など、2009年度〜。
-- 2017年度以前の「国庫支出金」は推移の表の「国庫支出金（交通安全対策特別交付金等を含む）」（約500億円多い）
SELECT fiscal_year AS 年度, item AS 項目, ROUND(amount / 1e12, 2) AS 兆円 FROM fiscal_flows
WHERE account = '地方（純計）' ORDER BY fiscal_year, item;

-- name: 国策の数値目標
-- 骨太の方針・デジタル重点計画の数値目標（AI の読み手2系統が一致し、原文と目標値が本文にあるもの）と達成状況。
-- 達成状況は定義の合う系列と結べたものだけ（scripts/fetch_target_series.py）。結ばない目標は理由を「測り方・理由」に
SELECT d.decided_on AS 決定日, d.title AS 決定, t.indicator AS 指標, t.target_value AS 目標値, t.unit AS 単位, t.target_year AS 目標年, t.target_year_kind AS 年の別,
       t.achievement AS 判定, t.achieved_value AS 達成の値, t.achieved_year AS 達成の年, t.series_id AS 系列, t.achievement_note AS 測り方・理由, t.quote AS 原文
FROM decision_targets t JOIN decisions d USING (decision_id) ORDER BY d.decided_on, t.target_year;

-- name: 取得元
SELECT status, category, name, host, note FROM source_registry ORDER BY status, category;

-- name: 仕様の版
SELECT * FROM method_versions;
