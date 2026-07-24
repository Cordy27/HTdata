'use strict';

function parseJsonList(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try { const parsed = JSON.parse(String(value)); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}

function sourceType(value) { return value === 'RSS' ? 'rss' : 'wechat'; }

function presentNews(row, { view = 'standard', includeHtml = false } = {}) {
  const item = {
    id: row.id || '', title: row.title || '', url: row.url || '',
    source: { id: row.source_id || '', name: row.source_name || '', type: sourceType(row.source_type) },
    publishedAt: row.published_at || null,
    changedAt: row.updated_at || row.latest_seen_at || null,
    aiScore: row.ai_score === null || row.ai_score === undefined ? null : Number(row.ai_score),
  };
  if (view === 'compact') return item;
  Object.assign(item, {
    summary: row.summary || '', tags: parseJsonList(row.tags_json),
    matchedTerms: parseJsonList(row.matched_terms_json),
    contentStatus: row.content_status || 'pending',
    contentFetchedAt: row.content_fetched_at || null,
    collectedAt: row.collected_at || null,
  });
  if (view === 'full') {
    Object.assign(item, {
      contentText: row.content_text || '', contentHash: row.content_hash || null,
      contentError: row.content_error || null, aiReason: row.ai_reason || '',
      sourceStatus: row.source_status || '', externalId: row.external_id || '',
      firstSeenAt: row.first_seen_at || null, latestSeenAt: row.latest_seen_at || null,
      observations: Number(row.observations || 1),
    });
    if (includeHtml) item.contentHtml = row.content_html || '';
  }
  return item;
}

function presentIncrementBatch(row, previousBatchId = null) {
  return {
    id: row.id || '',
    runAt: row.run_at || null,
    newCount: Number(row.public_new_count || 0),
    status: row.status === 'ok' ? 'complete' : 'partial',
    previousBatchId,
  };
}

module.exports = { parseJsonList, presentIncrementBatch, presentNews };
