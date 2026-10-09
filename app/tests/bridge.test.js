import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import bridgeModule from '../api-bridge.cjs';
import backendModule from '../backend-process.cjs';
import { createApi, ApiError } from '../renderer/lib/api.js';

const { validateApiRequest, forwardApiRequest, TOKEN_HEADER } = bridgeModule;
const { pythonCandidates, parseReadyLine, startBackend } = backendModule;
const BACKEND_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'backend');

test('validateApiRequest allows only GET/POST on /api paths', () => {
  assert.deepEqual(validateApiRequest({ method: 'get', path: '/api/status' }),
    { method: 'GET', path: '/api/status', body: undefined });
  assert.deepEqual(validateApiRequest({ method: 'POST', path: '/api/reports', body: { a: 1 } }).body, { a: 1 });
  assert.throws(() => validateApiRequest({ method: 'DELETE', path: '/api/status' }), /Method/);
  assert.throws(() => validateApiRequest({ method: 'GET', path: 'http://evil/api' }), /Path/);
  assert.throws(() => validateApiRequest({ method: 'GET', path: '/api/../secret' }), /Path/);
  assert.throws(() => validateApiRequest({ method: 'GET', path: '/other' }), /Path/);
  assert.throws(() => validateApiRequest(null), /Invalid/);
});

test('forwardApiRequest adds the token and reports unreachable backends', async () => {
  let seen;
  const fakeFetch = async (url, init) => {
    seen = { url, init };
    return { ok: true, status: 200, json: async () => ({ hello: 'world' }) };
  };
  const res = await forwardApiRequest({ port: 1234, token: 'tok' }, { method: 'GET', path: '/api/health' }, fakeFetch);
  assert.deepEqual(res, { ok: true, status: 200, body: { hello: 'world' } });
  assert.equal(seen.url, 'http://127.0.0.1:1234/api/health');
  assert.equal(seen.init.headers[TOKEN_HEADER], 'tok');

  const down = await forwardApiRequest({ port: 1, token: 't' }, { path: '/api/health' },
    async () => { throw new Error('ECONNREFUSED'); });
  assert.equal(down.ok, false);
  assert.match(down.body.error, /unreachable/);
});

test('createApi unwraps bodies and throws ApiError on failure', async () => {
  const api = createApi({
    request: async (method, p) => (p === '/api/ok' ? { ok: true, status: 200, body: { v: 1 } }
      : { ok: false, status: 404, body: { error: 'nope' } }),
  });
  assert.deepEqual(await api.get('/api/ok'), { v: 1 });
  await assert.rejects(api.get('/api/missing'), (err) => err instanceof ApiError && err.status === 404 && err.message === 'nope');
  await assert.rejects(createApi(undefined).get('/api/ok'), /bridge/);
});

test('pythonCandidates honours HOI4DBG_PYTHON and platform', () => {
  assert.deepEqual(pythonCandidates({ HOI4DBG_PYTHON: 'C:/py/python.exe' }, 'win32'),
    [{ command: 'C:/py/python.exe', args: [] }]);
  assert.equal(pythonCandidates({}, 'win32')[0].command, 'py');
  assert.equal(pythonCandidates({}, 'linux')[0].command, 'python');
});

test('parseReadyLine', () => {
  assert.equal(parseReadyLine('{"event":"ready","port":5000}').port, 5000);
  assert.equal(parseReadyLine('{"event":"ready","port":0}'), null);
  assert.equal(parseReadyLine('hello'), null);
});

test('startBackend launches the real Python backend and it answers through the bridge', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hoi4dbg-test-'));
  const env = { ...process.env, HOI4DBG_DATA_DIR: dataDir };
  const backend = await startBackend({ backendDir: BACKEND_DIR, token: 'node-test', extraArgs: ['--no-game'], env });
  try {
    const res = await forwardApiRequest({ port: backend.port, token: 'node-test' }, { path: '/api/countries' });
    assert.equal(res.status, 200);
    assert.equal(res.body.source, 'demo');
    const denied = await forwardApiRequest({ port: backend.port, token: 'wrong' }, { path: '/api/countries' });
    assert.equal(denied.status, 401);
  } finally {
    const exited = new Promise((resolve) => backend.child.once('exit', resolve));
    backend.stop();
    await exited;
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});
