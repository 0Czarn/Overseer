// Game summary - campaign map (2026-10-21, user's request): the game's own map (game files and the mods it runs with,
// backend campaign_map.py) coloured by the owner or controller of every state on a recorded day, played back day by
// day. The backend sends the map once as a PNG whose pixels hold the state id (red << 8 | green; blue = land / sea /
// lake / land without a state) and the recorded changes of owners and controllers (ic_history.add_map).
import { card, h, notice } from '../lib/dom.js';
import { dayText } from '../lib/linechart.js';
import { numberLocale } from '../lib/options.js';
import { zoomable } from '../lib/zoom.js';
import { dragToScroll } from './research.js';

const LAND = 255;
const SEA = 0;
const LAKE = 1;
const COLORS = { sea: [24, 38, 58], lake: [36, 58, 84], empty: [70, 68, 64], unknown: [110, 108, 104], border: [12, 12, 12] };
const SPEEDS = [['Slow', 600], ['Normal', 250], ['Fast', 80]];
const PREFS_KEY = 'hoi4dbg.summaryMap';
const rasters = new Map();   // map key -> {width, height, ids: Uint16Array, kind: Uint8Array}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {}; } catch { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* preference only */ }
}

/** [r, g, b] of "#rrggbb" (unknown: grey). */
export function rgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex ?? '');
  if (!m) return COLORS.unknown;
  const n = parseInt(m[1], 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

/** {state id: [owner, controller]} on recorded row `index`: from the last full row before it, its changes on top. */
export function statesAt(rows, index) {
  let start = 0;
  for (let i = Math.min(index, rows.length - 1); i >= 0; i--) if (rows[i].full) { start = i; break; }
  const out = {};
  for (let i = start; i <= index && i < rows.length; i++) Object.assign(out, rows[i].s);
  return out;
}

/** Index of the last map row on or before day `t` (-1: none). */
export function rowAt(rows, t) {
  let found = -1;
  for (let i = 0; i < rows.length && rows[i].t <= t; i++) found = i;
  return found;
}

/** Countries by number of states owned and controlled on a day: [{tag, owned, controlled, vp}], most first. */
export function standings(states, vps = {}) {
  const out = new Map();
  const row = (tag) => { if (!out.has(tag)) out.set(tag, { tag, owned: 0, controlled: 0, vp: 0 }); return out.get(tag); };
  for (const [sid, [owner, controller]] of Object.entries(states)) {
    if (owner) row(owner).owned += 1;
    if (controller) { row(controller).controlled += 1; row(controller).vp += vps[sid] ?? 0; }
  }
  return [...out.values()].sort((a, b) => b.controlled - a.controlled || b.owned - a.owned);
}

async function decode(png) {
  const img = new Image();
  img.src = png;
  await img.decode();
  const canvas = document.createElement('canvas');
  canvas.width = img.width;
  canvas.height = img.height;
  const g = canvas.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  const px = g.getImageData(0, 0, img.width, img.height).data;
  const n = img.width * img.height;
  const ids = new Uint16Array(n);
  const kind = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    ids[i] = (px[4 * i] << 8) | px[4 * i + 1];
    kind[i] = px[4 * i + 2];
  }
  return { width: img.width, height: img.height, ids, kind };
}

/** The section: el, update(gameId) - call it whenever the summary has read its campaign again. */
export function mapSection(ctx) {
  const prefs = { mode: 'owner', speed: 250, ...loadPrefs() };
  const body = h('div', { class: 'gs-map' }, h('p', { class: 'muted' }, 'Choose a campaign above.'));
  const el = card('Campaign map', body, { cls: 'gs-map-card' });
  let gid = null;
  let data = null;      // the backend's answer without the PNG
  let raster = null;
  let index = -1;       // map row shown
  let follow = true;    // stay on the newest day while it is recorded
  let timer = null;
  let canvas = null;
  let image = null;
  let tip = null;
  let dateLabel = null;
  let slider = null;
  let legend = null;
  let playBtn = null;
  let busy = false;
  let current = {};     // states of the day shown
  let vps = {};         // victory points of each state
  let controls = null;

  function colorTable(states) {
    const size = 65536;
    const fill = new Uint8Array(size * 3);       // the colour of each state id
    const stripe = new Uint8Array(size * 3);     // the occupier's colour (owner mode)
    const occupied = new Uint8Array(size);
    const country = new Uint16Array(size);       // a number per shown country (borders)
    const numbers = new Map();
    const colour = (tag) => rgb(data.colors[tag]);
    for (const [sid, [owner, controller]] of Object.entries(states)) {
      const id = Number(sid);
      const shown = prefs.mode === 'controller' ? controller : owner;
      const c = shown ? colour(shown) : COLORS.empty;
      fill.set(c, id * 3);
      if (!numbers.has(shown)) numbers.set(shown, numbers.size + 1);
      country[id] = numbers.get(shown);
      if (prefs.mode === 'owner' && controller && owner && controller !== owner) {
        occupied[id] = 1;
        stripe.set(colour(controller), id * 3);
      }
    }
    return { fill, stripe, occupied, country };
  }

  function draw() {
    if (!raster || !data || !canvas) return;
    const { width, height, ids, kind } = raster;
    current = index >= 0 ? statesAt(data.rows, index) : {};
    const t = colorTable(current);
    const px = image.data;
    const [sr, sg, sb] = COLORS.sea;
    const [lr, lg, lb] = COLORS.lake;
    const [er, eg, eb] = COLORS.empty;
    const [br, bg, bb] = COLORS.border;
    for (let y = 0, i = 0; y < height; y++) {
      for (let x = 0; x < width; x++, i++) {
        const k = kind[i];
        const p = 4 * i;
        px[p + 3] = 255;
        if (k !== LAND) {
          if (k === SEA) { px[p] = sr; px[p + 1] = sg; px[p + 2] = sb; } else if (k === LAKE) { px[p] = lr; px[p + 1] = lg; px[p + 2] = lb; } else { px[p] = er; px[p + 1] = eg; px[p + 2] = eb; }
          continue;
        }
        const id = ids[i];
        const own = t.country[id];
        const left = x > 0 && kind[i - 1] === LAND ? t.country[ids[i - 1]] : own;
        const up = y > 0 && kind[i - width] === LAND ? t.country[ids[i - width]] : own;
        if (left !== own || up !== own) { px[p] = br; px[p + 1] = bg; px[p + 2] = bb; continue; }
        if (!own) { px[p] = er; px[p + 1] = eg; px[p + 2] = eb; continue; }
        const src = t.occupied[id] && ((x + y) % 8) < 3 ? t.stripe : t.fill;
        const o = id * 3;
        px[p] = src[o]; px[p + 1] = src[o + 1]; px[p + 2] = src[o + 2];
      }
    }
    canvas.getContext('2d').putImageData(image, 0, 0);
    const row = data.rows[index];
    dateLabel.textContent = row ? dayText(row.t) : '—';
    slider.value = String(Math.max(0, index));
    const top = standings(current, vps);
    const fmt = (v) => v.toLocaleString(numberLocale(), { maximumFractionDigits: 0 });
    legend.replaceChildren(...top.slice(0, 14).map((s) => h('span', { class: 'gs-map-legend-item',
      title: `${data.names[s.tag] ?? s.tag}: ${s.owned} states owned, ${s.controlled} controlled, ${fmt(s.vp)} victory points` },
    h('span', { class: 'gs-map-swatch', style: { background: data.colors[s.tag] ?? '#6e6c68' } }),
    `${s.tag} ${s.controlled}`)));
  }

  function hover(ev) {
    if (!raster) return;
    const r = canvas.getBoundingClientRect();
    const x = Math.floor(((ev.clientX - r.left) / r.width) * raster.width);
    const y = Math.floor(((ev.clientY - r.top) / r.height) * raster.height);
    const i = y * raster.width + x;
    if (x < 0 || y < 0 || x >= raster.width || y >= raster.height || raster.kind[i] !== LAND) { tip.hidden = true; return; }
    const sid = raster.ids[i];
    const [owner, controller] = current[sid] ?? [];
    const state = data.states[sid] ?? { name: `State ${sid}`, vp: 0 };
    const name = (tag) => (tag ? `${data.names[tag] ?? tag} (${tag})` : '—');
    tip.replaceChildren(h('strong', null, state.name), h('div', null, `Owner: ${name(owner)}`),
      controller && controller !== owner ? h('div', { class: 'bad-text' }, `Controller: ${name(controller)}`) : null,
      state.vp ? h('div', { class: 'muted' }, `Victory points: ${state.vp}`) : null);
    tip.hidden = false;
    const box = canvas.parentElement.parentElement.getBoundingClientRect();
    tip.style.left = `${Math.min(ev.clientX - box.left + 14, box.width - 220)}px`;
    tip.style.top = `${ev.clientY - box.top + 14}px`;
  }

  function stop() {
    clearInterval(timer);
    timer = null;
    if (playBtn) playBtn.textContent = '▶ Play';
  }

  function play() {
    if (timer) { stop(); return; }
    if (index >= data.rows.length - 1) index = 0;
    follow = false;
    playBtn.textContent = '❚❚ Pause';
    timer = setInterval(() => {
      if (index >= data.rows.length - 1) { stop(); follow = true; return; }
      index += 1;
      draw();
    }, prefs.speed);
  }

  function buildCanvas() {
    canvas = h('canvas', { class: 'gs-map-canvas', width: raster.width, height: raster.height });
    image = canvas.getContext('2d').createImageData(raster.width, raster.height);
    tip = h('div', { class: 'gs-map-tip', hidden: true });
    const view = h('div', { class: 'gs-map-scroll' });
    try {   // the whole world the first time
      if (!localStorage.getItem('hoi4dbg.zoom.campaign-map')) localStorage.setItem('hoi4dbg.zoom.campaign-map', String(Math.max(0.25, Math.min(1, 1000 / raster.width))));
    } catch { /* preference only */ }
    const { toolbar, sizer } = zoomable('campaign-map', view, canvas, raster.width, raster.height);
    view.append(sizer);
    dragToScroll(view);
    canvas.addEventListener('mousemove', hover);
    canvas.addEventListener('mouseleave', () => { tip.hidden = true; });
    dateLabel = h('strong', { class: 'gs-map-date' });
    slider = h('input', { type: 'range', class: 'gs-map-slider', min: 0, max: Math.max(0, data.rows.length - 1), value: index,
      'aria-label': 'Day', oninput: (e) => { stop(); index = Number(e.target.value); follow = index === data.rows.length - 1; draw(); } });
    playBtn = h('button', { class: 'btn btn-small', onclick: play }, timer ? '❚❚ Pause' : '▶ Play');
    controls = h('span', { class: 'gs-map-options' });
    legend = h('div', { class: 'gs-map-legend' });
    body.replaceChildren(
      h('div', { class: 'gs-map-controls' }, playBtn, dateLabel, slider, controls),
      h('div', { class: 'gs-map-wrap' }, toolbar, view, tip), legend,
      h('p', { class: 'hint' }, 'The game\'s map with the mods it runs with. Owner and controller of every state, recorded once a '
        + 'game day from game memory (from 2026-10-21) - states, not provinces: a state shows its controller even while a '
        + 'part of it is still fought over. Hover a state for its name; wheel: zoom, drag: move.'));
    renderControls();
  }

  function renderControls() {
    const seg = (items, value, onPick) => h('div', { class: 'gs-seg' }, items.map(([v, label]) =>
      h('button', { class: `gs-seg-btn ${v === value ? 'gs-seg-on' : ''}`, onclick: () => onPick(v) }, label)));
    controls.replaceChildren(
      seg([['owner', 'Owner (occupied: stripes)'], ['controller', 'Controller']], prefs.mode,
        (v) => { prefs.mode = v; savePrefs(prefs); renderControls(); draw(); }),
      seg(SPEEDS.map(([l, ms]) => [ms, l]), prefs.speed, (v) => {
        prefs.speed = v; savePrefs(prefs); renderControls();
        if (timer) { stop(); play(); }
      }));
  }

  async function update(id) {
    if (busy) return;
    if (!id) { gid = null; stop(); body.replaceChildren(h('p', { class: 'muted' }, 'Choose a campaign above.')); return; }
    busy = true;
    try {
      const changed = id !== gid;
      const res = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(id)}/map`)).data;
      if (!rasters.has(res.map.key)) {
        const full = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(id)}/map?raster=1`)).data;
        rasters.set(res.map.key, await decode(full.map.png));
      }
      const fresh = rasters.get(res.map.key);
      const rebuilt = changed || fresh !== raster || !canvas;
      if (changed) { stop(); follow = true; }
      gid = id;
      data = res;
      raster = fresh;
      if (!data.rows.length) {
        canvas = null;
        body.replaceChildren(notice('info', 'No map recorded for this campaign yet - the owner and controller of every state are '
          + 'recorded once a game day from 2026-10-21 (keep the app open while you play).'));
        return;
      }
      if (follow && !timer) index = data.rows.length - 1;
      index = Math.min(index, data.rows.length - 1);
      vps = Object.fromEntries(Object.entries(data.states).map(([k, v]) => [k, v.vp]));
      if (rebuilt) buildCanvas();
      slider.max = String(data.rows.length - 1);
      if (!timer) draw();
    } catch (err) {
      canvas = null;
      body.replaceChildren(notice('warn', `Campaign map unavailable: ${err.message}`));
    } finally {
      busy = false;
    }
  }

  /** {png, date} of the map shown (half size, for the report), null without one. */
  function snapshot() {
    if (!canvas || index < 0) return null;
    const small = document.createElement('canvas');
    small.width = Math.round(canvas.width / 2);
    small.height = Math.round(canvas.height / 2);
    small.getContext('2d').drawImage(canvas, 0, 0, small.width, small.height);
    return { png: small.toDataURL('image/png'), date: dayText(data.rows[index].t) };
  }

  return { el, update, stop, snapshot };
}
