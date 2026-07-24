'use strict';

const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');

test('HTTP function bootstrap starts on port 9000', { timeout: 15_000 }, async () => {
  const child = spawn(process.execPath, ['index.js'], {
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env,
      CLOUDBASE_ENV_ID: 'test-env',
      CLOUDBASE_API_KEY: 'test-token',
      NEWS_API_KEY_SHA256: '2bb80d537b1da3e38bd30361aa855686bde0ba509f951e5dbb53f8f7f34e6a3e',
      NEWS_CURSOR_SECRET: 'cursor-test-secret',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('server did not start')), 10_000);
      child.once('exit', (code) => reject(new Error(`server exited with ${code}`)));
      child.stdout.on('data', (chunk) => {
        if (String(chunk).includes('listening on port 9000')) {
          clearTimeout(timer);
          resolve();
        }
      });
    });
    const response = await fetch('http://127.0.0.1:9000/health');
    assert.equal(response.status, 200);
    assert.equal((await response.json()).data.status, 'ok');
  } finally {
    child.kill();
    await new Promise((resolve) => child.once('exit', resolve));
  }
});
