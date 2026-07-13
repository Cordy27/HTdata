-- Idempotent migration for an existing news schema. It is safe to run more than once.
SET @migration_schema = DATABASE();

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_items` ADD COLUMN `external_id` VARCHAR(120) NULL AFTER `source_type`',
    'SELECT 1')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_items'
    AND COLUMN_NAME = 'external_id'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_items` ADD COLUMN `source_status` VARCHAR(40) NULL AFTER `external_id`',
    'SELECT 1')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_items'
    AND COLUMN_NAME = 'source_status'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_items` ADD INDEX `idx_ht_news_external` (`source_id`, `external_id`)',
    'SELECT 1')
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_items'
    AND INDEX_NAME = 'idx_ht_news_external'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_sync_runs` ADD COLUMN `status` VARCHAR(20) DEFAULT ''ok'' AFTER `issue_count`',
    'SELECT 1')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_sync_runs'
    AND COLUMN_NAME = 'status'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_sync_runs` ADD COLUMN `metrics_json` LONGTEXT NULL AFTER `status`',
    'SELECT 1')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_sync_runs'
    AND COLUMN_NAME = 'metrics_json'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

CREATE TABLE IF NOT EXISTS ht_news_wechat_accounts (
  id VARCHAR(80) PRIMARY KEY,
  _openid VARCHAR(64) DEFAULT '' NOT NULL,
  display_name VARCHAR(160) NOT NULL,
  fakeid VARCHAR(120) NULL,
  enabled TINYINT(1) DEFAULT 1,
  cursor_aid VARCHAR(120) NULL,
  cursor_published_at DATETIME NULL,
  last_success_at DATETIME NULL,
  last_error TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_ht_news_wechat_fakeid (fakeid),
  INDEX idx_ht_news_wechat_enabled (enabled)
);
