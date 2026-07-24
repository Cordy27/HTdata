'use strict';

const http = require('node:http');
const { createRequestHandler } = require('./lib/app');
const { createAuthenticatorFromEnv } = require('./lib/auth');
const { CloudBaseNewsRepository } = require('./lib/repository');

function buildRuntime() {
  const cursorSecret = process.env.NEWS_CURSOR_SECRET;
  if (!cursorSecret) throw new Error('NEWS_CURSOR_SECRET must be configured.');
  return {
    repository: CloudBaseNewsRepository.fromEnv(),
    authenticate: createAuthenticatorFromEnv(),
    cursorSecret,
    maxResponseBytes: Number(process.env.NEWS_API_MAX_RESPONSE_BYTES || 5_000_000),
  };
}

if (require.main === module) {
  let runtime;
  const handler = async (request, response) => {
    runtime ||= buildRuntime();
    return createRequestHandler(runtime)(request, response);
  };
  const server = http.createServer(handler);
  server.listen(9000, '0.0.0.0', () => console.log('ht-news-api listening on port 9000'));
  const shutdown = () => server.close(() => process.exit(0));
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

module.exports = { buildRuntime };
