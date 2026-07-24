'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');
const { createRequestHandler } = require('../lib/app');
const { createBearerAuthenticator, sha256 } = require('../lib/auth');
const { normalizeQuery } = require('../lib/query');
const { rowMatches } = require('../lib/search');

const rows = [{
  id: 'abc123', title: 'AI Agent 发布', url: 'https://example.com/1', source_id: 'feed',
  source_name: 'Example', source_type: 'RSS', summary: '摘要', content_text: '完整正文包含大模型',
  content_html: '<p>完整正文</p>', content_status: 'available', tags_json: '["AI"]',
  matched_terms_json: '["Agent"]', published_at: '2026-07-16T01:00:00.000Z',
  effective_published_at: '2026-07-16T01:00:00.000Z', first_seen_run_id: 'run_20260716090000_deadbeef',
  updated_at: '2026-07-16T02:00:00.000Z', ai_score: 80,
}];

function fakeRepository() {
  return {
    async listSources() { return [{ id: 'feed', name: 'Example', type: 'rss', count: 1 }]; },
    async search(query, cursor, matches) { return rows.filter((row) => matches(row, query)); },
    async getById(id) { return rows.find((row) => row.id === id) || null; },
    async getByIds(ids) { return rows.filter((row) => ids.includes(row.id)); },
    async resolveIncrementBatch(batchId) {
      if (batchId && batchId !== 'run_20260716090000_deadbeef') return null;
      return { id: 'run_20260716090000_deadbeef', run_at: '2026-07-16T01:00:00.000Z', public_new_count: 1, status: 'ok' };
    },
    async findPreviousIncrementBatch() {
      return { id: 'run_20260715090000_cafebabe', run_at: '2026-07-15T01:00:00.000Z', public_new_count: 2, status: 'failed' };
    },
  };
}

async function withServer(callback) {
  const handler = createRequestHandler({
    repository: fakeRepository(),
    authenticate: createBearerAuthenticator({ hashes: [sha256('secret')] }),
    cursorSecret: 'cursor-test-secret',
    maxResponseBytes: 5_000_000,
  });
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try { await callback(`http://127.0.0.1:${server.address().port}`); }
  finally { await new Promise((resolve) => server.close(resolve)); }
}

test('health is public and API routes require a bearer key', async () => withServer(async (base) => {
  assert.equal((await fetch(`${base}/health`)).status, 200);
  assert.equal((await fetch(`${base}/api/v1/news`)).status, 401);
  assert.equal((await fetch(`${base}/api/v1/news`, { headers: { Authorization: 'Bearer wrong' } })).status, 401);
}));

test('legacy CloudBase documentation routes redirect to the portal page', async () => withServer(async (base) => {
  for (const path of ['/docs', '/news-api/docs']) {
    const response = await fetch(`${base}${path}`, { redirect: 'manual' });
    assert.equal(response.status, 302);
    assert.equal(response.headers.get('location'), 'https://cordy27.github.io/HTdata/docs/');
  }
}));

test('machine-readable documentation routes are public', async () => withServer(async (base) => {

  const openapi = await fetch(`${base}/openapi.yaml`);
  assert.equal(openapi.status, 200);
  assert.match(openapi.headers.get('content-type'), /^application\/yaml/);
  const openapiText = await openapi.text();
  assert.match(openapiText, /openapi: 3\.1\.0/);
  assert.match(openapiText, /\/api\/v1\/news\/increments/);
  assert.match(openapiText, /BATCH_NOT_FOUND/);

  const agentGuide = await fetch(`${base}/llms.txt`);
  assert.equal(agentGuide.status, 200);
  assert.match(agentGuide.headers.get('content-type'), /^text\/plain/);
  const agentGuideText = await agentGuide.text();
  assert.match(agentGuideText, /GET \/api\/v1\/sources/);
  assert.match(agentGuideText, /GET \/api\/v1\/news\/increments/);
}));

test('public documentation and health routes only match root or function prefix paths', async () => withServer(async (base) => {
  assert.equal((await fetch(`${base}/news-api/docs`, { redirect: 'manual' })).status, 302);
  assert.equal((await fetch(`${base}/news-api/openapi.yaml`)).status, 200);
  assert.equal((await fetch(`${base}/news-api/llms.txt`)).status, 200);
  assert.equal((await fetch(`${base}/news-api/health`)).status, 200);

  assert.equal((await fetch(`${base}/api/v1/news/docs`)).status, 401);
  assert.equal((await fetch(`${base}/api/v1/news/openapi.yaml`)).status, 401);
  assert.equal((await fetch(`${base}/api/v1/news/llms.txt`)).status, 401);
  assert.equal((await fetch(`${base}/api/v1/news/health`)).status, 401);
}));

test('portal origin receives CORS headers while other origins remain blocked', async () => withServer(async (base) => {
  const preflight = await fetch(`${base}/api/v1/news/search`, {
    method: 'OPTIONS',
    headers: { Origin: 'https://cordy27.github.io', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'Authorization, Content-Type' },
  });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('access-control-allow-origin'), 'https://cordy27.github.io');
  assert.match(preflight.headers.get('access-control-allow-headers'), /Authorization/);

  const allowed = await fetch(`${base}/api/v1/sources`, { headers: { Origin: 'https://cordy27.github.io' } });
  assert.equal(allowed.status, 401);
  assert.equal(allowed.headers.get('access-control-allow-origin'), 'https://cordy27.github.io');

  const blocked = await fetch(`${base}/api/v1/sources`, { headers: { Origin: 'https://example.com' } });
  assert.equal(blocked.status, 401);
  assert.equal(blocked.headers.get('access-control-allow-origin'), null);
}));

test('search returns matching RSS content and never exposes html by default', async () => withServer(async (base) => {
  const response = await fetch(`${base}/api/v1/news?q=大模型&view=full`, { headers: { Authorization: 'Bearer secret' } });
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.data.items[0].contentText, '完整正文包含大模型');
  assert.equal(payload.data.items[0].contentHtml, undefined);
}));

test('increments defaults to the latest non-empty batch and exposes previous navigation', async () => withServer(async (base) => {
  const response = await fetch(`${base}/api/v1/news/increments`, { headers: { Authorization: 'Bearer secret' } });
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.data.batch.id, 'run_20260716090000_deadbeef');
  assert.equal(payload.data.batch.newCount, 1);
  assert.equal(payload.data.batch.status, 'complete');
  assert.equal(payload.data.batch.previousBatchId, 'run_20260715090000_cafebabe');
  assert.equal(payload.data.items[0].id, 'abc123');
}));

test('increments accepts an immutable batch ID and rejects unknown batches', async () => withServer(async (base) => {
  const found = await fetch(`${base}/api/v1/news/increments?batchId=run_20260716090000_deadbeef`, {
    headers: { Authorization: 'Bearer secret' },
  });
  assert.equal(found.status, 200);

  const missing = await fetch(`${base}/api/v1/news/increments?batchId=run_20260714090000_aaaaaaaa`, {
    headers: { Authorization: 'Bearer secret' },
  });
  assert.equal(missing.status, 404);
  assert.equal((await missing.json()).error.code, 'BATCH_NOT_FOUND');
}));

test('increments requires batchId when continuing with a cursor', async () => withServer(async (base) => {
  const response = await fetch(`${base}/api/v1/news/increments?cursor=opaque`, {
    headers: { Authorization: 'Bearer secret' },
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error.code, 'INVALID_ARGUMENT');
}));

test('batch content limit is enforced', async () => withServer(async (base) => {
  const ids = Array.from({ length: 21 }, (_, index) => `id${index}`);
  const response = await fetch(`${base}/api/v1/news/batch`, {
    method: 'POST', headers: { Authorization: 'Bearer secret', 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, includeContent: true }),
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error.code, 'QUERY_TOO_BROAD');
}));

test('HTML batches have a lower limit', async () => withServer(async (base) => {
  const response = await fetch(`${base}/api/v1/news/batch`, {
    method: 'POST', headers: { Authorization: 'Bearer secret', 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: Array.from({ length: 6 }, (_, index) => `id${index}`), includeHtml: true }),
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error.code, 'QUERY_TOO_BROAD');
}));

test('POST endpoints reject malformed JSON and non-object JSON bodies', async () => withServer(async (base) => {
  for (const body of ['{"keywords":', '[]']) {
    const response = await fetch(`${base}/api/v1/news/search`, {
      method: 'POST', headers: { Authorization: 'Bearer secret', 'Content-Type': 'application/json' }, body,
    });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, 'INVALID_ARGUMENT');
  }
}));

test('response byte limit returns a stable 413 error', async () => {
  const handler = createRequestHandler({
    repository: fakeRepository(),
    authenticate: createBearerAuthenticator({ hashes: [sha256('secret')] }),
    cursorSecret: 'cursor-test-secret',
    maxResponseBytes: 200,
  });
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/v1/news?q=大模型&view=full`, {
      headers: { Authorization: 'Bearer secret' },
    });
    assert.equal(response.status, 413);
    assert.equal((await response.json()).error.code, 'RESPONSE_TOO_LARGE');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('keyword modes search title summary and content', () => {
  assert.equal(rowMatches(rows[0], normalizeQuery({ keywords: ['不存在', '大模型'], keywordMode: 'any' })), true);
  assert.equal(rowMatches(rows[0], normalizeQuery({ keywords: ['Agent', '大模型'], keywordMode: 'all' })), true);
  assert.equal(rowMatches(rows[0], normalizeQuery({ keywords: ['Agent', '不存在'], keywordMode: 'all' })), false);
  assert.equal(rowMatches(rows[0], normalizeQuery({ phrase: '完整正文', keywordMode: 'phrase' })), true);
});

test('full view defaults to its 20 item response limit', () => {
  assert.equal(normalizeQuery({ view: 'full' }).limit, 20);
  assert.equal(normalizeQuery({ view: 'standard' }).limit, 30);
});
