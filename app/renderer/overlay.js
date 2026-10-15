// The overlay window (desktop.cjs): the player's chosen values over the game, read from game memory
// (/api/live/overlay). Which values, the transparency and the reading pace come from Options (same localStorage).
import { createApi } from './lib/api.js';
import { h } from './lib/dom.js';
import { statIcon } from './lib/icons.js';
import { OVERLAY_FIELDS, loadOptions, numberLocale, refreshMs, reloadOptions } from './lib/options.js';
import { tr } from './lib/i18n.js';

const api = createApi();
const rows = document.getElementById('rows');
const title = document.getElementById('title');
const POLL_MS = 2000;

/** Text of one overlay value. */
export function overlayText(field, data) {
  const fmt = (v, digits) => v.toLocaleString(numberLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (field === 'date') return data.date ?? '—';
  if (field === 'ic') {
    const ic = data.ic;
    return ic ? `${fmt(ic.mil, 0)} / ${fmt(ic.civ, 0)} / ${fmt(ic.nav, 0)}` : '—';
  }
  const v = data.values?.[field];
  if (!Number.isFinite(v)) return '—';
  if (field === 'stability' || field === 'war_support') return `${fmt(v * 100, 1)}%`;
  if (field === 'fuel') return fmt(v, 0);
  return fmt(v, 1);
}

function draw(data) {
  const o = loadOptions();
  document.documentElement.style.setProperty('--ov-alpha', String(o.overlayOpacity / 100));
  title.textContent = data ? `${data.tag ?? ''} · ${data.date ?? ''}` : 'THE OVERSEER';
  if (!data) return;
  rows.replaceChildren(...o.overlayFields.map((f) => h('div', { class: 'ov-row', title: f === 'ic' ? 'Military / civilian / naval IC a day' : '' },
    f === 'ic' ? h('img', { src: 'assets/texticons/factory_output_modifier_texticon.png', alt: '' }) : statIcon(f),
    h('span', { class: 'ov-label' }, tr(OVERLAY_FIELDS[f])), h('span', { class: 'ov-value' }, overlayText(f, data)))));
}

async function tick() {
  try {
    draw((await api.get('/api/live/overlay')).data);
  } catch (err) {
    draw(null);
    rows.replaceChildren(h('span', { class: 'ov-muted' }, err.message));
  }
  setTimeout(tick, refreshMs(POLL_MS));
}

document.getElementById('close').addEventListener('click', () => globalThis.hoi4dbg?.setOverlay(false));
window.addEventListener('storage', () => reloadOptions());   // options changed in the main window: next reading shows them
tick();
