// Optional auto-sort of the player's construction queue: civilian factories closest to completion first
// (backend: /api/live/construction/sort, a LOCAL game memory write, single player only). Off by default.

export const SORT_POLL_MS = 3000;
const KEY = 'hoi4dbg.civSort';

export function sortEnabled() {
  try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
}

export function setSortEnabled(on) {
  try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* preference only */ }
}

/** "Moved 3 lines: Krasnoyarsk 87% to 1, ..." - toast after a sort (null when nothing moved). */
export function sortMessage(res) {
  if (!res?.applied || !res.moved?.length) return null;
  const civ = res.moved.filter((m) => m.building === 'industrial_complex');
  const list = civ.slice(0, 3).map((m) => `${m.state_name ?? `state ${m.location}`} ${Math.floor((m.progress ?? 0) * 100)}% → ${m.to}`);
  return `Construction queue sorted (${res.moved.length} moved)${list.length ? `: ${list.join(', ')}` : ''}`;
}

/** Runs the sort every SORT_POLL_MS while enabled; onResult(res | null, error | null) after each attempt. */
export function startConstructionSort(api, onResult) {
  let busy = false;
  const tick = async () => {
    if (busy || !sortEnabled()) return;
    busy = true;
    try {
      const res = await api.post('/api/live/construction/sort', { confirm_local: true });
      onResult(res, null);
    } catch (err) {
      onResult(null, err);
    } finally {
      busy = false;
    }
  };
  const timer = setInterval(tick, SORT_POLL_MS);
  return () => clearInterval(timer);
}
