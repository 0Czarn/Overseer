// Shared refresh for data tiles. Every tile has its own mode switch [Live | On refresh]:
// - Live: the tile re-reads its data every LIVE_MS (paused while the window is hidden);
// - On refresh: the data changes only when the ↻ button of the tile is clicked.
// The choice is remembered per tile (browser storage of this app). A tile is redrawn only when its data changed,
// so an open tooltip or an expanded list stays as it is between identical reads.
import { h, notice } from './dom.js';

export const LIVE_MS = 2000;
export const MODES = { live: 'Live', manual: 'On refresh' };
const MODE_KEY = 'hoi4dbg.tileMode.';

/** Stable key of a response for change detection (read time stamps are ignored). */
export function dataKey(data) {
  return JSON.stringify(data, (k, v) => (k === 'read_at' ? undefined : v));
}

/** Remembered mode of tile `id` ('live' unless 'manual' was chosen). */
export function readMode(storage, id) {
  try {
    return storage?.getItem(MODE_KEY + id) === 'manual' ? 'manual' : 'live';
  } catch {
    return 'live';
  }
}

export function writeMode(storage, id, mode) {
  try {
    storage?.setItem(MODE_KEY + id, mode);
  } catch { /* preference only */ }
}

function storage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Mode switch + ↻ button of one tile. run(force) reads the data; it is called every LIVE_MS in Live mode and on
 * a ↻ click in On refresh mode. Returns { el, button, mode(), stop }.
 */
export function refreshControl(id, title, run) {
  let mode = readMode(storage(), id);
  let timer = null;
  const button = h('button', { class: 'hoi-refresh', type: 'button', title: 'Refresh now', 'aria-label': `Refresh ${title}` }, '↻');
  button.addEventListener('click', () => run(true));
  const choices = Object.entries(MODES).map(([value, label]) => {
    const b = h('button', { type: 'button', class: 'hoi-mode-btn', 'data-mode': value,
      title: value === 'live' ? `Re-read every ${LIVE_MS / 1000} s` : 'Re-read only with the ↻ button' }, label);
    b.addEventListener('click', () => set(value));
    return b;
  });
  const group = h('span', { class: 'hoi-mode', role: 'group', 'aria-label': `${title}: update mode` }, choices);

  function apply() {
    choices.forEach((b) => {
      const on = b.dataset.mode === mode;
      b.classList.toggle('hoi-mode-on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    button.hidden = mode === 'live';
    clearInterval(timer);
    timer = mode === 'live' ? setInterval(() => { if (!document.hidden) run(false); }, LIVE_MS) : null;
  }

  function set(value) {
    if (value === mode) return;
    mode = value;
    writeMode(storage(), id, mode);
    apply();
    if (mode === 'live') run(false);
  }

  apply();
  return { el: h('span', { class: 'hoi-mode-wrap' }, group, button), button, mode: () => mode,
    stop: () => clearInterval(timer) };
}

/**
 * Tile with header (title, source line, mode switch, ↻) whose content comes from `url`.
 * render(body, res) fills the body; liveParts(res) names the parts read from game memory. The header shows
 * "game memory · read <time>" (green) when any part is live, else "save <file> · read <time>"; the details
 * (live parts, save file, in-game date) are in the tooltip of that line.
 * Returns { el, refresh, stop }.
 */
export function livePanel(ctx, { title, url, render, liveParts, cls = '', unavailable = title, id = title }) {
  const body = h('div', { class: 'live-panel-body' }, h('span', { class: 'muted' }, `Reading ${title.toLowerCase()}…`));
  const source = h('span', { class: 'hoi-status' });
  let last = null;
  let busy = false;
  let stopped = false;

  async function refresh(force = false) {
    if (busy || stopped) return;
    busy = true;
    control.button.classList.add('hoi-refresh-busy');
    try {
      const res = await ctx.api.get(url);
      if (stopped) return;
      const key = dataKey(res.data ?? res.note);
      if (force || key !== last) {
        last = key;
        render(body, res);
      }
      const line = sourceLine(res, liveParts?.(res) ?? [], new Date().toLocaleTimeString());
      source.textContent = line.text;
      source.title = line.title;
      source.className = `hoi-status ${line.live ? 'hoi-status-on' : ''}`.trim();
    } catch (err) {
      if (!stopped) body.replaceChildren(notice('warn', `${unavailable} unavailable: ${err.message}`));
    } finally {
      busy = false;
      control.button.classList.remove('hoi-refresh-busy');
    }
  }

  const control = refreshControl(id, title, refresh);
  refresh(true);
  const el = h('section', { class: `hoi-panel ${cls}`.trim() },
    h('div', { class: 'hoi-head' }, h('span', { class: 'hoi-head-title' }, title),
      h('span', { class: 'hoi-head-right' }, source, control.el)),
    body);
  return { el, refresh, stop: () => { stopped = true; control.stop(); } };
}

/** Header line of a tile: { text, title, live } - see livePanel. */
export function sourceLine(res, live, time) {
  if (!res.data?.file) {   // game memory only (no save behind it)
    return live.length ? { text: `game memory · read ${time}`, title: `LIVE: ${live.join(', ')}`, live: true }
      : { text: '', title: '', live: false };
  }
  return { text: live.length ? `game memory · read ${time}` : `save ${res.data.file.name} · read ${time}`,
    title: saveSource(res, live), live: live.length > 0 };
}

/** "file · in-game date" of a save-based response, with LIVE parts named (tooltip of the header line). */
export function saveSource(res, live = []) {
  const d = res.data;
  if (!d?.file) return '';
  const date = d.in_game_date ? ` · ${d.in_game_date.text}` : '';
  return `${live.length ? `LIVE: ${live.join(', ')} · ` : ''}save ${d.file.name}${date}`;
}
