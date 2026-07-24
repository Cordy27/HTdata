'use strict';

const crypto = require('node:crypto');
const { ApiError, invalidArgument } = require('./errors');

const PUBLIC_SOURCE_TYPES = Object.freeze({ rss: 'RSS', wechat: '公众号' });
const ALLOWED_KEYWORD_FIELDS = new Set(['title', 'summary', 'content']);
const ALLOWED_CONTENT_STATUSES = new Set(['pending', 'available', 'partial', 'unavailable']);
const ALLOWED_VIEWS = new Set(['compact', 'standard', 'full']);
const SORT_FIELDS = Object.freeze({ publishedAt: 'effective_published_at', changedAt: 'updated_at', aiScore: 'ai_score' });
const BATCH_ID_PATTERN = /^run_\d{14}_[0-9a-f]{8}$/;

function asArray(value) {
  if (value === undefined || value === null || value === '') return [];
  const values = Array.isArray(value) ? value : [value];
  return values.flatMap((item) => String(item).split(',')).map((item) => item.trim()).filter(Boolean);
}

function unique(values) { return [...new Set(values)]; }

function boundedArray(value, maximum, field) {
  const values = unique(asArray(value));
  if (values.length > maximum) throw invalidArgument(`${field} supports at most ${maximum} values.`);
  return values;
}

function parseBoolean(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback;
  if (value === true || String(value).toLowerCase() === 'true' || String(value) === '1') return true;
  if (value === false || String(value).toLowerCase() === 'false' || String(value) === '0') return false;
  throw invalidArgument(`Invalid boolean value: ${value}`);
}

function parseInteger(value, fallback, minimum, maximum, field) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw invalidArgument(`${field} must be an integer between ${minimum} and ${maximum}.`);
  }
  return parsed;
}

function normalizeTimestamp(value, field) {
  if (value === undefined || value === null || value === '') return null;
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) throw invalidArgument(`${field} must be an ISO 8601 timestamp.`);
  return parsed.toISOString();
}

function normalizeSourceTypes(value) {
  const values = asArray(value);
  if (!values.length) return Object.values(PUBLIC_SOURCE_TYPES);
  return unique(values.map((item) => {
    const mapped = PUBLIC_SOURCE_TYPES[item.toLowerCase()];
    if (mapped) return mapped;
    if (item === 'RSS' || item === '公众号') return item;
    throw invalidArgument('sourceTypes only supports rss and wechat.');
  }));
}

function normalizeKeywords(input) {
  const keywords = unique(asArray(input.keywords ?? input.keyword ?? input.q));
  if (keywords.length > 10) throw invalidArgument('At most 10 keywords are allowed.');
  for (const keyword of keywords) {
    if (keyword.length > 80 || /[\u0000-\u001f]/.test(keyword)) {
      throw invalidArgument('Each keyword must contain 1 to 80 printable characters.');
    }
  }
  const keywordMode = String(input.keywordMode || 'any').toLowerCase();
  if (!['any', 'all', 'phrase'].includes(keywordMode)) {
    throw invalidArgument('keywordMode must be any, all, or phrase.');
  }
  const keywordFields = unique(asArray(input.keywordFields || ['title', 'summary', 'content']));
  if (!keywordFields.length || keywordFields.some((field) => !ALLOWED_KEYWORD_FIELDS.has(field))) {
    throw invalidArgument('keywordFields only supports title, summary, and content.');
  }
  const phrase = String(input.phrase || (keywordMode === 'phrase' ? keywords.join(' ') : '')).trim();
  if (keywordMode === 'phrase' && !phrase) throw invalidArgument('phrase mode requires phrase or keywords.');
  return { keywords, keywordMode, keywordFields, phrase };
}

function normalizeSort(input, changedAfter) {
  const raw = typeof input.sort === 'object' && input.sort ? input.sort : {};
  const field = String(raw.field || input.sortField || (changedAfter ? 'changedAt' : 'publishedAt'));
  const direction = String(raw.direction || input.sortDirection || (changedAfter ? 'asc' : 'desc')).toLowerCase();
  if (!SORT_FIELDS[field]) throw invalidArgument('sort.field must be publishedAt, changedAt, or aiScore.');
  if (!['asc', 'desc'].includes(direction)) throw invalidArgument('sort.direction must be asc or desc.');
  return { field, column: SORT_FIELDS[field], direction };
}

function normalizeQuery(input = {}, options = {}) {
  const page = typeof input.page === 'object' && input.page ? input.page : {};
  const changedAfter = normalizeTimestamp(input.changedAfter, 'changedAfter');
  const view = String(input.view || 'standard').toLowerCase();
  if (!ALLOWED_VIEWS.has(view)) throw invalidArgument('view must be compact, standard, or full.');
  const includeHtml = parseBoolean(input.includeHtml, false);
  if (includeHtml && view !== 'full') throw invalidArgument('includeHtml requires view=full.');
  const maximumLimit = view === 'full' ? 20 : 100;
  const defaultLimit = view === 'full' ? 20 : 30;
  const limit = parseInteger(page.limit ?? input.limit, defaultLimit, 1, maximumLimit, 'limit');
  const keywordOptions = normalizeKeywords(input);
  const contentStatuses = unique(asArray(input.contentStatuses));
  if (contentStatuses.some((status) => !ALLOWED_CONTENT_STATUSES.has(status))) {
    throw invalidArgument('contentStatuses contains an unsupported value.');
  }
  const minAiScore = input.minAiScore === undefined || input.minAiScore === '' ? null : Number(input.minAiScore);
  if (minAiScore !== null && (!Number.isFinite(minAiScore) || minAiScore < 0 || minAiScore > 100)) {
    throw invalidArgument('minAiScore must be between 0 and 100.');
  }
  const publishedFrom = normalizeTimestamp(input.publishedFrom, 'publishedFrom');
  const publishedTo = normalizeTimestamp(input.publishedTo, 'publishedTo');
  if (publishedFrom && publishedTo && publishedFrom > publishedTo) {
    throw invalidArgument('publishedFrom must not be later than publishedTo.');
  }
  const sort = normalizeSort(input, changedAfter);
  if (sort.field === 'aiScore' && minAiScore === null) {
    throw invalidArgument('aiScore sorting requires minAiScore so null scores are excluded.');
  }
  const normalized = {
    sourceTypes: normalizeSourceTypes(input.sourceTypes ?? input.sourceType),
    sourceIds: boundedArray(input.sourceIds ?? input.sourceId, 100, 'sourceIds'),
    sourceNames: boundedArray(input.sourceNames ?? input.sourceName, 100, 'sourceNames'),
    tags: boundedArray(input.tags, 20, 'tags'),
    matchedTerms: boundedArray(input.matchedTerms, 20, 'matchedTerms'),
    contentStatuses, publishedFrom, publishedTo, changedAfter, minAiScore,
    ...keywordOptions,
    sort, view, includeHtml, limit,
    cursor: String(page.cursor ?? input.cursor ?? '').trim() || null,
    snapshotAt: options.snapshotAt || new Date().toISOString(),
  };
  normalized.filterHash = queryHash(normalized);
  return normalized;
}

function stableObject(value) {
  if (Array.isArray(value)) return value.map(stableObject);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableObject(value[key])]));
}

function queryHash(query) {
  const filter = { ...query };
  for (const field of ['cursor', 'limit', 'snapshotAt', 'filterHash']) delete filter[field];
  return crypto.createHash('sha256').update(JSON.stringify(stableObject(filter))).digest('hex').slice(0, 24);
}

function cursorSignature(payload, secret) {
  if (!secret) throw new Error('NEWS_CURSOR_SECRET must be configured.');
  return crypto.createHmac('sha256', secret).update(payload).digest('base64url');
}

function encodeCursor({ query, value, id }, secret) {
  const payload = Buffer.from(JSON.stringify({
    v: 1, field: query.sort.field, direction: query.sort.direction, value, id,
    filterHash: query.filterHash, snapshotAt: query.snapshotAt,
  }), 'utf8').toString('base64url');
  return `${payload}.${cursorSignature(payload, secret)}`;
}

function decodeCursor(value, query, secret) {
  if (!value) return null;
  let cursor;
  try {
    const [payload, signature, extra] = String(value).split('.');
    if (!payload || !signature || extra) throw new Error('invalid cursor parts');
    const expected = Buffer.from(cursorSignature(payload, secret));
    const supplied = Buffer.from(signature);
    if (expected.length !== supplied.length || !crypto.timingSafeEqual(expected, supplied)) throw new Error('bad signature');
    cursor = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
  }
  catch { throw new ApiError(400, 'INVALID_CURSOR', 'The pagination cursor is malformed.'); }
  if (cursor.v !== 1 || cursor.filterHash !== query.filterHash || cursor.field !== query.sort.field ||
      cursor.direction !== query.sort.direction || typeof cursor.id !== 'string' || !cursor.id ||
      cursor.value === undefined || !cursor.snapshotAt) {
    throw new ApiError(400, 'INVALID_CURSOR', 'The cursor does not match the current query.');
  }
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(cursor.id) || Number.isNaN(Date.parse(cursor.snapshotAt))) {
    throw new ApiError(400, 'INVALID_CURSOR', 'The cursor contains invalid values.');
  }
  if (query.sort.field === 'aiScore') {
    if (!Number.isFinite(Number(cursor.value))) throw new ApiError(400, 'INVALID_CURSOR', 'The cursor score is invalid.');
    cursor.value = Number(cursor.value);
  } else if (Number.isNaN(Date.parse(String(cursor.value)))) {
    throw new ApiError(400, 'INVALID_CURSOR', 'The cursor timestamp is invalid.');
  }
  return cursor;
}

function normalizeBatch(input = {}) {
  const ids = unique(asArray(input.ids));
  if (!ids.length) throw invalidArgument('ids must contain at least one news ID.');
  if (ids.some((id) => id.length > 64 || !/^[A-Za-z0-9_-]+$/.test(id))) {
    throw invalidArgument('ids contains an invalid news ID.');
  }
  const includeContent = parseBoolean(input.includeContent, true);
  const view = String(input.view || (includeContent ? 'full' : 'standard')).toLowerCase();
  if (!ALLOWED_VIEWS.has(view)) throw invalidArgument('view must be compact, standard, or full.');
  const returnsContent = includeContent || view === 'full';
  const includeHtml = parseBoolean(input.includeHtml, false);
  const maximum = includeHtml ? 5 : returnsContent ? 20 : 100;
  if (ids.length > maximum) {
    throw new ApiError(400, 'QUERY_TOO_BROAD', `At most ${maximum} IDs are allowed for this response.`, {
      details: { maximum, returnsContent },
    });
  }
  if (includeHtml && !returnsContent) throw invalidArgument('includeHtml requires content output.');
  return { ids, view: returnsContent ? 'full' : view, includeHtml, returnsContent };
}

function normalizeIncrementQuery(input = {}, options = {}) {
  const batchId = String(input.batchId || '').trim();
  if (batchId && !BATCH_ID_PATTERN.test(batchId)) throw invalidArgument('batchId is invalid.');
  const cursor = String(input.cursor || '').trim();
  if (cursor && !batchId) throw invalidArgument('batchId is required when cursor is provided.');
  const query = normalizeQuery({
    sourceTypes: input.sourceTypes ?? input.sourceType,
    view: input.view,
    includeHtml: input.includeHtml,
    limit: input.limit,
    cursor,
    sortField: 'publishedAt',
    sortDirection: 'desc',
  }, options);
  query.batchId = batchId || null;
  query.filterHash = queryHash(query);
  return query;
}

function queryParamsToObject(searchParams) {
  const result = {};
  for (const [key, value] of searchParams) {
    if (result[key] === undefined) result[key] = value;
    else result[key] = asArray(result[key]).concat(value);
  }
  return result;
}

module.exports = {
  PUBLIC_SOURCE_TYPES, SORT_FIELDS, asArray, decodeCursor, encodeCursor,
  normalizeBatch, normalizeIncrementQuery, normalizeQuery, queryHash, queryParamsToObject,
};
