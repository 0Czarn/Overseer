// Optional auto-sort of the player's construction queue: civilian OR military factories closest to completion first
// (backend: /api/live/construction/sort, a LOCAL game memory write, single player only). Off by default; the two
// switches exclude each other (one mode is kept).

export const SORT_POLL_MS = 3000;
const KEY = 'hoi4dbg.constructionSort';   // 'civ' | 'mil' | absent
const OLD_KEY = 'hoi4dbg.civSort';        // before military factories: '1' = civilian

/** The auto-sort mode: 'civ', 'mil' or null (off). */
export function sortMode() {
  try {
    const mode = localStorage.getItem(KEY);
    if (mode === 'civ' || mode === 'mil') return mode;
    return localStorage.getItem(OLD_KEY) === '1' ? 'civ' : null;
  } catch { return null; }
}

export function setSortMode(mode) {
  try {
    if (mode === 'civ' || mode === 'mil') localStorage.setItem(KEY, mode); else localStorage.removeItem(KEY);
    localStorage.removeItem(OLD_KEY);
  } catch { /* preference only */ }
}

export const sortEnabled = () => sortMode() !== null;

/** "Moved 3 lines: Krasnoyarsk 87% to 1, ..." - toast after a sort (null when nothing moved). */
export function sortMessage(res) {
  if (!res?.applied || !res.moved?.length) return null;
  const civ = res.moved.filter((m) => m.building === (res.kind === 'mil' ? 'arms_factory' : 'industrial_complex'));
  const list = civ.slice(0, 3).map((m) => `${m.state_name ?? `state ${m.location}`} ${Math.floor((m.progress ?? 0) * 100)}% → ${m.to}`);
  return `Construction queue sorted, ${res.kind === 'mil' ? 'military' : 'civilian'} factories first (${res.moved.length} moved)`
    + `${list.length ? `: ${list.join(', ')}` : ''}`;
}

/** Runs the sort every SORT_POLL_MS while enabled; onResult(res | null, error | null) after each attempt. */
export function startConstructionSort(api, onResult) {
  let busy = false;
  const tick = async () => {
    const mode = sortMode();
    if (busy || !mode) return;
    busy = true;
    try {
      const res = await api.post('/api/live/construction/sort', { confirm_local: true, kind: mode });
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
