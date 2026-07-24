'use strict';

const { ApiError } = require('./errors');

const METADATA_COLUMNS = [
  'id', 'title', 'url', 'source_id', 'source_name', 'source_type', 'external_id',
  'source_status', 'rank_num', 'tags_json', 'matched_terms_json', 'summary',
  'content_status', 'content_fetched_at',
  'content_hash', 'content_error', 'published_at', 'first_seen_at', 'latest_seen_at',
  'collected_at', 'effective_published_at', 'first_seen_run_id', 'observations', 'ai_score', 'ai_reason', 'created_at', 'updated_at',
];

function selectColumns({ content = false, html = false } = {}) {
  return [...METADATA_COLUMNS, ...(content ? ['content_text'] : []), ...(html ? ['content_html'] : [])].join(',');
}

function inFilter(values) {
  return `in.(${values.map((value) => String(value).replace(/[(),]/g, '')).join(',')})`;
}

function formatDbTimestamp(value) {
  const raw = String(value || '').trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw)) {
    return raw.slice(0, 19).replace('T', ' ');
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Date(parsed.getTime() + 8 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 19)
    .replace('T', ' ');
}

class CloudBaseNewsRepository {
  constructor({ envId, token, fetchImpl = globalThis.fetch, maxScanRows = 5000 }) {
    if (!envId || !token) throw new Error('CLOUDBASE_ENV_ID and CLOUDBASE_API_KEY are required.');
    if (typeof fetchImpl !== 'function') throw new Error('A fetch implementation is required.');
    this.baseUrl = `https://${envId}.api.tcloudbasegateway.com/v1/rdb/rest`;
    this.token = token;
    this.fetchImpl = fetchImpl;
    this.maxScanRows = maxScanRows;
    this.sourceCache = null;
  }

  static fromEnv(env = process.env) {
    return new CloudBaseNewsRepository({
      envId: env.CLOUDBASE_ENV_ID,
      token: env.CLOUDBASE_API_KEY || env.CLOUDBASE_ACCESS_TOKEN || env.CLOUDBASE_TOKEN,
      maxScanRows: Number(env.NEWS_API_MAX_SCAN_ROWS || 2000),
    });
  }

  async request(table, query) {
    const url = new URL(`${this.baseUrl}/${table}`);
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
    let response;
    try {
      response = await this.fetchImpl(url, {
        headers: { Authorization: `Bearer ${this.token}`, Accept: 'application/json' },
      });
    } catch {
      throw new ApiError(503, 'DATABASE_UNAVAILABLE', 'The news database is temporarily unavailable.', { retryable: true });
    }
    const text = await response.text();
    if (!response.ok) {
      console.error('news database request failed', response.status);
      throw new ApiError(503, 'DATABASE_UNAVAILABLE', 'The news database is temporarily unavailable.', { retryable: true });
    }
    try {
      const payload = text ? JSON.parse(text) : [];
      return Array.isArray(payload) ? payload : [];
    } catch {
      throw new ApiError(503, 'DATABASE_UNAVAILABLE', 'The news database returned an invalid response.', { retryable: true });
    }
  }

  buildBaseQuery(query, cursor, limit) {
    const conjunctions = [`updated_at.lte.${formatDbTimestamp(query.snapshotAt)}`];
    const params = {
      select: selectColumns({
        content: query.view === 'full' || (query.keywordFields.includes('content') && (query.keywords.length || query.phrase)),
        html: query.includeHtml,
      }),
      source_type: inFilter(query.sourceTypes),
      order: `${query.sort.column}.${query.sort.direction},id.${query.sort.direction}`,
      limit,
    };
    if (query.sourceIds.length) params.source_id = inFilter(query.sourceIds);
    if (query.sourceNames.length) params.source_name = inFilter(query.sourceNames);
    if (query.contentStatuses.length) params.content_status = inFilter(query.contentStatuses);
    if (query.batchId) params.first_seen_run_id = `eq.${query.batchId}`;
    if (query.publishedFrom) conjunctions.push(`effective_published_at.gte.${formatDbTimestamp(query.publishedFrom)}`);
    if (query.publishedTo) conjunctions.push(`effective_published_at.lte.${formatDbTimestamp(query.publishedTo)}`);
    if (query.changedAfter) conjunctions.push(`updated_at.gt.${formatDbTimestamp(query.changedAfter)}`);
    if (query.minAiScore !== null) params.ai_score = `gte.${query.minAiScore}`;
    if (cursor) {
      const op = query.sort.direction === 'desc' ? 'lt' : 'gt';
      params.or = `(${query.sort.column}.${op}.${cursor.value},and(${query.sort.column}.eq.${cursor.value},id.${op}.${cursor.id}))`;
    }
    params.and = `(${conjunctions.join(',')})`;
    return params;
  }

  async search(query, cursor, matches) {
    const needsContent = query.view === 'full' || (query.keywordFields.includes('content') && (query.keywords.length || query.phrase));
    const pageSize = needsContent ? 50 : 200;
    const matched = [];
    let scanned = 0;
    let scanCursor = cursor;
    let exhausted = false;
    while (matched.length < query.limit + 1 && scanned < this.maxScanRows && !exhausted) {
      const size = Math.min(pageSize, this.maxScanRows - scanned);
      const rows = await this.request('ht_news_items', this.buildBaseQuery(query, scanCursor, size));
      scanned += rows.length;
      for (const row of rows) {
        if (matches(row, query)) matched.push(row);
        if (matched.length >= query.limit + 1) break;
      }
      exhausted = rows.length < size;
      const last = rows.at(-1);
      if (last) scanCursor = { value: last[query.sort.column], id: last.id };
    }
    if (!exhausted && matched.length <= query.limit) {
      throw new ApiError(400, 'QUERY_TOO_BROAD', 'The query scans too many rows; add a time or source filter.');
    }
    return matched;
  }

  async getById(id, { includeHtml = false } = {}) {
    const rows = await this.request('ht_news_items', {
      select: selectColumns({ content: true, html: includeHtml }), id: `eq.${id}`, source_type: inFilter(['RSS', '公众号']), limit: 1,
    });
    return rows[0] || null;
  }

  async getByIds(ids, { includeContent = true, includeHtml = false } = {}) {
    const rows = [];
    for (let index = 0; index < ids.length; index += 40) {
      rows.push(...await this.request('ht_news_items', {
        select: selectColumns({ content: includeContent, html: includeHtml }),
        id: inFilter(ids.slice(index, index + 40)),
        source_type: inFilter(['RSS', '公众号']),
        limit: 40,
      }));
    }
    const order = new Map(ids.map((id, index) => [id, index]));
    return rows.sort((a, b) => order.get(a.id) - order.get(b.id));
  }

  async resolveIncrementBatch(batchId = null) {
    const query = {
      select: 'id,run_at,public_new_count,status',
      public_new_count: 'gt.0',
      order: 'run_at.desc,id.desc',
      limit: 1,
    };
    if (batchId) query.id = `eq.${batchId}`;
    const rows = await this.request('ht_news_sync_runs', query);
    return rows[0] || null;
  }

  async findPreviousIncrementBatch(batch) {
    const runAt = formatDbTimestamp(batch.run_at);
    const rows = await this.request('ht_news_sync_runs', {
      select: 'id,run_at,public_new_count,status',
      public_new_count: 'gt.0',
      or: `(run_at.lt.${runAt},and(run_at.eq.${runAt},id.lt.${batch.id}))`,
      order: 'run_at.desc,id.desc',
      limit: 1,
    });
    return rows[0] || null;
  }

  async listSources() {
    if (this.sourceCache && this.sourceCache.expiresAt > Date.now()) return this.sourceCache.value;
    const rows = [];
    for (let offset = 0; offset < 20_000; offset += 1000) {
      const page = await this.request('ht_news_items', {
        select: 'id,source_id,source_name,source_type', source_type: inFilter(['RSS', '公众号']),
        order: 'source_type.asc,source_name.asc,id.asc', limit: 1000, offset,
      });
      rows.push(...page);
      if (page.length < 1000) break;
    }
    const sources = new Map();
    for (const row of rows) {
      const key = `${row.source_type}\0${row.source_id}`;
      const current = sources.get(key) || {
        id: row.source_id || '', name: row.source_name || '',
        type: row.source_type === 'RSS' ? 'rss' : 'wechat', count: 0,
      };
      current.count += 1;
      sources.set(key, current);
    }
    const value = [...sources.values()].sort((a, b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name, 'zh-CN'));
    this.sourceCache = { value, expiresAt: Date.now() + 5 * 60 * 1000 };
    return value;
  }
}

module.exports = { CloudBaseNewsRepository, METADATA_COLUMNS, formatDbTimestamp, inFilter, selectColumns };
