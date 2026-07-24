-- RSS and WeChat full-content storage and query indexes.
-- Apply once after checking information_schema for existing columns/indexes.

ALTER TABLE ht_news_items
  ADD COLUMN content_text MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL AFTER summary,
  ADD COLUMN content_html MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL AFTER content_text,
  ADD COLUMN content_status VARCHAR(24) NOT NULL DEFAULT 'pending' AFTER content_html,
  ADD COLUMN content_fetched_at DATETIME NULL AFTER content_status,
  ADD COLUMN content_hash CHAR(64) NULL AFTER content_fetched_at,
  ADD COLUMN content_error VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL AFTER content_hash;

ALTER TABLE ht_news_items ADD COLUMN effective_published_at DATETIME NULL AFTER published_at;
UPDATE ht_news_items SET effective_published_at = COALESCE(published_at, collected_at, created_at)
WHERE effective_published_at IS NULL;
ALTER TABLE ht_news_items MODIFY COLUMN effective_published_at DATETIME NOT NULL;

CREATE INDEX idx_ht_news_published_id ON ht_news_items (published_at, id);
CREATE INDEX idx_ht_news_effective_published_id ON ht_news_items (effective_published_at, id);
CREATE INDEX idx_ht_news_type_published_id ON ht_news_items (source_type, published_at, id);
CREATE INDEX idx_ht_news_source_published_id ON ht_news_items (source_id, published_at, id);
CREATE INDEX idx_ht_news_updated_id ON ht_news_items (updated_at, id);
