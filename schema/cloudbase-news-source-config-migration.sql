CREATE TABLE IF NOT EXISTS ht_news_source_config_versions (
  id CHAR(36) PRIMARY KEY,
  _openid VARCHAR(64) DEFAULT '' NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'archived',
  config_json LONGTEXT NOT NULL,
  config_sha256 CHAR(64) NOT NULL,
  change_note VARCHAR(500) NOT NULL DEFAULT '',
  published_by VARCHAR(80) NOT NULL DEFAULT 'administrator',
  published_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ht_news_source_config_status_time (status, published_at)
);
