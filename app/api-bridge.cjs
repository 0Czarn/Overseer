'use strict';
// Forwards renderer API calls (received over IPC) to the local backend. The renderer never
// sees the token or the port, and may only reach /api/ paths with GET or POST.

const TOKEN_HEADER = 'X-HOI4DBG-Token';
const PATH_RE = /^\/api\/[A-Za-z0-9_\-./]*(\?[A-Za-z0-9_\-.=&%]*)?$/;

function validateApiRequest(request) {
  if (!request || typeof request !== 'object') throw new Error('Invalid request');
  const method = String(request.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'POST') throw new Error(`Method not allowed: ${method}`);
  const path = String(request.path || '');
  if (!PATH_RE.test(path) || path.includes('..')) throw new Error(`Path not allowed: ${path}`);
  return { method, path, body: method === 'POST' ? (request.body ?? {}) : undefined };
}

async function forwardApiRequest({ port, token }, request, fetchImpl = fetch) {
  const { method, path, body } = validateApiRequest(request);
  const headers = { [TOKEN_HEADER]: token };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  try {
    const res = await fetchImpl(`http://127.0.0.1:${port}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let payload = null;
    try {
      payload = await res.json();
    } catch {
      payload = { error: 'Backend returned a non-JSON response' };
    }
    return { ok: res.ok, status: res.status, body: payload };
  } catch (err) {
    return { ok: false, status: 0, body: { error: `Backend unreachable: ${err.message}` } };
  }
}

module.exports = { TOKEN_HEADER, validateApiRequest, forwardApiRequest };
