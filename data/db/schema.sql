-- 国賊ランキングのデータベース（kokuzoku-db/v1）。設計は docs/データベース.md、計算の版は設計決定0013。
-- scripts/build_database.py がリポジトリの JSON/CSV から毎朝作り直す。手で書き足さない（元の JSON/CSV を直す）。
-- 額の単位はすべて円（整数）。幅は low（第1四分位）・median・high（第3四分位）。
PRAGMA foreign_keys = ON;

-- ---- 仕様と出どころ ----
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE method_versions (
  component TEXT PRIMARY KEY,           -- method-spec.ts の節の id
  version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('採用', '案')),
  title TEXT NOT NULL,
  code TEXT NOT NULL
);
CREATE TABLE sources (                  -- 一次資料（URL 1つに1行）
  source_id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  host TEXT NOT NULL
);
CREATE TABLE source_registry (          -- 取得元の一覧（取得済みと予定）。data/db/source-registry.csv
  name TEXT PRIMARY KEY,
  category TEXT NOT NULL,               -- 法律・国策・海外の政策・金融政策・財政・地方財政・為替・指標
  host TEXT NOT NULL,
  url TEXT NOT NULL,
  target_table TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('取得済み', '取得できる（未取得）', '通信先の許可待ち', 'サイトが拒否（経路を探す）')),
  checked_on TEXT NOT NULL,
  note TEXT NOT NULL
);

-- ---- 主体 ----
CREATE TABLE people (
  person_id TEXT PRIMARY KEY,           -- 人物ID（scripts/person_ids.py）
  name TEXT NOT NULL
);
CREATE TABLE parties (party_id TEXT PRIMARY KEY);   -- 会派の表記そのまま
CREATE TABLE organizations (
  org_id TEXT PRIMARY KEY,              -- 名前そのまま（省庁・業界団体・審議会・日銀・自治体）
  kind TEXT NOT NULL
);

-- ---- 決定（法律・国策・金融政策・税制・予算・国債・地方財政・為替・規制。日本と海外を同じ形で） ----
CREATE TABLE decisions (
  decision_id TEXT PRIMARY KEY,         -- 法律は 閣法-196-2 のような法律ID
  country TEXT NOT NULL,                -- ISO 3166-1 alpha-3（日本は JPN）
  kind TEXT NOT NULL CHECK (kind IN ('法律', '国策', '金融政策', '税制', '予算', '国債', '地方財政', '為替', '規制', '判決', '条例')),
  title TEXT NOT NULL,
  decided_on TEXT,                      -- 決定日（法律は公布日）YYYY-MM-DD
  effective_on TEXT,                    -- 施行日・実施日
  effective_origin TEXT,                -- 台帳 / 推定（公布日）
  fiscal_year INTEGER,                  -- 年度（予算・国債・地方財政）
  decided_by TEXT,                      -- 決めた主体（内閣・国会・日銀政策委員会・所管省庁など）
  source_id INTEGER REFERENCES sources,
  summary TEXT
);
CREATE TABLE decision_targets (         -- 国策の数値目標と達成状況
  decision_id TEXT NOT NULL REFERENCES decisions,
  indicator TEXT NOT NULL,
  target_value REAL, unit TEXT, target_year INTEGER,
  target_year_kind TEXT,                -- 目標年が「年」（暦年）か「年度」か。分からなければ「不明」
  quote TEXT,                           -- 本文の原文（目標値・限定語を確かめた箇所）
  achieved_value REAL, achieved_year INTEGER,   -- 目標の単位（限定語を除く）での値と、その年。scripts/fetch_target_series.py の target-links.csv
  series_id TEXT REFERENCES series,
  achievement TEXT,                     -- 達成・未達・期限前（到達／未到達）・期限なし（到達／未到達）・値なし・結ばない
  achievement_note TEXT,                -- 測り方、または結ばない理由
  source_id INTEGER REFERENCES sources
);
CREATE TABLE decision_amounts (         -- 決定に書かれたお金（予算額・国債や ETF の買い入れ額・交付税など）
  decision_id TEXT NOT NULL REFERENCES decisions,
  item TEXT NOT NULL,                   -- 主要経費別の項目・買い入れの対象など
  amount REAL NOT NULL, unit TEXT NOT NULL,
  period TEXT,                          -- 年度・年・月
  source_id INTEGER REFERENCES sources
);
CREATE TABLE decision_votes (           -- 個人の賛否（参議院本会議・日銀の政策委員）
  decision_id TEXT NOT NULL REFERENCES decisions,
  person_id TEXT NOT NULL REFERENCES people,
  stance TEXT NOT NULL CHECK (stance IN ('賛成', '反対', '棄権')),
  source_id INTEGER REFERENCES sources
);
CREATE TABLE decision_links (           -- 日本と海外の似た決定、改正と元の決定など
  from_id TEXT NOT NULL REFERENCES decisions,
  to_id TEXT NOT NULL REFERENCES decisions,
  relation TEXT NOT NULL,               -- 似た政策・改正・前提
  lag_years REAL
);
CREATE TABLE decision_series (          -- 決定と、効果を見る指標の系列
  decision_id TEXT NOT NULL REFERENCES decisions,
  series_id TEXT NOT NULL REFERENCES series,
  role TEXT NOT NULL                    -- 結果・目標・比較
);

-- ---- 法律の計算の結果（決定のうち kind = '法律'） ----
CREATE TABLE observations (             -- 同じ観測（観測グループ・窓・額の幅）。observation-split-v1
  observation_id TEXT PRIMARY KEY,
  grp TEXT NOT NULL, window TEXT NOT NULL,
  low INTEGER NOT NULL, median INTEGER NOT NULL, high INTEGER NOT NULL,
  n_laws INTEGER NOT NULL
);
CREATE TABLE laws (
  law_id TEXT PRIMARY KEY REFERENCES decisions(decision_id),
  bill_kind TEXT NOT NULL,              -- 閣法・衆法・参法
  session INTEGER NOT NULL, number INTEGER,           -- 番号の無い議案（衆法-166- など）は NULL
  title TEXT NOT NULL,
  enacted_on TEXT,                      -- 公布日
  enforced_on TEXT,
  outcome TEXT NOT NULL,                -- 額 / 評価対象外 / 効果なし（定例） / 保留 など
  reason TEXT,                          -- 額が無いときの理由
  side TEXT CHECK (side IN ('loss', 'benefit')),
  certainty TEXT CHECK (certainty IN ('高', '中', '低', '参考')),
  stage TEXT, field TEXT, indicator TEXT,
  low INTEGER, median INTEGER, high INTEGER,  -- 損失は正、便益も正（向きは side）
  window_from INTEGER, window_to INTEGER,
  lower_bound INTEGER NOT NULL DEFAULT 0,
  benefit_status TEXT,
  observation_id TEXT REFERENCES observations
);
CREATE TABLE law_notes (law_id TEXT NOT NULL REFERENCES laws, note TEXT NOT NULL);
CREATE TABLE law_sources (law_id TEXT NOT NULL REFERENCES laws, source_id INTEGER NOT NULL REFERENCES sources);
CREATE TABLE law_countries (law_id TEXT NOT NULL REFERENCES laws, country TEXT NOT NULL);
CREATE TABLE law_party_stances (        -- 衆議院の会派別の賛否（議案の経過）
  law_id TEXT NOT NULL REFERENCES laws, party_id TEXT NOT NULL REFERENCES parties,
  house TEXT NOT NULL, stance TEXT NOT NULL CHECK (stance IN ('賛成', '反対'))
);
CREATE TABLE sangiin_votes (            -- 参議院本会議の票数
  law_id TEXT PRIMARY KEY REFERENCES laws, vote_id TEXT NOT NULL, voted_on TEXT NOT NULL,
  yes INTEGER NOT NULL, no INTEGER NOT NULL, source_id INTEGER REFERENCES sources
);
CREATE TABLE involvements (             -- 一次資料に残った行動（算入しないものも理由つきで残す）
  law_id TEXT NOT NULL, person_id TEXT NOT NULL REFERENCES people,
  house TEXT, action TEXT NOT NULL, position TEXT NOT NULL, title_then TEXT,
  acted_on TEXT, source_id INTEGER REFERENCES sources,
  counted INTEGER NOT NULL, excluded_reason TEXT
);

-- ---- 配分（責任の配り方の版ごと） ----
CREATE TABLE allocations (
  method TEXT NOT NULL,                 -- causal-shapley-v1 など
  ledger TEXT NOT NULL,                 -- 確か（高・中）/ 参考
  law_id TEXT NOT NULL REFERENCES laws,
  recipient_kind TEXT NOT NULL CHECK (recipient_kind IN ('person', 'party', 'unidentified', 'organization')),
  recipient_id TEXT NOT NULL,
  role TEXT NOT NULL,                   -- proposer / vote / chair / party / unidentified / office（閣法の大臣の役職の帳簿）/ oppose（反対票。額の配分とは別、向きは逆）
  fraction REAL NOT NULL,
  low INTEGER NOT NULL, median INTEGER NOT NULL, high INTEGER NOT NULL  -- 向きは laws.side
);
CREATE TABLE member_scores (
  method TEXT NOT NULL, ledger TEXT NOT NULL,
  person_id TEXT NOT NULL REFERENCES people,
  rank INTEGER,
  net_low INTEGER NOT NULL, net_median INTEGER NOT NULL, net_high INTEGER NOT NULL,
  loss_median INTEGER NOT NULL, credit_median INTEGER NOT NULL,
  chair_veto_rank INTEGER, flagged INTEGER,
  PRIMARY KEY (method, ledger, person_id)
);

-- ---- 団体の行動（止めた側の記録） ----
CREATE TABLE org_actions (
  org_id TEXT NOT NULL REFERENCES organizations,
  dataset TEXT NOT NULL,                -- 規制改革ホットライン・審議会・天下り・行政事業レビュー・条例
  acted_on TEXT,                        -- 日付を ISO に直したもの（直せないときは元の表記）
  acted_on_text TEXT,                   -- 元の日付の表記（「（推定）」などの印もそのまま）
  stance TEXT, subject TEXT, technology TEXT, law_text TEXT,
  source_id INTEGER REFERENCES sources, confidence TEXT
);

-- ---- 指標の系列（マクロ・ミクロ・物価・雇用・賃金・金融・エネルギー・世界シェア） ----
CREATE TABLE series (
  series_id TEXT PRIMARY KEY,           -- 取得ファイルと列から機械的に作る
  dataset TEXT NOT NULL,                -- data/acquired/ のフォルダ/ファイル
  domain TEXT NOT NULL,                 -- 付加価値・物価・雇用・賃金・金融・エネルギー・観光・交通・通信・世界・行政
  country TEXT NOT NULL,
  label TEXT NOT NULL,
  breakdown TEXT NOT NULL,              -- 産業・品目・区分
  price_basis TEXT NOT NULL,            -- 名目 / 実質（連鎖） / 指数 / 件数 など
  unit TEXT NOT NULL,
  base_year TEXT NOT NULL,
  period_kind TEXT NOT NULL CHECK (period_kind IN ('暦年', '年度', '月')),
  source_url TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''          -- 取得元の注記（推計を含む・基準の違いなど）
);
CREATE TABLE points (
  series_id TEXT NOT NULL REFERENCES series,
  period INTEGER NOT NULL,              -- 年（年度は開始年）
  value REAL NOT NULL,
  source_url TEXT,                      -- 系列の出典（series.source_url）と違う年だけ入る
  PRIMARY KEY (series_id, period)
);

-- ---- お金の流れ（財政・国債・地方。年度で結ぶ） ----
CREATE TABLE fiscal_flows (
  fiscal_year INTEGER NOT NULL,
  account TEXT NOT NULL,                -- 一般会計・特別会計・地方財政計画
  stage TEXT NOT NULL CHECK (stage IN ('当初', '補正', '決算')),
  category TEXT NOT NULL,               -- 主要経費別・国債発行額・国債残高・地方交付税・国庫支出金・地方債
  item TEXT NOT NULL,
  amount REAL NOT NULL, unit TEXT NOT NULL,
  decision_id TEXT REFERENCES decisions,
  source_id INTEGER REFERENCES sources
);

CREATE INDEX idx_alloc_person ON allocations (recipient_id);
CREATE INDEX idx_alloc_law ON allocations (law_id);
CREATE INDEX idx_inv_person ON involvements (person_id);
CREATE INDEX idx_points_series ON points (series_id);
CREATE INDEX idx_decisions_date ON decisions (decided_on);
