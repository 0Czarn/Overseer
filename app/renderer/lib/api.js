// Renderer-side API client. All calls go through the preload bridge (IPC), never directly to the network.

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code; // machine-readable reason, e.g. 'game_not_running' from /api/live/*
  }
}

export function createApi(bridge = globalThis.hoi4dbg) {
  async function call(method, path, body) {
    if (!bridge) throw new ApiError('Desktop bridge not available', 0);
    const res = await bridge.request(method, path, body);
    if (!res.ok) throw new ApiError(res.body?.error ?? `Request failed (${res.status})`, res.status, res.body?.code);
    return res.body;
  }
  return {
    get: (path) => call('GET', path),
    post: (path, body) => call('POST', path, body),
    log: (level, message) => call('POST', '/api/logs/app', { level, message }).catch(() => {}),
  };
}
