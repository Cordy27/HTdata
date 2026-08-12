'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const test = require('node:test');
const { createAdminServiceFromEnv, validateSourceConfig } = require('../lib/admin');

function passwordHash(password) {
  const salt = 'admin-test-salt';
  const digest = crypto.pbkdf2Sync(password, salt, 120000, 32, 'sha256').toString('base64url');
  return `pbkdf2-sha256$120000$${salt}$${digest}`;
}

function config() {
  return {
    settings: { timeoutSeconds: 12 },
    keywordGroups: [{ tag: 'AI', terms: ['AI'] }],
    hotlists: [{ id: 'example-hot', name: 'Example hot', expectedDomain: 'example.com', enabled: true }],
    rss: [{ id: 'example-rss', name: 'Example RSS', url: 'https://example.com/feed.xml', contentAllowedDomains: ['example.com'], enabled: true, maxAgeDays: 7 }],
    wechat: { enabled: true, accounts: [{ id: 'example-wechat', name: 'Example', fakeid: 'MzI3MTA0MTk1MA==', enabled: true }] },
  };
}

test('configuration validation blocks unsafe source addresses and duplicate IDs', () => {
  assert.equal(validateSourceConfig(config()).rss[0].id, 'example-rss');
  const unsafe = config();
  unsafe.rss[0].url = 'http://127.0.0.1/feed.xml';
  assert.throws(() => validateSourceConfig(unsafe), { code: 'INVALID_CONFIG' });
  const unsafeHotlistApi = config();
  unsafeHotlistApi.settings.apiUrl = 'http://127.0.0.1/api/s';
  assert.throws(() => validateSourceConfig(unsafeHotlistApi), { code: 'INVALID_CONFIG' });
  const duplicate = config();
  duplicate.wechat.accounts[0].id = 'example-rss';
  assert.throws(() => validateSourceConfig(duplicate), { code: 'INVALID_CONFIG' });
});

test('administrator sessions are short-lived signed tokens', () => {
  const service = createAdminServiceFromEnv({
    CLOUDBASE_ENV_ID: 'test', CLOUDBASE_API_KEY: 'key',
    NEWS_ADMIN_PASSWORD_PBKDF2: passwordHash('correct horse battery staple'),
    NEWS_ADMIN_SESSION_SECRET: 'session-test-secret',
  }, {});
  assert.throws(() => service.login('wrong password'), { code: 'UNAUTHORIZED' });
  const login = service.login('correct horse battery staple');
  assert.doesNotThrow(() => service.authorize(login.token));
  assert.throws(() => service.authorize(`${login.token}x`), { code: 'UNAUTHORIZED' });
});
