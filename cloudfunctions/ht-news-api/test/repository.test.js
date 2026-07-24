'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { CloudBaseNewsRepository, formatDbTimestamp } = require('../lib/repository');
const { decodeCursor, encodeCursor, normalizeIncrementQuery, normalizeQuery } = require('../lib/query');

test('repository uses the CloudBase RDB REST root without an extra schema segment', () => {
  const repository = new CloudBaseNewsRepository({ envId: 'test-env', token: 'token', fetchImpl: async () => null });
  assert.equal(repository.baseUrl, 'https://test-env.api.tcloudbasegateway.com/v1/rdb/rest');
});

test('repository projects content only when search or output needs it', () => {
  const repository = new CloudBaseNewsRepository({ envId: 'test-env', token: 'token', fetchImpl: async () => null });
  const compact = normalizeQuery({ view: 'compact', keywordFields: ['title'], publishedFrom: '2026-07-01', publishedTo: '2026-07-16' });
  const compactParams = repository.buildBaseQuery(compact, null, 30);
  assert.equal(compactParams.select.includes('content_text'), false);
  assert.equal(compactParams.select.includes('content_html'), false);
  assert.match(compactParams.and, /effective_published_at\.gte/);
  assert.match(compactParams.and, /effective_published_at\.lte/);
  assert.doesNotMatch(compactParams.and, /(^|[^_])published_at\./);

  const content = normalizeQuery({ view: 'full', keywords: ['AI'], keywordFields: ['content'], includeHtml: true });
  const contentParams = repository.buildBaseQuery(content, null, 20);
  assert.equal(contentParams.select.includes('content_text'), true);
  assert.equal(contentParams.select.includes('content_html'), true);
});

test('CloudBase DATETIME filters use Shanghai local time', () => {
  assert.equal(formatDbTimestamp('2026-07-16T00:00:00.000Z'), '2026-07-16 08:00:00');
  assert.equal(formatDbTimestamp('2026-07-16 09:00:00'), '2026-07-16 09:00:00');
  const repository = new CloudBaseNewsRepository({ envId: 'test-env', token: 'token', fetchImpl: async () => null });
  const query = normalizeQuery(
    {
      publishedFrom: '2026-07-15T00:00:00Z',
      publishedTo: '2026-07-16T00:00:00Z',
      changedAfter: '2026-07-14T00:00:00Z',
    },
    { snapshotAt: '2026-07-17T00:00:00.000Z' },
  );
  const params = repository.buildBaseQuery(query, null, 30);
  assert.match(params.and, /effective_published_at\.gte\.2026-07-15 08:00:00/);
  assert.match(params.and, /effective_published_at\.lte\.2026-07-16 08:00:00/);
  assert.match(params.and, /updated_at\.gt\.2026-07-14 08:00:00/);
  assert.match(params.and, /updated_at\.lte\.2026-07-17 08:00:00/);
});

test('published sorting uses a non-null effective timestamp', () => {
  assert.equal(normalizeQuery({}).sort.column, 'effective_published_at');
});

test('increment queries are bound to an immutable batch and use the standard view by default', () => {
  const query = normalizeIncrementQuery({ batchId: 'run_20260716090000_deadbeef' }, { snapshotAt: '2026-07-16T02:00:00.000Z' });
  assert.equal(query.batchId, 'run_20260716090000_deadbeef');
  assert.equal(query.view, 'standard');
  assert.equal(query.sort.column, 'effective_published_at');
  const repository = new CloudBaseNewsRepository({ envId: 'test-env', token: 'token', fetchImpl: async () => null });
  assert.equal(repository.buildBaseQuery(query, null, 30).first_seen_run_id, 'eq.run_20260716090000_deadbeef');
  assert.throws(() => normalizeIncrementQuery({ cursor: 'opaque' }), /batchId is required/);
  assert.throws(() => normalizeIncrementQuery({ batchId: 'invalid' }), /batchId is invalid/);
});

test('increment cursor cannot be reused for another batch', () => {
  const original = normalizeIncrementQuery({ batchId: 'run_20260716090000_deadbeef' }, { snapshotAt: '2026-07-16T02:00:00.000Z' });
  const cursor = encodeCursor({ query: original, value: '2026-07-16T01:00:00.000Z', id: 'abc123' }, 'secret');
  const other = normalizeIncrementQuery({ batchId: 'run_20260715090000_cafebabe', cursor });
  assert.throws(() => decodeCursor(cursor, other, 'secret'), /does not match/);
});

test('repository resolves latest, specific, and previous public increment batches', async () => {
  const requested = [];
  const repository = new CloudBaseNewsRepository({
    envId: 'test-env', token: 'token',
    fetchImpl: async (url) => {
      requested.push(new URL(url));
      return new Response(JSON.stringify([{ id: 'run_20260716090000_deadbeef', run_at: '2026-07-16 09:00:00', public_new_count: 3, status: 'ok' }]), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    },
  });
  const latest = await repository.resolveIncrementBatch();
  await repository.resolveIncrementBatch('run_20260716090000_deadbeef');
  await repository.findPreviousIncrementBatch(latest);
  assert.equal(requested[0].searchParams.get('public_new_count'), 'gt.0');
  assert.equal(requested[0].searchParams.get('order'), 'run_at.desc,id.desc');
  assert.equal(requested[1].searchParams.get('id'), 'eq.run_20260716090000_deadbeef');
  assert.match(requested[2].searchParams.get('or'), /run_at\.lt\.2026-07-16 09:00:00/);
});

test('changedAfter defaults to ascending update order and is snapshot bounded', () => {
  const repository = new CloudBaseNewsRepository({ envId: 'test-env', token: 'token', fetchImpl: async () => null });
  const query = normalizeQuery({ changedAfter: '2026-07-15T00:00:00Z' }, { snapshotAt: '2026-07-16T00:00:00.000Z' });
  const params = repository.buildBaseQuery(query, null, 30);
  assert.equal(params.order, 'updated_at.asc,id.asc');
  assert.match(params.and, /updated_at\.gt\.2026-07-15 08:00:00/);
  assert.match(params.and, /updated_at\.lte\.2026-07-16 08:00:00/);
});

test('source scans include the primary key so CloudBase does not deduplicate projections', async () => {
  const requested = [];
  const repository = new CloudBaseNewsRepository({
    envId: 'test-env',
    token: 'token',
    fetchImpl: async (url) => {
      requested.push(new URL(url));
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
    },
  });
  await repository.listSources();
  assert.equal(requested[0].searchParams.get('select'), 'id,source_id,source_name,source_type');
});

test('cursor signatures reject tampering and preserve the snapshot', () => {
  const query = normalizeQuery({ sourceTypes: ['rss'] }, { snapshotAt: '2026-07-16T00:00:00.000Z' });
  const cursor = encodeCursor({ query, value: '2026-07-15T00:00:00.000Z', id: 'abc123' }, 'secret');
  assert.equal(decodeCursor(cursor, query, 'secret').snapshotAt, '2026-07-16T00:00:00.000Z');
  assert.throws(() => decodeCursor(`${cursor.slice(0, -1)}x`, query, 'secret'), /cursor/i);
});

test('cursor is bound to filters, sort order, and snapshot', () => {
  const original = normalizeQuery(
    { sourceTypes: ['rss'], keywords: ['AI'], keywordMode: 'all', sortField: 'changedAt', sortDirection: 'asc' },
    { snapshotAt: '2026-07-16T00:00:00.000Z' },
  );
  const cursor = encodeCursor({ query: original, value: '2026-07-15T00:00:00.000Z', id: 'abc123' }, 'secret');
  const sameFilters = normalizeQuery(
    { sourceTypes: ['rss'], keywords: ['AI'], keywordMode: 'all', sortField: 'changedAt', sortDirection: 'asc', cursor },
    { snapshotAt: '2026-07-17T00:00:00.000Z' },
  );
  assert.equal(decodeCursor(cursor, sameFilters, 'secret').snapshotAt, '2026-07-16T00:00:00.000Z');
  assert.throws(() => decodeCursor(cursor, normalizeQuery({ sourceTypes: ['wechat'], keywords: ['AI'], keywordMode: 'all', sortField: 'changedAt', sortDirection: 'asc' }), 'secret'), /does not match/i);
  assert.throws(() => decodeCursor(cursor, normalizeQuery({ sourceTypes: ['rss'], keywords: ['AI'], keywordMode: 'all', sortField: 'changedAt', sortDirection: 'desc' }), 'secret'), /does not match/i);
});

test('repository always scopes search, detail, and batch queries to RSS and WeChat', async () => {
  const requested = [];
  const repository = new CloudBaseNewsRepository({
    envId: 'test-env', token: 'token',
    fetchImpl: async (url) => {
      requested.push(new URL(url));
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } });
    },
  });
  const query = normalizeQuery({ sourceTypes: ['rss'], limit: 1 });
  await repository.search(query, null, () => true);
  await repository.getById('abc123');
  await repository.getByIds(['abc123']);
  assert.equal(requested[0].searchParams.get('source_type'), 'in.(RSS)');
  assert.equal(requested[1].searchParams.get('source_type'), 'in.(RSS,公众号)');
  assert.equal(requested[2].searchParams.get('source_type'), 'in.(RSS,公众号)');
});

test('oversized filter arrays fail instead of being silently truncated', () => {
  assert.throws(() => normalizeQuery({ tags: Array.from({ length: 21 }, (_, index) => `tag${index}`) }), /at most 20/);
});
