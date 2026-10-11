// Shared refresh for data tiles: a manual ↻ button per tile and the app-wide interval chosen in the top bar
// (the app dispatches REFRESH_EVENT on every tick). A tile is redrawn only when its data changed, so an open
// tooltip or an expanded list stays as it is between identical reads.
import { h, notice } from './dom.js';

export const REFRESH_EVENT = 'hoi4dbg:refresh';
export const REFRESH_CHOICES = [0, 5, 10, 30, 60];

/** Stable key of a response for change detection (read time stamps are ignored). */
export function dataKey(data) {
  return JSON.stringify(data, (k, v) => (k === 'read_at' ? undefined : v));
}

/**
 * Tile with header (title, source line, ↻ button) whose content comes from `url`.
 * render(body, res) fills the body; describe(res) returns the source text shown in the header.
 * Returns { el, refresh, stop }.
 */
export function livePanel(ctx, { title, url, render, describe, cls = '', unavailable = title }) {
  const body = h('div', { class: 'live-panel-body' }, h('span', { class: 'muted' }, `Reading ${title.toLowerCase()}…`));
  const source = h('span', { class: 'hoi-status' });
  const button = h('button', { class: 'hoi-refresh', type: 'button', title: 'Refresh now', 'aria-label': `Refresh ${title}` }, '↻');
  let last = null;
  let busy = false;
  let stopped = false;

  async function refresh(force = false) {
    if (busy || stopped) return;
    busy = true;
    button.classList.add('hoi-refresh-busy');
    try {
      const res = await ctx.api.get(url);
      if (stopped) return;
      const key = dataKey(res.data ?? res.note);
      if (force || key !== last) {
        last = key;
        render(body, res);
      }
      source.textContent = describe?.(res) ?? '';
      source.title = `Checked ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      if (!stopped) body.replaceChildren(notice('warn', `${unavailable} unavailable: ${err.message}`));
    } finally {
      busy = false;
      button.classList.remove('hoi-refresh-busy');
    }
  }

  button.addEventListener('click', () => refresh(true));
  const onTick = () => refresh(false);
  window.addEventListener(REFRESH_EVENT, onTick);
  refresh(true);
  const el = h('section', { class: `hoi-panel ${cls}`.trim() },
    h('div', { class: 'hoi-head' }, h('span', { class: 'hoi-head-title' }, title),
      h('span', { class: 'hoi-head-right' }, source, button)),
    body);
  return { el, refresh, stop: () => { stopped = true; window.removeEventListener(REFRESH_EVENT, onTick); } };
}

/** "file · in-game date" source line of a save-based response, with LIVE parts named. */
export function saveSource(res, live = []) {
  const d = res.data;
  if (!d?.file) return '';
  const date = d.in_game_date ? ` · ${d.in_game_date.text}` : '';
  return `${live.length ? `LIVE: ${live.join(', ')} · ` : ''}save ${d.file.name}${date}`;
}
