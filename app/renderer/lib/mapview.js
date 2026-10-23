// The game's map in a canvas (Game summary campaign map, State Editor - 2026-10-22): the backend sends the province map
// of the game and its mods once (campaign_map.py: a PNG whose pixels hold the province id - red << 8 | green - and blue
// = land / sea / lake) with the state of every province; the caller colours the states. Borders of countries, states
// and provinces, a highlighted state, hover tooltip and click, wheel zoom and drag (lib/zoom.js).
// 2026-10-23 (user's request "a more detailed campaign map"): the map at the game's full size, a second canvas on top
// for names - of countries / groups (placed on the largest connected piece of their land, sized to it) and of cities
// (victory point provinces, more of them the closer the zoom); city names keep their size on screen while zooming.
// 2026-10-23 (user's request "sharp edges when zoomed in"): a canvas of the size of the view on top draws the names at
// the screen's resolution and, from VECTOR_ZOOM, the map itself from the province outlines (campaign_map.borders:
// smoothed lines, the same for both provinces of a border) instead of the enlarged pixels. Terrain (campaign_map.terrain):
// the relief blended soft-light over the colours and the rivers as lines, wider ones from further away.
// 2026-10-23 (user's request "deserts, hills, mountains, swamps, forests visible"): the terrain of every province
// (definition.csv) as a light tint and, from TYPE_SYMBOLS_ZOOM, symbols of a constant size on screen.
import { h } from './dom.js';
import { zoomable } from './zoom.js';
import { dragToScroll } from '../views/research.js';

export const LAND = 255;
export const SEA = 0;
export const LAKE = 1;
export const COLORS = { sea: [24, 38, 58], lake: [36, 58, 84], empty: [70, 68, 64], unknown: [110, 108, 104], border: [12, 12, 12],
  highlight: [255, 255, 255] };
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;
const VECTOR_ZOOM = 1;      // from this zoom the map is drawn from its outlines
const NO_STATE = 2;
const loaded = new Map();   // map key -> Promise of the decoded map
const loadedBorders = new Map();   // map key -> Promise of the decoded outlines
const loadedTerrain = new Map();   // map key -> Promise of {relief: image, rivers}
const RIVER = 'rgba(86, 140, 196, .9)';
const TYPE_SYMBOLS_ZOOM = 0.45;
// province terrain: [tint, draw(g) of a 16 x 16 symbol tile]; plains (and unknown) stay as they are
const tree = (color) => (g, x, y) => {
  g.fillStyle = color; g.beginPath(); g.moveTo(x, y - 4); g.lineTo(x + 3, y + 2); g.lineTo(x - 3, y + 2); g.closePath(); g.fill();
  g.fillRect(x - 0.5, y + 2, 1, 2);
};
export const TERRAIN_STYLES = {
  forest: ['rgba(30, 110, 40, .2)', (g) => { const t = tree('rgba(18, 70, 26, .85)'); t(g, 4.5, 6); t(g, 12, 13); }],
  jungle: ['rgba(10, 95, 55, .28)', (g) => { const t = tree('rgba(8, 60, 32, .9)'); t(g, 4, 5); t(g, 12, 6); t(g, 8, 13); }],
  hills: ['rgba(160, 115, 60, .18)', (g) => {
    g.strokeStyle = 'rgba(85, 52, 16, .95)'; g.lineWidth = 1.6;
    g.beginPath(); g.arc(5, 8, 3.5, Math.PI, 0); g.stroke(); g.beginPath(); g.arc(12.5, 15, 3.5, Math.PI, 0); g.stroke();
  }],
  mountain: ['rgba(235, 235, 235, .2)', (g) => {
    g.lineJoin = 'round';
    for (const [x, y] of [[5, 8], [12.5, 15]]) {
      g.beginPath(); g.moveTo(x - 4.5, y); g.lineTo(x, y - 6); g.lineTo(x + 4.5, y);
      g.fillStyle = 'rgba(240, 240, 240, .75)'; g.fill(); g.strokeStyle = 'rgba(40, 40, 40, .85)'; g.lineWidth = 1; g.stroke();
    }
  }],
  desert: ['rgba(245, 215, 120, .26)', (g) => {
    g.fillStyle = 'rgba(150, 110, 40, .85)';
    for (const [x, y] of [[3, 4], [11, 3], [7, 9], [14, 11], [3, 14], [10, 15]]) g.fillRect(x, y, 1.9, 1.9);
  }],
  marsh: ['rgba(50, 150, 150, .22)', (g) => {
    g.strokeStyle = 'rgba(20, 95, 110, .9)'; g.lineWidth = 1.1;
    g.beginPath(); g.moveTo(1, 6); g.lineTo(7, 6); g.moveTo(9, 13); g.lineTo(15, 13);
    g.moveTo(4, 6); g.lineTo(4, 3); g.moveTo(12, 13); g.lineTo(12, 10); g.stroke();
  }],
  urban: ['rgba(70, 70, 70, .22)', (g) => {
    g.fillStyle = 'rgba(45, 45, 45, .85)'; g.fillRect(3, 4, 4, 4); g.fillRect(10, 11, 4, 4); g.fillRect(9, 3, 2.5, 2.5);
  }],
};

/** A small canvas of a terrain's look (the map's legend), null for one without a style. */
export function terrainSwatch(name, size = 18) {
  const style = TERRAIN_STYLES[name];
  if (!style || typeof document === 'undefined') return null;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  g.fillStyle = '#6b6a66';
  g.fillRect(0, 0, size, size);
  g.fillStyle = style[0];
  g.fillRect(0, 0, size, size);
  g.scale(size / 16, size / 16);
  style[1](g);
  return c;
}
// screen pixels and colours of the borders drawn from the outlines, the lowest first
const LINES = {
  province: [0.6, 'rgba(0, 0, 0, .3)'],
  coast: [0.9, 'rgba(0, 0, 0, .5)'],
  state: [1, 'rgba(0, 0, 0, .6)'],
  country: [1.6, 'rgb(12, 12, 12)'],
  highlight: [2.2, 'rgb(255, 255, 255)'],
};
// lines whose width and opacity follow style.borderStrength (2026-10-23, user's request: a slider for the visibility
// of the state and province borders)
const SCALED = new Set(['province', 'state']);
export const BORDER_STRENGTH = [0.5, 4];

/** `colour` (rgba / rgb) with its opacity times `s` (up to 1). */
export function strengthen(colour, s) {
  const m = /^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/.exec(colour);
  return m ? `rgba(${m[1]}, ${m[2]}, ${m[3]}, ${Math.min(1, Number(m[4]) * s).toFixed(3)})` : colour;
}

/** The province outlines of campaign_map.encode_borders (base64): {width, height, arcs, start (first point of each
 * arc, arcs + 1), sides (provinces p, q of each arc), pts (x, y in map pixels), box (x0, y0, x1, y1 of each arc),
 * rings: Map province -> [[arc ref: i forwards, ~i backwards]], provBox: Map province -> [x0, y0, x1, y1]}. */
export function decodeBorders(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  if (String.fromCharCode(...bytes.subarray(0, 4)) !== 'OVB1') throw new Error('Unknown format of the map outlines');
  const buf = bytes.buffer;
  const [width, height, arcs, points, words] = new Uint32Array(buf, 4, 5);
  let at = 24;
  const start = new Uint32Array(buf, at, arcs + 1);
  at += 4 * (arcs + 1);
  const sides = new Uint16Array(buf, at, 2 * arcs);
  at += 4 * arcs;
  const half = new Uint16Array(buf, at, 2 * points);
  at += 4 * points;
  const ringWords = new Int32Array(buf, at, words);
  const pts = new Float32Array(2 * points);
  for (let i = 0; i < pts.length; i++) pts[i] = half[i] / 2;
  const box = new Float32Array(4 * arcs);
  for (let a = 0; a < arcs; a++) {
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
    for (let k = start[a]; k < start[a + 1]; k++) {
      const x = pts[2 * k];
      const y = pts[2 * k + 1];
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
    box[4 * a] = x0; box[4 * a + 1] = y0; box[4 * a + 2] = x1; box[4 * a + 3] = y1;
  }
  const rings = new Map();
  const provBox = new Map();
  for (let i = 0; i < words;) {
    const pid = ringWords[i++];
    const n = ringWords[i++];
    const list = [];
    const b = [Infinity, Infinity, -Infinity, -Infinity];
    for (let r = 0; r < n; r++) {
      const len = ringWords[i++];
      const ring = Array.from(ringWords.subarray(i, i + len));
      i += len;
      for (const ref of ring) {
        const a = 4 * (ref < 0 ? ~ref : ref);
        b[0] = Math.min(b[0], box[a]); b[1] = Math.min(b[1], box[a + 1]);
        b[2] = Math.max(b[2], box[a + 2]); b[3] = Math.max(b[3], box[a + 3]);
      }
      list.push(ring);
    }
    rings.set(pid, list);
    provBox.set(pid, b);
  }
  return { width, height, arcs, start, sides, pts, box, rings, provBox };
}

/** Adds arc `ref` of `outlines` (decodeBorders; backwards when < 0) to `path` (`move`: starting there), smoothed the
 * same way both ways: straight to the middle of its first segment, curves through the middles of the next ones (the
 * points are their control points), straight to its last point - both provinces of a border get the same line. */
export function traceArc(path, outlines, ref, move) {
  const a = ref < 0 ? ~ref : ref;
  const s = outlines.start[a];
  const e = outlines.start[a + 1] - 1;
  const P = outlines.pts;
  const at = (k) => 2 * (ref < 0 ? e - k : s + k);
  const n = e - s;
  let j = at(0);
  if (move) path.moveTo(P[j], P[j + 1]);
  if (n === 1) { j = at(1); path.lineTo(P[j], P[j + 1]); return; }
  let px = P[at(1)];
  let py = P[at(1) + 1];
  path.lineTo((P[j] + px) / 2, (P[j + 1] + py) / 2);
  for (let k = 2; k <= n; k++) {
    j = at(k);
    path.quadraticCurveTo(px, py, (px + P[j]) / 2, (py + P[j + 1]) / 2);
    px = P[j]; py = P[j + 1];
  }
  path.lineTo(px, py);
}

/** The outline of province `pid` (all its rings: holes are rings the other way round - non-zero fill). */
export function provincePath(outlines, pid, path = new Path2D()) {
  for (const ring of outlines.rings.get(pid) ?? []) {
    ring.forEach((ref, i) => traceArc(path, outlines, ref, i === 0));
    path.closePath();
  }
  return path;
}

/** Which border line arc `a` gets (LINES key or null): between land and the rest the coast, between land provinces of
 * different border groups a country border, the chosen state's outline, state and province borders when shown. */
export function borderKind(map, outlines, a, paint) {
  const p = outlines.sides[2 * a];
  const q = outlines.sides[2 * a + 1];
  const lp = map.provKind[p] === LAND;
  const lq = map.provKind[q] === LAND;
  if (lp !== lq) return 'coast';
  if (!lp) return null;
  const sp = map.provState[p] ?? 0;
  const sq = map.provState[q] ?? 0;
  const hl = paint.style.highlight;
  if (hl && sp !== sq && (sp === hl || sq === hl)) return 'highlight';
  if (paint.group[p] !== paint.group[q]) return 'country';
  if (sp !== sq && paint.style.states) return 'state';
  return paint.style.provinces ? 'province' : null;
}

/** [r, g, b] of "#rrggbb" (unknown: grey). */
export function rgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex ?? '');
  if (!m) return COLORS.unknown;
  const n = parseInt(m[1], 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

/** A colour darker (f < 1) or towards white (f > 1: 1 + the share of white). */
export function shade([r, g, b], f) {
  if (f <= 1) return [Math.round(r * f), Math.round(g * f), Math.round(b * f)];
  const w = f - 1;
  return [Math.round(r + (255 - r) * w), Math.round(g + (255 - g) * w), Math.round(b + (255 - b) * w)];
}

async function decode(png, provinceState, terrainTypes = [], provinceTerrain = []) {
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
  const pids = new Uint16Array(n);
  const kind = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    pids[i] = (px[4 * i] << 8) | px[4 * i + 1];
    kind[i] = px[4 * i + 2];
  }
  const provState = Uint16Array.from(provinceState);
  return { width: img.width, height: img.height, pids, kind, provState, terrainTypes, provTerrain: Uint8Array.from(provinceTerrain),
    ...measure(img.width, img.height, pids, kind, provState) };
}

/** Per province: pixel count, sums of x and y, bounding box (x0, y0, x1, y1); pairs [a, b] of neighbouring land states;
 * `adjacent`: the neighbouring land provinces of each province (fog of war); `provKind`: LAND, SEA, LAKE of each. */
export function measure(width, height, pids, kind, provState) {
  let top = 0;
  for (let i = 0; i < pids.length; i++) if (pids[i] > top) top = pids[i];
  const provKind = new Uint8Array(top + 1).fill(NO_STATE);
  for (let i = 0; i < pids.length; i++) provKind[pids[i]] = kind[i];
  provKind[0] = NO_STATE;
  const count = new Float64Array(top + 1);
  const sx = new Float64Array(top + 1);
  const sy = new Float64Array(top + 1);
  const box = new Int32Array((top + 1) * 4).fill(-1);
  const pairs = new Set();
  const pair = (a, b) => { if (a && b && a !== b) pairs.add(a < b ? a * 65536 + b : b * 65536 + a); };
  const provPairs = new Set();
  const provPair = (a, b) => { if (a !== b) provPairs.add(a < b ? a * 65536 + b : b * 65536 + a); };
  for (let y = 0, i = 0; y < height; y++) {
    for (let x = 0; x < width; x++, i++) {
      if (kind[i] !== LAND) continue;
      const p = pids[i];
      count[p] += 1; sx[p] += x; sy[p] += y;
      const b = 4 * p;
      if (box[b] < 0) { box[b] = x; box[b + 1] = y; box[b + 2] = x; box[b + 3] = y; } else {
        if (x < box[b]) box[b] = x;
        if (x > box[b + 2]) box[b + 2] = x;
        box[b + 3] = y;
      }
      const s = provState[p] ?? 0;
      if (x > 0 && kind[i - 1] === LAND) { pair(provState[pids[i - 1]] ?? 0, s); provPair(pids[i - 1], p); }
      if (y > 0 && kind[i - width] === LAND) { pair(provState[pids[i - width]] ?? 0, s); provPair(pids[i - width], p); }
    }
  }
  const adjacent = Array.from({ length: top + 1 }, () => []);
  for (const k of provPairs) {
    const a = Math.floor(k / 65536);
    const b = k % 65536;
    adjacent[a].push(b);
    adjacent[b].push(a);
  }
  return { prov: { count, sx, sy, box }, neighbours: [...pairs].map((k) => [Math.floor(k / 65536), k % 65536]), adjacent,
    provKind };
}

/** Land provinces seen from `own` (Set of province ids held by the country and its allies): those and their land
 * neighbours - an approximate fog of war (the game also counts intelligence, radar, air and sea). */
export function seenProvinces(map, own) {
  const seen = new Set(own);
  for (const p of own) for (const n of map.adjacent[p] ?? []) seen.add(n);
  return seen;
}

/** Division markers of a zoom: one per province and country key, or per state when zoomed out (< 0.5).
 * units: [{pid, key, color, count}] -> [{x, y, key, color, count}]. */
export function unitMarkers(map, units, z) {
  const perState = z < 0.5;
  const groups = new Map();
  for (const u of units) {
    const c = map.prov.count[u.pid];
    if (!c) continue;
    const where = perState ? `s${map.provState[u.pid]}` : `p${u.pid}`;
    const id = `${where}|${u.key}`;
    let g = groups.get(id);
    if (!g) { g = { key: u.key, color: u.color, count: 0, sx: 0, sy: 0, n: 0 }; groups.set(id, g); }
    g.count += u.count;
    g.sx += map.prov.sx[u.pid]; g.sy += map.prov.sy[u.pid]; g.n += c;
  }
  return [...groups.values()].map((g) => ({ x: g.sx / g.n, y: g.sy / g.n, key: g.key, color: g.color, count: g.count }));
}

/** Name labels of the land of each key: `keyOf(sid)` -> a key or null, `textOf(key)` -> its name or null. A key's land
 * splits into pieces of neighbouring states; the piece with the most victory points (`vpOf(sid)`: the capital, not the
 * larger colonies) gets the name, other pieces too when at least a quarter of the largest one. [{text, x, y, size}] in
 * map pixels (centre of the piece; the name fits its width and height), largest first. */
export function placeLabels(map, keyOf, textOf, vpOf = () => 0, minPixels = 600) {
  const { prov, provState, neighbours } = map;
  const states = new Map();   // sid -> {count, sx, sy, x0, y0, x1, y1}
  const grow = (into, count, sx, sy, x0, y0, x1, y1) => {
    into.count += count; into.sx += sx; into.sy += sy;
    into.x0 = Math.min(into.x0, x0); into.y0 = Math.min(into.y0, y0); into.x1 = Math.max(into.x1, x1); into.y1 = Math.max(into.y1, y1);
  };
  const empty = (extra) => ({ ...extra, count: 0, sx: 0, sy: 0, x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
  for (let p = 0; p < prov.count.length; p++) {
    const sid = provState[p];
    if (!prov.count[p] || !sid) continue;
    if (!states.has(sid)) states.set(sid, empty());
    const b = 4 * p;
    grow(states.get(sid), prov.count[p], prov.sx[p], prov.sy[p], prov.box[b], prov.box[b + 1], prov.box[b + 2], prov.box[b + 3]);
  }
  const keys = new Map();
  const parent = new Map();
  for (const sid of states.keys()) {
    const k = keyOf(sid);
    if (k == null) continue;
    keys.set(sid, k);
    parent.set(sid, sid);
  }
  const find = (a) => {
    while (parent.get(a) !== a) { parent.set(a, parent.get(parent.get(a))); a = parent.get(a); }
    return a;
  };
  for (const [a, b] of neighbours) {
    if (keys.has(a) && keys.get(a) === keys.get(b)) {
      const ra = find(a);
      const rb = find(b);
      if (ra !== rb) parent.set(ra, rb);
    }
  }
  const pieces = new Map();   // root state -> piece
  for (const [sid, key] of keys) {
    const s = states.get(sid);
    const root = find(sid);
    if (!pieces.has(root)) pieces.set(root, empty({ key, vp: 0 }));
    grow(pieces.get(root), s.count, s.sx, s.sy, s.x0, s.y0, s.x1, s.y1);
    pieces.get(root).vp += vpOf(sid) ?? 0;
  }
  const byKey = new Map();
  for (const pc of pieces.values()) {
    if (!byKey.has(pc.key)) byKey.set(pc.key, []);
    byKey.get(pc.key).push(pc);
  }
  const out = [];
  for (const [key, list] of byKey) {
    const text = textOf(key);
    if (!text) continue;
    list.sort((a, b) => b.count - a.count);
    const largest = list[0].count;
    const main = list.reduce((best, pc) => (pc.vp > best.vp && pc.count >= minPixels ? pc : best), list[0]);
    for (const pc of [main, ...list.filter((x) => x !== main)]) {
      if (pc.count < minPixels || (pc !== main && pc.count < largest / 4)) continue;
      const w = pc.x1 - pc.x0 + 1;
      const hgt = pc.y1 - pc.y0 + 1;
      // over ~80% of the piece's width at most, 40% of its height; a long name on narrow land gets smaller
      const size = Math.max(6, Math.min(hgt * 0.4, (w * 0.8) / (text.length * 0.72), Math.sqrt(pc.count) * 0.45, 140));
      out.push({ text, x: pc.sx / pc.count, y: pc.sy / pc.count, size });
    }
  }
  return out.sort((a, b) => b.size - a.size);
}

/** Centre of a province in map pixels, null when it has no land pixel. */
export function provinceCentre(map, pid) {
  const c = map.prov.count[pid];
  return c ? [map.prov.sx[pid] / c, map.prov.sy[pid] / c] : null;
}

/** The smallest victory points of the cities named at zoom `z` (Infinity: none). */
export function cityThreshold(z) {
  return z >= 1.5 ? 0 : z >= 0.8 ? 3 : z >= 0.45 ? 10 : z >= 0.25 ? 25 : Infinity;
}

/** The game's map: {width, height, pids, kind, provState, prov, neighbours, info: {colors, names, states, cities, key}}
 * - read once per map key. */
export async function loadMap(ctx) {
  const info = (await ctx.api.get('/api/map')).data;
  if (!loaded.has(info.map.key)) {
    loaded.set(info.map.key, ctx.api.get('/api/map?raster=1').then((r) => decode(r.data.map.png, r.data.map.province_state,
      r.data.map.terrain_types ?? [], r.data.map.province_terrain ?? [])));
  }
  try {
    const decoded = await loaded.get(info.map.key);
    return { ...decoded, info: { ...info, key: info.map.key }, outlines: () => loadOutlines(ctx, info.map.key),
      terrain: () => loadTerrain(ctx, info.map.key) };
  } catch (err) {
    loaded.delete(info.map.key);
    throw err;
  }
}

/** The province outlines of map `key` (decodeBorders), read once; null when the backend cannot give them. */
function loadOutlines(ctx, key) {
  if (!loadedBorders.has(key)) {
    loadedBorders.set(key, ctx.api.get('/api/map/borders').then((r) => decodeBorders(r.data.borders)).catch(() => {
      loadedBorders.delete(key);   // tried again next time; the enlarged pixels meanwhile
      return null;
    }));
  }
  return loadedBorders.get(key);
}

/** Relief (a decoded image, null without heightmap) and rivers ([[width class, x0, y0, ...]]) of map `key`, read once;
 * null when the backend cannot give them. */
function loadTerrain(ctx, key) {
  if (!loadedTerrain.has(key)) {
    loadedTerrain.set(key, ctx.api.get('/api/map/terrain').then(async (r) => {
      let relief = null;
      if (r.data.relief) {
        relief = new Image();
        relief.src = r.data.relief.png;
        await relief.decode();
      }
      return { relief, rivers: r.data.rivers ?? [] };
    }).catch(() => {
      loadedTerrain.delete(key);
      return null;
    }));
  }
  return loadedTerrain.get(key);
}

/** Adds the line through `xy` (flat x, y list from `from`) to `path`, smoothed like traceArc. */
export function smoothLine(path, xy, from = 0) {
  const n = (xy.length - from) / 2 - 1;
  if (n < 1) return;
  path.moveTo(xy[from], xy[from + 1]);
  if (n === 1) { path.lineTo(xy[from + 2], xy[from + 3]); return; }
  let px = xy[from + 2];
  let py = xy[from + 3];
  path.lineTo((xy[from] + px) / 2, (xy[from + 1] + py) / 2);
  for (let j = from + 4; j < xy.length; j += 2) {
    path.quadraticCurveTo(px, py, (px + xy[j]) / 2, (py + xy[j + 1]) / 2);
    px = xy[j]; py = xy[j + 1];
  }
  path.lineTo(px, py);
}

/** The lowest railway level shown at zoom `z` (1..5). */
export function railThreshold(z) {
  return z < 0.3 ? 3 : z < 0.5 ? 2 : 1;
}

/** The smallest river width class shown at zoom `z` (rivers.bmp 3 narrow .. 11 wide). */
export function riverThreshold(z) {
  return z < 0.3 ? 9 : z < 0.6 ? 6 : 3;
}

/** A map view of `map` (loadMap): {el, draw(style), labels({names, cities}), at(event) -> {pid, sid} | null, canvas,
 * snapshot(scale) -> a canvas with the names, setTip(nodes, event), terrain({relief, rivers, types}) - what is shown}.
 * style: {fill(sid) -> [r, g, b] | null, stripe(sid) -> [r, g, b] | null (occupation stripes), group(sid) -> number
 * (country borders between different groups), states: true (state borders), provinces: true (province borders),
 * highlight: state id, overrides: Map province id -> {fill, stripe, group} (a province unlike its state: the front),
 * visible: Set of province ids or null (fog of war: the others greyed, without stripes)}.
 * labels: names [{text, x, y, size}] (placeLabels; map pixels, shown from 7 to 46 pixels on screen), cities [{text, x,
 * y, vp}] largest first (cityThreshold; one overlapping a name shown before is left out), units [{pid, key, color,
 * count}] (division markers, unitMarkers: per state when zoomed out), rails [[province a, province b, level]] (lines
 * between the provinces' centres, railThreshold), marks [{pid, kind: hub | port | fort | coastal, level}] (from 70%),
 * arrows [{from, to, color, count, attack}] (divisions moving / attacking into a neighbour), battles [{pid, attacker,
 * defender, share}] (crossed swords, a bar of the attacker's share).
 * `zoomId` remembers the zoom level. */
export function mapView(map, zoomId, { onHover, onClick } = {}) {
  const { width, height, pids, kind, provState } = map;
  const canvas = h('canvas', { class: 'map-canvas', width, height });
  const image = canvas.getContext('2d').createImageData(width, height);
  const layers = h('div', { class: 'map-layers', style: { width: `${width}px`, height: `${height}px` } }, canvas);
  const screen = h('canvas', { class: 'map-screen', width: 1, height: 1 });   // names; the outlines when zoomed in
  const tip = h('div', { class: 'map-tip', hidden: true });
  const view = h('div', { class: 'map-scroll' });
  try {   // the whole world the first time
    if (!localStorage.getItem(`hoi4dbg.zoom.${zoomId}`)) localStorage.setItem(`hoi4dbg.zoom.${zoomId}`, String(Math.max(ZOOM_MIN, Math.min(1, 1000 / width))));
  } catch { /* preference only */ }
  let labelSet = null;
  let paint = null;      // the colours of the last draw(style)
  let outlines = null;   // decodeBorders, when loaded
  let ground = null;     // loadTerrain, when loaded
  let riverPaths = null; // width class -> Path2D
  const show = { relief: true, rivers: true, types: true };
  const typePatterns = new Map();   // terrain -> CanvasPattern of its symbols
  const provPaths = new Map();   // province -> Path2D
  const arcPaths = new Map();    // arc -> Path2D
  const patterns = new Map();    // "fill|stripe" -> occupation stripes
  let frame = 0;
  const schedule = () => { if (!frame) frame = requestAnimationFrame(render); };
  const zoom = zoomable(zoomId, view, layers, width, height, { min: ZOOM_MIN, max: ZOOM_MAX, onZoom: schedule });
  canvas.style.imageRendering = 'auto';   // smooth while shrunk; drawn from the outlines when enlarged
  view.append(zoom.sizer);
  dragToScroll(view);
  view.addEventListener('scroll', schedule, { passive: true });
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(schedule).observe(view);
  map.outlines?.().then((o) => { if (o && o.width === width && o.height === height) { outlines = o; schedule(); } });
  map.terrain?.().then((t) => { if (t) { ground = t; schedule(); } });
  const wrap = h('div', { class: 'map-wrap' }, zoom.toolbar, view, screen, tip);

  const at = (ev) => {
    const r = canvas.getBoundingClientRect();
    const x = Math.floor(((ev.clientX - r.left) / r.width) * width);
    const y = Math.floor(((ev.clientY - r.top) / r.height) * height);
    if (x < 0 || y < 0 || x >= width || y >= height) return null;
    const i = y * width + x;
    if (kind[i] !== LAND) return null;
    return { pid: pids[i], sid: provState[pids[i]] ?? 0 };
  };
  const setTip = (nodes, ev) => {
    if (!nodes) { tip.hidden = true; return; }
    tip.replaceChildren(...[nodes].flat().filter(Boolean));
    tip.hidden = false;
    const box = wrap.getBoundingClientRect();
    tip.style.left = `${Math.max(0, Math.min(ev.clientX - box.left + 14, box.width - 230))}px`;
    tip.style.top = `${ev.clientY - box.top + 14}px`;
  };
  let downAt = null;
  canvas.addEventListener('mousemove', (ev) => onHover?.(at(ev), ev));
  canvas.addEventListener('mouseleave', () => { tip.hidden = true; });
  canvas.addEventListener('mousedown', (ev) => { downAt = [ev.clientX, ev.clientY]; });
  canvas.addEventListener('click', (ev) => {   // a drag of the map is no click
    if (downAt && Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 4) return;
    const hit = at(ev);
    if (hit) onClick?.(hit, ev);
  });

  function draw(style) {
    // colours, stripes and border groups per province: its state's, unless the province has its own (overrides)
    const maxSid = provState.reduce((a, b) => Math.max(a, b), 0) + 1;
    const sfill = [];
    const sstripe = [];
    const sgroup = new Int32Array(maxSid);
    for (let sid = 1; sid < maxSid; sid++) {
      const c = style.fill?.(sid);
      sfill[sid] = c ? (sid === style.highlight ? shade(c, 1.35) : c) : null;
      sstripe[sid] = style.stripe?.(sid) ?? null;
      sgroup[sid] = style.group?.(sid) ?? 0;
    }
    const strength = style.borderStrength ?? 1;   // pixel borders (below VECTOR_ZOOM): how much darker they are
    const fState = Math.max(0, 1 - 0.55 * strength);
    const fProvince = Math.max(0, 1 - 0.28 * strength);
    const nProv = provState.length;
    const fill = new Uint8Array(nProv * 3);
    const stripe = new Uint8Array(nProv * 3);
    const striped = new Uint8Array(nProv);
    const group = new Int32Array(nProv);
    const known = new Uint8Array(nProv);
    const setProvince = (p, c, s, g) => {
      known[p] = c ? 1 : 0;
      if (c) fill.set(c, p * 3);
      striped[p] = s ? 1 : 0;
      if (s) stripe.set(s, p * 3);
      group[p] = g;
    };
    for (let p = 1; p < nProv; p++) {
      const sid = provState[p];
      if (sid) setProvince(p, sfill[sid], sstripe[sid], sgroup[sid]);
    }
    for (const [p, o] of style.overrides ?? []) {
      if (p > 0 && p < nProv) {
        const sid = provState[p];
        setProvince(p, o.fill && sid === style.highlight ? shade(o.fill, 1.35) : o.fill, o.stripe, o.group ?? 0);
      }
    }
    if (style.visible) {   // fog of war: what is not seen is grey, its occupation unknown
      for (let p = 1; p < nProv; p++) {
        if (style.visible.has(p) || !known[p]) continue;
        const o = p * 3;
        for (let j = 0; j < 3; j++) fill[o + j] = fill[o + j] * 0.3 + 46;
        striped[p] = 0;
      }
    }
    const px = image.data;
    const [sr, sg, sb] = COLORS.sea;
    const [lr, lg, lb] = COLORS.lake;
    const [er, eg, eb] = COLORS.empty;
    const [br, bg, bb] = COLORS.border;
    const hl = style.highlight ?? -1;
    for (let y = 0, i = 0; y < height; y++) {
      for (let x = 0; x < width; x++, i++) {
        const p = 4 * i;
        px[p + 3] = 255;
        const k = kind[i];
        if (k !== LAND) {
          if (k === SEA) { px[p] = sr; px[p + 1] = sg; px[p + 2] = sb; } else if (k === LAKE) { px[p] = lr; px[p + 1] = lg; px[p + 2] = lb; } else { px[p] = er; px[p + 1] = eg; px[p + 2] = eb; }
          continue;
        }
        const pid = pids[i];
        const sid = provState[pid] ?? 0;
        const left = x > 0 && kind[i - 1] === LAND ? i - 1 : -1;
        const up = y > 0 && kind[i - width] === LAND ? i - width : -1;
        const lsid = left >= 0 ? provState[pids[left]] : sid;
        const usid = up >= 0 ? provState[pids[up]] : sid;
        if ((lsid !== sid || usid !== sid) && (sid === hl || lsid === hl || usid === hl)) {   // the chosen state's outline
          px[p] = 255; px[p + 1] = 255; px[p + 2] = 255;
          continue;
        }
        const g = group[pid];
        if ((left >= 0 && group[pids[left]] !== g) || (up >= 0 && group[pids[up]] !== g)) { px[p] = br; px[p + 1] = bg; px[p + 2] = bb; continue; }
        if (!known[pid]) { px[p] = er; px[p + 1] = eg; px[p + 2] = eb; continue; }
        const src = striped[pid] && ((x + y) % 8) < 3 ? stripe : fill;
        const o = pid * 3;
        let f = 1;
        if (style.states && (lsid !== sid || usid !== sid)) f = fState;
        else if (style.provinces && ((left >= 0 && pids[left] !== pid) || (up >= 0 && pids[up] !== pid))) f = fProvince;
        px[p] = src[o] * f; px[p + 1] = src[o + 1] * f; px[p + 2] = src[o + 2] * f;
      }
    }
    canvas.getContext('2d').putImageData(image, 0, 0);
    paint = { fill, stripe, striped, known, group, style };
    schedule();
  }

  /** The view: the map from its outlines when zoomed in (VECTOR_ZOOM), the names - at the screen's resolution. */
  function render() {
    frame = 0;
    const w = view.clientWidth;
    const hgt = view.clientHeight;
    if (!w || !hgt) return;
    const dpr = window.devicePixelRatio || 1;
    Object.assign(screen.style, { left: `${view.offsetLeft + view.clientLeft}px`, top: `${view.offsetTop + view.clientTop}px`,
      width: `${w}px`, height: `${hgt}px` });
    if (screen.width !== Math.round(w * dpr) || screen.height !== Math.round(hgt * dpr)) {
      screen.width = Math.round(w * dpr);
      screen.height = Math.round(hgt * dpr);
    }
    const z = zoom.level();
    const g = screen.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, screen.width, screen.height);
    g.setTransform(dpr * z, 0, 0, dpr * z, -view.scrollLeft * dpr, -view.scrollTop * dpr);
    const area = [view.scrollLeft / z, view.scrollTop / z, (view.scrollLeft + w) / z, (view.scrollTop + hgt) / z];
    const t0 = performance.now();
    if (paint) {
      const vector = outlines && z >= VECTOR_ZOOM;
      if (vector) paintFills(g, z, area); else paintPixels(g, z, area);
      paintTerrain(g, z, area);
      if (vector) paintBorders(g, z, area);
    }
    paintLabels(g, z, area);
    wrap.dataset.frameMs = String(Math.round(performance.now() - t0));   // the smoke test reads it
  }

  /** The drawn map (draw) of `area`: smoothed while shrunk, its pixels when enlarged (no outlines). */
  function paintPixels(g, z, area) {
    const x0 = Math.max(0, Math.floor(area[0]));
    const y0 = Math.max(0, Math.floor(area[1]));
    const x1 = Math.min(width, Math.ceil(area[2]));
    const y1 = Math.min(height, Math.ceil(area[3]));
    if (x1 <= x0 || y1 <= y0) return;
    g.imageSmoothingEnabled = z < 1;
    g.drawImage(canvas, x0, y0, x1 - x0, y1 - y0, x0, y0, x1 - x0, y1 - y0);
    g.imageSmoothingEnabled = true;
  }

  /** Relief (soft-light: lighter slopes to the north-west, darker to the south-east) and rivers over `area`. */
  function paintTerrain(g, z, area) {
    if (show.types && outlines && map.provTerrain?.length) paintTypes(g, z, area);
    if (!ground) return;
    const x0 = Math.max(0, area[0]);
    const y0 = Math.max(0, area[1]);
    const x1 = Math.min(width, area[2]);
    const y1 = Math.min(height, area[3]);
    if (show.relief && ground.relief && x1 > x0 && y1 > y0) {
      const sx = ground.relief.width / width;
      const sy = ground.relief.height / height;
      g.save();
      g.globalCompositeOperation = 'soft-light';
      g.drawImage(ground.relief, x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy, x0, y0, x1 - x0, y1 - y0);
      g.restore();
    }
    if (show.rivers && ground.rivers.length) {
      if (!riverPaths) {
        riverPaths = new Map();
        for (const r of ground.rivers) {
          if (!riverPaths.has(r[0])) riverPaths.set(r[0], new Path2D());
          smoothLine(riverPaths.get(r[0]), r, 1);
        }
      }
      const min = riverThreshold(z);
      g.strokeStyle = RIVER;
      g.lineCap = g.lineJoin = 'round';
      for (const [c, path] of riverPaths) {
        if (c < min) continue;
        g.lineWidth = Math.max(0.6 / z, 0.4 + (c - 3) * 0.125);
        g.stroke(path);
      }
    }
  }

  /** The terrain of the provinces in `area`: a tint per terrain, its symbols from TYPE_SYMBOLS_ZOOM. */
  function paintTypes(g, z, area) {
    const groups = new Map();
    for (const [pid, b] of outlines.provBox) {
      if (b[2] < area[0] || b[0] > area[2] || b[3] < area[1] || b[1] > area[3]) continue;
      const name = map.terrainTypes[map.provTerrain[pid]];
      if (!TERRAIN_STYLES[name] || map.provKind[pid] !== LAND) continue;
      let path = provPaths.get(pid);
      if (!path) { path = provincePath(outlines, pid); provPaths.set(pid, path); }
      if (!groups.has(name)) groups.set(name, new Path2D());
      groups.get(name).addPath(path);
    }
    for (const [name, path] of groups) {
      const [tint, symbol] = TERRAIN_STYLES[name];
      g.fillStyle = tint;
      g.fill(path);
      if (z < TYPE_SYMBOLS_ZOOM) continue;
      let pattern = typePatterns.get(name);
      if (!pattern) {
        const tile = document.createElement('canvas');
        tile.width = tile.height = 16;
        symbol(tile.getContext('2d'));
        pattern = g.createPattern(tile, 'repeat');
        typePatterns.set(name, pattern);
      }
      pattern.setTransform(new DOMMatrix([1 / z, 0, 0, 1 / z, 0, 0]));   // the symbols keep their size on screen
      g.fillStyle = pattern;
      g.fill(path);
    }
  }

  /** The map of `area` (map pixels) from the province outlines: sea, provinces by colour, stripes. */
  function paintFills(g, z, area) {
    const { fill, stripe, striped, known } = paint;
    const seen = (b) => b[2] >= area[0] && b[0] <= area[2] && b[3] >= area[1] && b[1] <= area[3];
    g.fillStyle = `rgb(${COLORS.sea.join(',')})`;
    g.fillRect(Math.max(0, area[0]), Math.max(0, area[1]), Math.min(width, area[2]) - Math.max(0, area[0]),
      Math.min(height, area[3]) - Math.max(0, area[1]));
    const byColour = new Map();   // one fill per colour: no seams between provinces of one colour
    const stripes = new Map();
    for (const [pid, b] of outlines.provBox) {
      if (!seen(b)) continue;
      let path = provPaths.get(pid);
      if (!path) { path = provincePath(outlines, pid); provPaths.set(pid, path); }
      const k = map.provKind[pid];
      const o = pid * 3;
      const c = k === LAKE ? COLORS.lake : k !== LAND ? COLORS.sea : known[pid] ? [fill[o], fill[o + 1], fill[o + 2]] : COLORS.empty;
      const key = k === LAND && striped[pid] ? `${c.join(',')}|${stripe[o]},${stripe[o + 1]},${stripe[o + 2]}` : c.join(',');
      const into = key.includes('|') ? stripes : byColour;
      if (!into.has(key)) into.set(key, new Path2D());
      into.get(key).addPath(path);
    }
    g.lineJoin = 'round';
    g.lineWidth = 1 / z;   // over the hairline between two colours
    for (const [key, path] of byColour) {
      g.fillStyle = g.strokeStyle = `rgb(${key})`;
      g.fill(path);
      g.stroke(path);
    }
    for (const [key, path] of stripes) {
      let pattern = patterns.get(key);
      if (!pattern) {
        const [base, line] = key.split('|');
        const tile = document.createElement('canvas');
        tile.width = tile.height = 8;
        const t = tile.getContext('2d');
        t.fillStyle = `rgb(${base})`;
        t.fillRect(0, 0, 8, 8);
        t.fillStyle = `rgb(${line})`;
        for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) if ((x + y) % 8 < 3) t.fillRect(x, y, 1, 1);
        pattern = g.createPattern(tile, 'repeat');
        patterns.set(key, pattern);
      }
      pattern.setTransform(new DOMMatrix([1 / z, 0, 0, 1 / z, 0, 0]));   // the stripes keep their size on screen
      g.fillStyle = pattern;
      g.fill(path);
    }
  }

  /** Coast, province, state and country borders and the chosen state's outline of `area` from the outlines. */
  function paintBorders(g, z, area) {
    const lines = Object.fromEntries(Object.keys(LINES).map((k) => [k, new Path2D()]));
    const box = outlines.box;
    for (let a = 0; a < outlines.arcs; a++) {
      const b = 4 * a;
      if (box[b + 2] < area[0] || box[b] > area[2] || box[b + 3] < area[1] || box[b + 1] > area[3]) continue;
      const line = borderKind(map, outlines, a, paint);
      if (!line) continue;
      let path = arcPaths.get(a);
      if (!path) { path = new Path2D(); traceArc(path, outlines, a, true); arcPaths.set(a, path); }
      lines[line].addPath(path);
    }
    g.lineCap = 'round';
    const s = paint.style.borderStrength ?? 1;
    for (const [line, [px, colour]] of Object.entries(LINES)) {
      const scaled = SCALED.has(line);
      g.lineWidth = (scaled ? px * s : px) / z;
      g.strokeStyle = scaled ? strengthen(colour, s) : colour;
      g.stroke(lines[line]);
    }
  }

  /** Names, cities and division markers on `g` (map pixels) at zoom `z`, those in `area` (map pixels). */
  function paintLabels(g, z, area) {
    if (!labelSet) return;
    const inside = (x, y, m) => x >= area[0] - m && x <= area[2] + m && y >= area[1] - m && y <= area[3] + m;
    paintRails(g, z, labelSet.rails ?? [], inside);
    paintArrows(g, z, labelSet.arrows ?? [], inside);
    g.textBaseline = 'middle';
    g.lineJoin = 'round';
    const placed = [];
    g.textAlign = 'center';
    for (const l of labelSet.names ?? []) {
      if (l.size * z < 7) continue;
      const size = Math.min(l.size, 46 / z);   // up to 46 pixels on screen when zoomed in
      const text = l.text.toUpperCase();
      if (!inside(l.x, l.y, size * text.length)) continue;
      g.font = `600 ${size.toFixed(1)}px "Segoe UI", system-ui, sans-serif`;
      g.letterSpacing = `${(size * 0.08).toFixed(1)}px`;
      const w = g.measureText(text).width;
      placed.push([l.x - w / 2, l.y - size / 2, l.x + w / 2, l.y + size / 2]);
      g.lineWidth = Math.max(2 / z, size / 7);
      g.strokeStyle = 'rgba(0, 0, 0, .55)';
      g.fillStyle = 'rgba(255, 255, 255, .88)';
      g.strokeText(text, l.x, l.y);
      g.fillText(text, l.x, l.y);
    }
    g.letterSpacing = '0px';
    g.textAlign = 'left';
    const min = cityThreshold(z);
    for (const c of labelSet.cities ?? []) {
      if (c.vp < min) break;   // the largest first
      if (!inside(c.x, c.y, 200 / z)) continue;
      const px = (c.vp >= 25 ? 13 : c.vp >= 10 ? 12 : 11) / z;
      g.font = `${c.vp >= 25 ? 600 : 400} ${px.toFixed(2)}px "Segoe UI", system-ui, sans-serif`;
      const w = g.measureText(c.text).width;
      const box = [c.x - 3 / z, c.y - px * 0.7, c.x + 6 / z + w, c.y + px * 0.7];
      if (placed.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
      placed.push(box);
      g.beginPath();
      g.arc(c.x, c.y, 2.4 / z, 0, Math.PI * 2);
      g.fillStyle = '#f4efe2';
      g.strokeStyle = 'rgba(0, 0, 0, .8)';
      g.lineWidth = 1.2 / z;
      g.fill();
      g.stroke();
      g.lineWidth = 3 / z;
      g.strokeStyle = 'rgba(0, 0, 0, .7)';
      g.strokeText(c.text, c.x + 5 / z, c.y);
      g.fillText(c.text, c.x + 5 / z, c.y);
    }
    g.textAlign = 'center';
    if (z >= 0.7) paintMarks(g, z, labelSet.marks ?? [], inside);
    paintBattles(g, z, labelSet.battles ?? [], inside);
    g.font = `700 ${(10 / z).toFixed(2)}px "Segoe UI", system-ui, sans-serif`;
    for (const m of unitMarkers(map, labelSet.units ?? [], z)) {   // a counter with the number of divisions
      if (!inside(m.x, m.y, 20 / z)) continue;
      const text = String(m.count);
      const w = Math.max(16 / z, g.measureText(text).width + 8 / z);
      const hgt = 14 / z;
      g.fillStyle = `rgb(${m.color.join(',')})`;
      g.strokeStyle = 'rgba(0, 0, 0, .85)';
      g.lineWidth = 1.5 / z;
      g.beginPath();
      g.roundRect(m.x - w / 2, m.y - hgt / 2, w, hgt, 3 / z);
      g.fill();
      g.stroke();
      const light = m.color[0] * 0.299 + m.color[1] * 0.587 + m.color[2] * 0.114 > 150;
      g.fillStyle = light ? '#111' : '#fff';
      g.fillText(text, m.x, m.y + 0.5 / z);
    }
  }

  /** Railways: a dark line per level (thicker = higher), sleepers as a light dashed line when zoomed in. */
  function paintRails(g, z, rails, inside) {
    if (!rails.length) return;
    const min = railThreshold(z);
    const byLevel = new Map();
    for (const [a, b, level] of rails) {
      if (level < min) continue;
      const p = provinceCentre(map, a);
      const q = provinceCentre(map, b);
      if (!p || !q || (!inside(p[0], p[1], 0) && !inside(q[0], q[1], 0) && Math.hypot(p[0] - q[0], p[1] - q[1]) < 400)) continue;
      if (!byLevel.has(level)) byLevel.set(level, new Path2D());
      const path = byLevel.get(level);
      path.moveTo(p[0], p[1]);
      path.lineTo(q[0], q[1]);
    }
    g.lineCap = 'round';
    for (const [level, path] of [...byLevel].sort((x, y) => x[0] - y[0])) {
      const w = (0.7 + 0.45 * level) / z;
      g.setLineDash([]);
      g.lineWidth = w;
      g.strokeStyle = 'rgba(28, 24, 20, .88)';
      g.stroke(path);
      if (z >= 0.8) {
        g.setLineDash([3 / z, 3 / z]);
        g.lineWidth = w * 0.4;
        g.strokeStyle = 'rgba(235, 225, 205, .8)';
        g.stroke(path);
      }
    }
    g.setLineDash([]);
  }

  /** Arrows from a province's centre towards the next one (stopping short of its centre), in the country's colour
   * with a dark edge; thicker when attacking, wider with more divisions. */
  function paintArrows(g, z, arrows, inside) {
    const s = 1 / z;
    g.lineCap = 'round';
    g.lineJoin = 'round';
    for (const a of arrows) {
      const p = provinceCentre(map, a.from);
      const q = provinceCentre(map, a.to);
      if (!p || !q || (!inside(p[0], p[1], 40 * s) && !inside(q[0], q[1], 40 * s))) continue;
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      if (len < 1) continue;
      const ux = (q[0] - p[0]) / len;
      const uy = (q[1] - p[1]) / len;
      const end = [q[0] - ux * Math.min(len * 0.3, 8 * s), q[1] - uy * Math.min(len * 0.3, 8 * s)];
      const w = (a.attack ? 3.2 : 2) * s + Math.min(a.count - 1, 4) * 0.5 * s;
      const head = Math.max(w * 2.4, 7 * s);
      const base = [end[0] - ux * head, end[1] - uy * head];
      const shape = new Path2D();
      shape.moveTo(p[0] + ux * 6 * s, p[1] + uy * 6 * s);
      shape.lineTo(base[0], base[1]);
      const tip = new Path2D();
      tip.moveTo(end[0], end[1]);
      tip.lineTo(base[0] - uy * head * 0.6, base[1] + ux * head * 0.6);
      tip.lineTo(base[0] + uy * head * 0.6, base[1] - ux * head * 0.6);
      tip.closePath();
      g.strokeStyle = 'rgba(0, 0, 0, .8)';
      g.lineWidth = w + 2 * s;
      g.stroke(shape);
      g.lineWidth = 2 * s;
      g.stroke(tip);
      const colour = `rgb(${a.color.join(',')})`;
      g.strokeStyle = colour;
      g.lineWidth = w;
      g.stroke(shape);
      g.fillStyle = colour;
      g.fill(tip);
    }
  }

  /** Crossed swords below the province's centre (its divisions stand on it) and a bar: the attacker's share in its
   * colour, the defender's in its. */
  function paintBattles(g, z, battles, inside) {
    const s = 1 / z;
    for (const b of battles) {
      const c = provinceCentre(map, b.pid);
      if (!c || !inside(c[0], c[1], 30 * s)) continue;
      const x = c[0];
      const y = c[1] + 15 * s;
      g.beginPath();
      g.arc(x, y, 7.5 * s, 0, Math.PI * 2);
      g.fillStyle = 'rgba(120, 16, 16, .92)';
      g.strokeStyle = 'rgba(0, 0, 0, .9)';
      g.lineWidth = 1.2 * s;
      g.fill();
      g.stroke();
      g.beginPath();
      g.moveTo(x - 4 * s, y - 4 * s); g.lineTo(x + 4 * s, y + 4 * s);
      g.moveTo(x + 4 * s, y - 4 * s); g.lineTo(x - 4 * s, y + 4 * s);
      g.strokeStyle = '#f4efe2';
      g.lineWidth = 1.6 * s;
      g.stroke();
      const w = 22 * s;
      const top = y + 9.5 * s;
      g.fillStyle = `rgb(${b.defender.join(',')})`;
      g.fillRect(x - w / 2, top, w, 3.5 * s);
      g.fillStyle = `rgb(${b.attacker.join(',')})`;
      g.fillRect(x - w / 2, top, (w * b.share) / 100, 3.5 * s);
      g.strokeStyle = 'rgba(0, 0, 0, .9)';
      g.lineWidth = 1 * s;
      g.strokeRect(x - w / 2, top, w, 3.5 * s);
    }
  }

  /** Ports (blue circle), forts (grey square, blue edge when coastal), supply hubs (orange diamond) with their level,
   * above the province's centre (its divisions stand on it). */
  function paintMarks(g, z, marks, inside) {
    const s = 1 / z;
    const slot = { fort: -13, coastal: -26, hub: 0, port: 13 };
    g.font = `700 ${(8.5 * s).toFixed(2)}px "Segoe UI", system-ui, sans-serif`;
    for (const m of marks) {
      const c = provinceCentre(map, m.pid);
      if (!c || !inside(c[0], c[1], 30 * s)) continue;
      const x = c[0] + slot[m.kind] * s;
      const y = c[1] - 14 * s;
      g.beginPath();
      if (m.kind === 'port') g.arc(x, y, 6 * s, 0, Math.PI * 2);
      else if (m.kind === 'hub') { g.moveTo(x, y - 7 * s); g.lineTo(x + 7 * s, y); g.lineTo(x, y + 7 * s); g.lineTo(x - 7 * s, y); g.closePath(); }
      else g.rect(x - 6 * s, y - 6 * s, 12 * s, 12 * s);
      g.fillStyle = { port: '#2f6fb3', hub: '#d9822b', fort: '#55524c', coastal: '#55524c' }[m.kind];
      g.strokeStyle = m.kind === 'coastal' ? '#6fb3ff' : 'rgba(0, 0, 0, .85)';
      g.lineWidth = (m.kind === 'coastal' ? 2 : 1.2) * s;
      g.fill();
      g.stroke();
      g.fillStyle = '#fff';
      g.fillText(String(m.level), x, y + 0.5 * s);
    }
  }

  function labels(set) {
    labelSet = set;
    schedule();
  }

  /** The map with its names at `scale` of the full size (the report). */
  function snapshot(scale = 0.5) {
    const out = document.createElement('canvas');
    out.width = Math.round(width * scale);
    out.height = Math.round(height * scale);
    const g = out.getContext('2d');
    g.imageSmoothingQuality = 'high';
    g.drawImage(canvas, 0, 0, out.width, out.height);
    g.setTransform(scale, 0, 0, scale, 0, 0);
    paintTerrain(g, scale, [0, 0, width, height]);
    paintLabels(g, scale, [0, 0, width, height]);   // the names as at zoom `scale`
    return out;
  }

  function terrain(opts) {
    Object.assign(show, opts);
    schedule();
  }

  return { el: wrap, draw, labels, at, canvas, snapshot, setTip, terrain };
}
