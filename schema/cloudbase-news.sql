CREATE TABLE IF NOT EXISTS ht_news_items (
  id VARCHAR(64) PRIMARY KEY,
  _openid VARCHAR(64) DEFAULT '' NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  source_id VARCHAR(80),
  source_name VARCHAR(160),
  source_type VARCHAR(40),
  rank_num INT NULL,
  tags_json LONGTEXT,
  matched_terms_json LONGTEXT,
  summary TEXT,
  published_at DATETIME NULL,
  first_seen_at DATETIME NOT NULL,
  latest_seen_at DATETIME NOT NULL,
  collected_at DATETIME NOT NULL,
  observations INT DEFAULT 1,
  ai_score DECIMAL(5,2) NULL,
  ai_reason TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_ht_news_latest (latest_seen_at),
  INDEX idx_ht_news_source (source_id),
  INDEX idx_ht_news_score (ai_score)
);

CREATE TABLE IF NOT EXISTS ht_news_briefs (
  id VARCHAR(64) PRIMARY KEY,
  _openid VARCHAR(64) DEFAULT '' NOT NULL,
  run_at DATETIME NOT NULL,
  window_start DATETIME NULL,
  window_end DATETIME NOT NULL,
  candidate_count INT DEFAULT 0,
  selected_count INT DEFAULT 0,
  title VARCHAR(220),
  summary TEXT,
  items_json LONGTEXT,
  prompt_version VARCHAR(40),
  model VARCHAR(120),
  raw_response MEDIUMTEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ht_news_briefs_run_at (run_at)
);

CREATE TABLE IF NOT EXISTS ht_news_sync_runs (
  id VARCHAR(64) PRIMARY KEY,
  _openid VARCHAR(64) DEFAULT '' NOT NULL,
  run_at DATETIME NOT NULL,
  fetched_count INT DEFAULT 0,
  item_count INT DEFAULT 0,
  new_count INT DEFAULT 0,
  issue_count INT DEFAULT 0,
  issues_json LONGTEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ht_news_sync_runs_run_at (run_at)
);
