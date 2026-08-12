'use strict';

const crypto = require('node:crypto');
const { ApiError } = require('./errors');

const MAX_CONFIG_BYTES = 180_000;
const MAX_SOURCES = 50;
const MAX_WECHAT_ACCOUNTS = 20;

function base64url(value) {
  return Buffer.from(value).toString('base64url');
}

function unbase64url(value) {
  return Buffer.from(value, 'base64url');
}

function constantEqual(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function parsePasswordHash(value) {
  const [algorithm, iterations, salt, digest] = String(value || '').split('$');
  if (algorithm !== 'pbkdf2-sha256' || !/^\d{5,7}$/.test(iterations) || !salt || !/^[A-Za-z0-9_-]{32,}$/.test(digest || '')) {
    throw new Error('NEWS_ADMIN_PASSWORD_PBKDF2 must be a pbkdf2-sha256 hash.');
  }
  return { iterations: Number(iterations), salt, digest };
}

function verifyPassword(password, encoded) {
  const parsed = parsePasswordHash(encoded);
  const actual = crypto.pbkdf2Sync(String(password), parsed.salt, parsed.iterations, 32, 'sha256').toString('base64url');
  return constantEqual(actual, parsed.digest);
}

function signSession(secret, expiresAt) {
  const payload = base64url(JSON.stringify({ role: 'news-source-admin', exp: expiresAt }));
  const signature = crypto.createHmac('sha256', secret).update(payload).digest('base64url');
  return `${payload}.${signature}`;
}

function verifySession(token, secret) {
  const [payload, signature] = String(token || '').split('.');
  if (!payload || !signature) return false;
  const expected = crypto.createHmac('sha256', secret).update(payload).digest('base64url');
  if (!constantEqual(signature, expected)) return false;
  try {
    const value = JSON.parse(unbase64url(payload).toString('utf8'));
    return value.role === 'news-source-admin' && Number(value.exp) > Date.now();
  } catch {
    return false;
  }
}

function assertHttpsUrl(value, field) {
  let parsed;
  try { parsed = new URL(String(value || '')); } catch { throw new ApiError(400, 'INVALID_CONFIG', `${field} must be an HTTPS URL.`); }
  const host = parsed.hostname.toLowerCase();
  if (parsed.protocol !== 'https:' || !host || parsed.username || parsed.password || host === 'localhost' || host.endsWith('.local') || /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(':')) {
    throw new ApiError(400, 'INVALID_CONFIG', `${field} must use a public HTTPS hostname.`);
  }
  return parsed;
}

function assertIdentifier(value, field) {
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(String(value || ''))) {
    throw new ApiError(400, 'INVALID_CONFIG', `${field} must be a lowercase source identifier.`);
  }
}

function assertArray(value, field, maximum = MAX_SOURCES) {
  if (!Array.isArray(value) || value.length > maximum) throw new ApiError(400, 'INVALID_CONFIG', `${field} has an invalid number of entries.`);
}

function validateSourceConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) throw new ApiError(400, 'INVALID_CONFIG', 'config must be a JSON object.');
  if (Buffer.byteLength(JSON.stringify(config), 'utf8') > MAX_CONFIG_BYTES) throw new ApiError(413, 'INVALID_CONFIG', 'config is too large.');
  const ids = new Set();
  for (const [field, maximum] of [['rss', MAX_SOURCES], ['hotlists', MAX_SOURCES]]) {
    assertArray(config[field] || [], field, maximum);
    for (const source of config[field] || []) {
      if (!source || typeof source !== 'object') throw new ApiError(400, 'INVALID_CONFIG', `${field} entries must be objects.`);
      assertIdentifier(source.id, `${field}.id`);
      if (ids.has(source.id)) throw new ApiError(400, 'INVALID_CONFIG', `source id ${source.id} is duplicated.`);
      ids.add(source.id);
      if (!String(source.name || '').trim() || String(source.name).length > 160) throw new ApiError(400, 'INVALID_CONFIG', `${source.id} needs a name.`);
      if (field === 'rss') {
        assertHttpsUrl(source.url, `${source.id}.url`);
        if (!Number.isInteger(Number(source.maxAgeDays || 7)) || Number(source.maxAgeDays || 7) < 1 || Number(source.maxAgeDays || 7) > 30) {
          throw new ApiError(400, 'INVALID_CONFIG', `${source.id}.maxAgeDays must be between 1 and 30.`);
        }
        if (source.contentAllowedDomains !== undefined && !Array.isArray(source.contentAllowedDomains)) throw new ApiError(400, 'INVALID_CONFIG', `${source.id}.contentAllowedDomains must be an array.`);
        for (const domain of source.contentAllowedDomains || []) {
          if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(String(domain))) {
            throw new ApiError(400, 'INVALID_CONFIG', `${source.id} has an invalid allowed content domain.`);
          }
        }
      }
      if (field === 'hotlists' && !/^[a-z0-9.-]+$/i.test(String(source.expectedDomain || ''))) {
        throw new ApiError(400, 'INVALID_CONFIG', `${source.id} has an invalid expected domain.`);
      }
    }
  }
  const wechat = config.wechat || {};
  if (!wechat || typeof wechat !== 'object' || Array.isArray(wechat)) throw new ApiError(400, 'INVALID_CONFIG', 'wechat must be an object.');
  assertArray(wechat.accounts || [], 'wechat.accounts', MAX_WECHAT_ACCOUNTS);
  for (const account of wechat.accounts || []) {
    if (!account || typeof account !== 'object') throw new ApiError(400, 'INVALID_CONFIG', 'wechat account entries must be objects.');
    assertIdentifier(account.id, 'wechat.accounts.id');
    if (ids.has(account.id)) throw new ApiError(400, 'INVALID_CONFIG', `source id ${account.id} is duplicated.`);
    ids.add(account.id);
    if (!String(account.name || '').trim() || !/^[A-Za-z0-9+/]+={0,2}$/.test(String(account.fakeid || ''))) {
      throw new ApiError(400, 'INVALID_CONFIG', `${account.id} needs a name and a valid fakeid.`);
    }
  }
  if (!Array.isArray(config.keywordGroups) || !config.keywordGroups.length) throw new ApiError(400, 'INVALID_CONFIG', 'keywordGroups must not be empty.');
  for (const group of config.keywordGroups) {
    if (!group || !String(group.tag || '').trim() || !Array.isArray(group.terms) || !group.terms.length) throw new ApiError(400, 'INVALID_CONFIG', 'every keyword group needs a tag and at least one term.');
  }
  if (!config.settings || typeof config.settings !== 'object') throw new ApiError(400, 'INVALID_CONFIG', 'settings must be an object.');
  if (config.settings.apiUrl !== undefined) assertHttpsUrl(config.settings.apiUrl, 'settings.apiUrl');
  return config;
}

class AdminConfigRepository {
  constructor({ envId, token, fetchImpl = globalThis.fetch }) {
    this.baseUrl = `https://${envId}.api.tcloudbasegateway.com/v1/rdb/rest`;
    this.token = token;
    this.fetchImpl = fetchImpl;
  }

  async request(method, table, { query = {}, body } = {}) {
    const url = new URL(`${this.baseUrl}/${table}`);
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    let response;
    try {
      response = await this.fetchImpl(url, { method, headers: { Authorization: `Bearer ${this.token}`, Accept: 'application/json', 'Content-Type': 'application/json', Prefer: 'return=representation' }, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch { throw new ApiError(503, 'DATABASE_UNAVAILABLE', 'The configuration database is temporarily unavailable.', { retryable: true }); }
    const text = await response.text();
    if (!response.ok) {
      console.error('news source configuration database request failed', response.status);
      throw new ApiError(503, 'DATABASE_UNAVAILABLE', 'The configuration database is temporarily unavailable.', { retryable: true });
    }
    try { const parsed = text ? JSON.parse(text) : []; return Array.isArray(parsed) ? parsed : []; } catch { return []; }
  }

  async latest() {
    const rows = await this.request('GET', 'ht_news_source_config_versions', { query: { select: 'id,status,config_json,config_sha256,change_note,published_by,published_at', status: 'eq.published', order: 'published_at.desc,id.desc', limit: 1 } });
    return rows[0] || null;
  }

  async list(limit = 12) {
    return this.request('GET', 'ht_news_source_config_versions', { query: { select: 'id,status,config_sha256,change_note,published_by,published_at', order: 'published_at.desc,id.desc', limit } });
  }

  async get(id) {
    const rows = await this.request('GET', 'ht_news_source_config_versions', { query: { select: 'id,status,config_json,config_sha256,change_note,published_by,published_at', id: `eq.${id}`, limit: 1 } });
    return rows[0] || null;
  }

  async publish({ config, changeNote, publishedBy = 'administrator' }) {
    const id = crypto.randomUUID();
    const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
    const configJson = JSON.stringify(config);
    const configSha256 = crypto.createHash('sha256').update(configJson).digest('hex');
    await this.request('POST', 'ht_news_source_config_versions', { body: { id, status: 'published', config_json: configJson, config_sha256: configSha256, change_note: String(changeNote || '').trim().slice(0, 500), published_by: publishedBy, published_at: now } });
    await this.request('PATCH', 'ht_news_source_config_versions', { query: { status: 'eq.published', id: `neq.${id}` }, body: { status: 'archived' } });
    return this.get(id);
  }
}

function createAdminServiceFromEnv(env = process.env, repository) {
  if (!env.NEWS_ADMIN_PASSWORD_PBKDF2 || !env.NEWS_ADMIN_SESSION_SECRET) return null;
  const adminRepository = repository || new AdminConfigRepository({ envId: env.CLOUDBASE_ENV_ID, token: env.CLOUDBASE_API_KEY || env.CLOUDBASE_ACCESS_TOKEN || env.CLOUDBASE_TOKEN });
  return {
    login(password) {
      if (!verifyPassword(password, env.NEWS_ADMIN_PASSWORD_PBKDF2)) throw new ApiError(401, 'UNAUTHORIZED', 'The administrator password is invalid.');
      return { token: signSession(env.NEWS_ADMIN_SESSION_SECRET, Date.now() + 30 * 60 * 1000), expiresAt: new Date(Date.now() + 30 * 60 * 1000).toISOString() };
    },
    authorize(token) { if (!verifySession(token, env.NEWS_ADMIN_SESSION_SECRET)) throw new ApiError(401, 'UNAUTHORIZED', 'The administrator session is invalid or has expired.'); },
    latest: () => adminRepository.latest(),
    list: () => adminRepository.list(),
    get: (id) => adminRepository.get(id),
    publish: async (config, changeNote) => adminRepository.publish({ config: validateSourceConfig(config), changeNote }),
  };
}

module.exports = { AdminConfigRepository, createAdminServiceFromEnv, validateSourceConfig, verifyPassword, signSession, verifySession };
