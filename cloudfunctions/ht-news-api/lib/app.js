'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { ApiError } = require('./errors');
const { decodeCursor, encodeCursor, normalizeBatch, normalizeIncrementQuery, normalizeQuery, queryHash, queryParamsToObject } = require('./query');
const { presentIncrementBatch, presentNews } = require('./presenter');
const { rowMatches } = require('./search');

const DOCUMENT_ROOT = path.resolve(__dirname, '..');
const PUBLIC_DOCUMENTS = {
  '/openapi.yaml': { file: 'openapi.yaml', contentType: 'application/yaml; charset=utf-8' },
  '/llms.txt': { file: 'llms.txt', contentType: 'text/plain; charset=utf-8' },
};
const PORTAL_DOCS_URL = 'https://cordy27.github.io/HTdata/docs/';

const DEFAULT_CORS_ORIGINS = ['https://cordy27.github.io'];

function corsHeaders(request) {
  const origin = String(request.headers.origin || '').trim();
  const allowedOrigins = String(process.env.NEWS_API_CORS_ORIGINS || DEFAULT_CORS_ORIGINS.join(','))
    .split(',').map((value) => value.trim()).filter(Boolean);
  if (!origin || !allowedOrigins.includes(origin)) return {};
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Max-Age': '600',
    Vary: 'Origin',
  };
}

function sendDocument(response, document, headers = {}) {
  const body = fs.readFileSync(path.join(DOCUMENT_ROOT, document.file), 'utf8');
  response.writeHead(200, {
    'Content-Type': document.contentType,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    ...headers,
  });
  response.end(body);
}

function redirectToPortalDocs(response, headers = {}) {
  response.writeHead(302, { Location: PORTAL_DOCS_URL, 'Cache-Control': 'no-store', ...headers });
  response.end();
}

function send(response, status, payload, maxResponseBytes = 5_000_000, headers = {}) {
  let body = JSON.stringify(payload);
  if (Buffer.byteLength(body, 'utf8') > maxResponseBytes) {
    status = 413;
    body = JSON.stringify({
      ok: false,
      error: {
        code: 'RESPONSE_TOO_LARGE',
        message: 'The response is too large; request fewer articles or omit HTML.',
        retryable: false,
      },
      meta: payload.meta || {},
    });
  }
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers });
  response.end(body);
}

function matchesPublicPath(pathname, suffix) {
  return pathname === suffix || /^[^/]+$/.test(pathname.slice(1, -suffix.length - 1)) && pathname.endsWith(suffix);
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 64 * 1024) throw new ApiError(413, 'QUERY_TOO_BROAD', 'The JSON request body is too large.');
    chunks.push(chunk);
  }
  if (!chunks.length) throw new ApiError(400, 'INVALID_ARGUMENT', 'The request body must be a JSON object.');
  try {
    const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new ApiError(400, 'INVALID_ARGUMENT', 'The request body must be a JSON object.');
    }
    return parsed;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(400, 'INVALID_ARGUMENT', 'The request body must be valid JSON.');
  }
}

function requestMeta(requestId) {
  return { requestId, generatedAt: new Date().toISOString(), schemaVersion: '1' };
}

function validateId(id) {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) throw new ApiError(400, 'INVALID_ARGUMENT', 'The news ID is invalid.');
}

function createRequestHandler({ repository, authenticate, cursorSecret, maxResponseBytes = 5_000_000 }) {
  return async function handler(request, response) {
    const requestId = `req_${crypto.randomUUID().replaceAll('-', '')}`;
    const started = Date.now();
    const headers = corsHeaders(request);
    const reply = (status, payload) => send(response, status, payload, maxResponseBytes, headers);
    try {
      const url = new URL(request.url || '/', 'http://localhost');
      const path = url.pathname.replace(/\/+$/, '') || '/';
      if (request.method === 'OPTIONS') { response.writeHead(204, headers); response.end(); return; }
      if (request.method === 'GET' && matchesPublicPath(path, '/docs')) return redirectToPortalDocs(response, headers);
      const document = Object.entries(PUBLIC_DOCUMENTS).find(([suffix]) => matchesPublicPath(path, suffix));
      if (request.method === 'GET' && document) return sendDocument(response, document[1], headers);
      if (request.method === 'GET' && matchesPublicPath(path, '/health')) {
        return reply(200, { ok: true, data: { service: 'ht-news-api', status: 'ok' }, meta: requestMeta(requestId) });
      }
      authenticate(request);

      if (request.method === 'GET' && path.endsWith('/api/v1/sources')) {
        return reply(200, { ok: true, data: { sources: await repository.listSources() }, meta: requestMeta(requestId) });
      }

      if (request.method === 'GET' && path.endsWith('/api/v1/news')) {
        const query = normalizeQuery(queryParamsToObject(url.searchParams));
        const cursor = decodeCursor(query.cursor, query, cursorSecret);
        if (cursor) query.snapshotAt = cursor.snapshotAt;
        const rows = await repository.search(query, cursor, rowMatches);
        const hasMore = rows.length > query.limit;
        const pageRows = rows.slice(0, query.limit);
        const last = pageRows.at(-1);
        const nextCursor = hasMore && last ? encodeCursor({ query, value: last[query.sort.column], id: last.id }, cursorSecret) : null;
        return reply(200, {
          ok: true,
          data: { items: pageRows.map((row) => presentNews(row, query)), page: { nextCursor, hasMore } },
          meta: { ...requestMeta(requestId), snapshotAt: query.snapshotAt },
        });
      }

      if (request.method === 'GET' && path.endsWith('/api/v1/news/increments')) {
        const query = normalizeIncrementQuery(queryParamsToObject(url.searchParams));
        const batch = await repository.resolveIncrementBatch(query.batchId);
        if (!batch) throw new ApiError(404, 'BATCH_NOT_FOUND', 'The requested news batch was not found.');
        query.batchId = batch.id;
        query.filterHash = queryHash(query);
        const cursor = decodeCursor(query.cursor, query, cursorSecret);
        if (cursor) query.snapshotAt = cursor.snapshotAt;
        const rows = await repository.search(query, cursor, rowMatches);
        const hasMore = rows.length > query.limit;
        const pageRows = rows.slice(0, query.limit);
        const last = pageRows.at(-1);
        const nextCursor = hasMore && last ? encodeCursor({ query, value: last[query.sort.column], id: last.id }, cursorSecret) : null;
        const previous = await repository.findPreviousIncrementBatch(batch);
        return reply(200, {
          ok: true,
          data: {
            batch: presentIncrementBatch(batch, previous?.id || null),
            items: pageRows.map((row) => presentNews(row, query)),
            page: { nextCursor, hasMore },
          },
          meta: { ...requestMeta(requestId), snapshotAt: query.snapshotAt },
        });
      }

      if (request.method === 'POST' && path.endsWith('/api/v1/news/search')) {
        const query = normalizeQuery(await readJson(request));
        const cursor = decodeCursor(query.cursor, query, cursorSecret);
        if (cursor) query.snapshotAt = cursor.snapshotAt;
        const rows = await repository.search(query, cursor, rowMatches);
        const hasMore = rows.length > query.limit;
        const pageRows = rows.slice(0, query.limit);
        const last = pageRows.at(-1);
        const nextCursor = hasMore && last ? encodeCursor({ query, value: last[query.sort.column], id: last.id }, cursorSecret) : null;
        return reply(200, {
          ok: true,
          data: { items: pageRows.map((row) => presentNews(row, query)), page: { nextCursor, hasMore } },
          meta: { ...requestMeta(requestId), snapshotAt: query.snapshotAt },
        });
      }

      if (request.method === 'POST' && path.endsWith('/api/v1/news/batch')) {
        const batch = normalizeBatch(await readJson(request));
        const rows = await repository.getByIds(batch.ids, { includeContent: batch.returnsContent, includeHtml: batch.includeHtml });
        return reply(200, { ok: true, data: { items: rows.map((row) => presentNews(row, batch)) }, meta: requestMeta(requestId) });
      }

      const detailMatch = path.match(/\/api\/v1\/news\/([^/]+)$/);
      if (request.method === 'GET' && detailMatch) {
        const id = decodeURIComponent(detailMatch[1]);
        validateId(id);
        const includeHtml = url.searchParams.get('includeHtml') === 'true';
        const row = await repository.getById(id, { includeHtml });
        if (!row) throw new ApiError(404, 'NEWS_NOT_FOUND', 'The requested news item was not found.');
        return reply(200, { ok: true, data: { item: presentNews(row, { view: 'full', includeHtml }) }, meta: requestMeta(requestId) });
      }

      throw new ApiError(404, 'NOT_FOUND', 'The requested API route does not exist.');
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(500, 'INTERNAL_ERROR', 'An internal error occurred.', { retryable: true });
      if (!(error instanceof ApiError)) console.error('news api request failed', error instanceof Error ? error.name : 'UnknownError');
      return reply(apiError.status, {
        ok: false,
        error: { code: apiError.code, message: apiError.message, retryable: apiError.retryable, ...(apiError.details ? { details: apiError.details } : {}) },
        meta: requestMeta(requestId),
      });
    } finally {
      console.log(JSON.stringify({ event: 'news_api_request', requestId, method: request.method, path: request.url?.split('?')[0], latencyMs: Date.now() - started }));
    }
  };
}

module.exports = { createRequestHandler, readJson };
