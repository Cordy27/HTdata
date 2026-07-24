'use strict';

const crypto = require('node:crypto');
const { ApiError } = require('./errors');

function sha256(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function splitValues(value) {
  return String(value || '').split(/[;,\s]+/).map((item) => item.trim()).filter(Boolean);
}

function createBearerAuthenticator({ hashes = [], rawKeys = [] } = {}) {
  const accepted = new Set([...hashes.map((value) => value.toLowerCase()), ...rawKeys.map(sha256)]);
  if (!accepted.size) throw new Error('NEWS_API_KEY_SHA256 or NEWS_API_KEY must be configured.');

  return function authenticate(request) {
    const match = String(request.headers.authorization || '').match(/^Bearer\s+([^\s]+)$/i);
    if (!match) throw new ApiError(401, 'UNAUTHORIZED', 'A Bearer API key is required.');
    const candidate = Buffer.from(sha256(match[1]), 'hex');
    const valid = [...accepted].some((hash) => {
      if (!/^[0-9a-f]{64}$/i.test(hash)) return false;
      const expected = Buffer.from(hash, 'hex');
      return expected.length === candidate.length && crypto.timingSafeEqual(expected, candidate);
    });
    if (!valid) throw new ApiError(401, 'UNAUTHORIZED', 'The API key is invalid or has been revoked.');
  };
}

function createAuthenticatorFromEnv(env = process.env) {
  return createBearerAuthenticator({
    hashes: splitValues(env.NEWS_API_KEY_SHA256),
    rawKeys: splitValues(env.NEWS_API_KEY),
  });
}

module.exports = { createBearerAuthenticator, createAuthenticatorFromEnv, sha256 };
