-- Idempotent migration for explicit first-seen news batches.
SET @migration_schema = DATABASE();

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_items` ADD COLUMN `first_seen_run_id` VARCHAR(64) NULL AFTER `effective_published_at`',
    'SELECT 1')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_items'
    AND COLUMN_NAME = 'first_seen_run_id'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_items` ADD INDEX `idx_ht_news_first_seen_run` (`first_seen_run_id`, `effective_published_at`, `id`)',
    'SELECT 1')
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_items'
    AND INDEX_NAME = 'idx_ht_news_first_seen_run'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_sync_runs` ADD COLUMN `public_new_count` INT DEFAULT 0 AFTER `new_count`',
    'SELECT 1')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_sync_runs'
    AND COLUMN_NAME = 'public_new_count'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `ht_news_sync_runs` ADD INDEX `idx_ht_news_sync_public_batch` (`public_new_count`, `run_at`, `id`)',
    'SELECT 1')
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @migration_schema
    AND TABLE_NAME = 'ht_news_sync_runs'
    AND INDEX_NAME = 'idx_ht_news_sync_public_batch'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

UPDATE ht_news_items AS item
JOIN (
  SELECT run_at, MIN(id) AS id
  FROM ht_news_sync_runs
  GROUP BY run_at
) AS run ON run.run_at = item.first_seen_at
SET item.first_seen_run_id = run.id
WHERE item.first_seen_run_id IS NULL
  AND item.source_type IN ('RSS', '公众号');

UPDATE ht_news_sync_runs AS run
LEFT JOIN (
  SELECT first_seen_run_id, COUNT(*) AS item_count
  FROM ht_news_items
  WHERE first_seen_run_id IS NOT NULL
    AND source_type IN ('RSS', '公众号')
  GROUP BY first_seen_run_id
) AS batch ON batch.first_seen_run_id = run.id
SET run.public_new_count = COALESCE(batch.item_count, 0);
