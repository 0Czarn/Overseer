// Optional auto-start of the next focus of the player's plan when no focus is selected (backend:
// /api/live/focus/autostart, a LOCAL game memory write, single player only; saved days are dropped, no political
// power is taken). Focuses with conditions the app cannot check or with effects on picking are left to the player.

export const AUTOSTART_POLL_MS = 3000;
const KEY = 'hoi4dbg.focusAutostart';

export function autostartEnabled() {
  try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
}

export function setAutostartEnabled(on) {
  try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* preference only */ }
}

/** Message after an attempt ({ text, kind } or null); `seen` keeps manual notices to one per focus. */
export function autostartMessage(res, seen = new Set()) {
  if (!res) return null;
  if (res.state === 'started') return { text: `Focus started: ${res.name} (${res.days} days)`, kind: 'ok' };
  if (res.state === 'manual' && !seen.has(res.focus)) {
    seen.add(res.focus);
    return { text: `Next in your plan: ${res.name} - ${res.reason}`, kind: 'warn' };
  }
  return null;
}

/** Runs every AUTOSTART_POLL_MS while enabled; onResult(res | null, error | null). */
export function startFocusAutostart(api, onResult) {
  let busy = false;
  const tick = async () => {
    if (busy || !autostartEnabled()) return;
    busy = true;
    try {
      onResult(await api.post('/api/live/focus/autostart', { confirm_local: true }), null);
    } catch (err) {
      onResult(null, err);
    } finally {
      busy = false;
    }
  };
  const timer = setInterval(tick, AUTOSTART_POLL_MS);
  return () => clearInterval(timer);
}
