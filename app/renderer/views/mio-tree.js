// MIO window (2026-10-20, user's request): a click on a MIO of the Country Editor shows its trait tree as the game's
// MIO window - column headers, traits at their grid positions with the game's frames and icons, parent lines (green
// from an unlocked parent, blue otherwise; dotted when any one of several parents is enough), mutually exclusive
// pairs (red "!"), unlocked traits ticked - with level, funds to the next level, attributes, initial trait and policy.
// Tree from the game and mod files (/api/countries/<TAG>/mios/<id>), state from game memory when the game runs.
import { h, notice } from '../lib/dom.js';
import { numberLocale } from '../lib/options.js';
import { modifierClass } from './spirits.js';
import { mioIcon } from '../lib/icons.js';
import { zoomable } from '../lib/zoom.js';
import { dragToScroll } from './research.js';

export const CELL = { w: 88, h: 117 };          // the game's trait grid (industrial_organisation_trait_entry 87 x 117)
export const FRAME = { w: 64, h: 80, icon: 48, left: 12 };
const HEAD = 30;                                 // column header row above the grid
export const LINE_ON = 'rgb(120, 237, 166)';     // defines TRAIT_LINE_ASSIGNED_COLOR
export const LINE_OFF = 'rgb(171, 191, 237)';    // TRAIT_LINE_NON_ASSIGNED_COLOR
const KIND_LABEL = { equipment_bonus: 'Design team bonus', production_bonus: 'Industrial manufacturer bonus',
  organization_modifier: 'Organization bonus' };
const SVG = 'http://www.w3.org/2000/svg';

const pct = (v) => `${v > 0 ? '+' : ''}${+(v * 100).toFixed(2)}%`;

/** "unlocked" | "available" | "locked" (parents missing) | "excluded" (a mutually exclusive trait is unlocked). */
export function traitState(t, byToken) {
  if (t.unlocked) return 'unlocked';
  if (t.exclusive.some((e) => byToken.get(e)?.unlocked)) return 'excluded';
  const have = t.parents.filter((p) => byToken.get(p)?.unlocked).length;
  return !t.parents.length || have >= Math.min(t.parents_needed || 1, t.parents.length) ? 'available' : 'locked';
}

/** Lines of the tree in grid pixels: [{x1, y1, x2, y2, on, dotted}] (parent links, elbows below the parent) and
 * [{x1, x2, y, ...}] for exclusive pairs on one row (each pair once), [{...}] for the other exclusive pairs. */
export function treeLines(traits) {
  const by = new Map(traits.map((t) => [t.token, t]));
  const cx = (t) => t.x * CELL.w + CELL.w / 2;
  const links = [];
  for (const t of traits) {
    const dotted = t.parents.length > 1 && (t.parents_needed || 1) < t.parents.length;
    for (const token of t.parents) {
      const p = by.get(token);
      if (!p) continue;
      const on = Boolean(p.unlocked);
      const top = t.y * CELL.h;
      const bottom = p.y * CELL.h + FRAME.h;
      if (Math.abs(cx(p) - cx(t)) < 1) links.push({ points: [[cx(p), bottom], [cx(t), top]], on, dotted });
      else {
        const mid = Math.min(bottom + 10, top - 6);
        links.push({ points: [[cx(p), bottom], [cx(p), mid], [cx(t), mid], [cx(t), top]], on, dotted });
      }
    }
  }
  const exclusive = [];
  const seen = new Set();
  for (const t of traits) {
    for (const token of t.exclusive) {
      const o = by.get(token);
      const key = [t.token, token].sort().join('|');
      if (!o || seen.has(key)) continue;
      seen.add(key);
      const [a, b] = t.x <= o.x ? [t, o] : [o, t];
      exclusive.push(a.y === b.y
        ? { row: true, x1: a.x * CELL.w + FRAME.left + FRAME.w, x2: b.x * CELL.w + FRAME.left, y: a.y * CELL.h + FRAME.icon / 2 + 8 }
        : { row: false, x1: cx(a), y1: a.y * CELL.h + FRAME.icon / 2 + 8, x2: cx(b), y2: b.y * CELL.h + FRAME.icon / 2 + 8 });
    }
  }
  return { links, exclusive };
}

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

function bonusLine(b) {
  return h('div', { class: 'hoi-line' }, h('span', { class: 'hoi-mod' }, mioIcon(b.key), b.scope ? `${b.scope}: ${b.label}` : b.label),
    h('span', { class: `hoi-num ${modifierClass(b.key, b.value)}` }, b.key.endsWith('task_capacity') ? `${b.value > 0 ? '+' : ''}${b.value}` : pct(b.value)));
}

function bonusGroups(bonuses) {
  return Object.keys(KIND_LABEL).filter((k) => bonuses.some((b) => b.kind === k)).map((k) => h('div', { class: 'spirit-tip-mods' },
    h('div', { class: 'mio-group' }, KIND_LABEL[k]), bonuses.filter((b) => b.kind === k).map(bonusLine)));
}

const STATE_TEXT = { unlocked: 'Unlocked', available: 'Can be unlocked', locked: 'Needs its parent traits',
  excluded: 'Not available: a mutually exclusive trait is unlocked' };
const FRAME_OF = { unlocked: 0, available: 0, locked: 1, excluded: 2 };

// The tree zooms (a CSS transform) and scrolls, which would move or clip a tooltip inside it: one tooltip at the top of
// the page shows a copy of the trait's, next to the trait and kept in the window.
let floatTip = null;
function showTip(e) {
  const tip = e.currentTarget.querySelector('.spirit-tip');
  if (!tip || e.currentTarget.closest('.tech-dragging')) return;
  if (!floatTip?.isConnected) {
    floatTip = h('div', { class: 'spirit-tip mio-float-tip', role: 'tooltip' });
    document.body.append(floatTip);
  }
  floatTip.replaceChildren(...[...tip.childNodes].map((n) => n.cloneNode(true)));
  floatTip.hidden = false;
  const r = e.currentTarget.getBoundingClientRect();
  const below = r.bottom + floatTip.offsetHeight + 8 <= window.innerHeight;
  floatTip.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - floatTip.offsetWidth - 8))}px`;
  floatTip.style.top = `${below ? r.bottom + 4 : Math.max(4, r.top - floatTip.offsetHeight - 4)}px`;
}
export function hideTip() {
  if (floatTip) floatTip.hidden = true;
}

function traitNode(t, state, data, byToken) {
  const frames = (t.special ? data.sprites.special : data.sprites.frame) ?? [];
  const frame = frames[FRAME_OF[state]] ?? frames[0];
  const needs = t.parents.length ? `${t.parents.length > 1 ? (t.parents_needed >= t.parents.length ? 'All of' : `${t.parents_needed} of`) : 'After'}: `
    + t.parents.map((p) => byToken.get(p)?.name ?? p).join(', ') : null;
  return h('div', {
    class: `mio-trait mio-trait-${state}${t.special ? ' mio-trait-special' : ''}`, tabindex: 0, 'data-token': t.token,
    'aria-label': `${t.name}: ${STATE_TEXT[state]}`, onMouseenter: showTip, onFocus: showTip, onMouseleave: hideTip, onBlur: hideTip,
    style: { left: `${t.x * CELL.w + FRAME.left}px`, top: `${t.y * CELL.h}px` },
  },
  frame ? h('img', { class: 'mio-trait-frame', src: frame, alt: '' }) : h('div', { class: 'mio-trait-frame mio-trait-noframe' }),
  t.icon ? h('img', { class: 'mio-trait-icon', src: t.icon, alt: '' }) : null,
  h('div', { class: 'mio-trait-kinds' }, t.kinds.map((k) => (data.sprites[k]
    ? h('img', { src: data.sprites[k], alt: '', title: KIND_LABEL[k] }) : null))),
  t.unlocked ? h('span', { class: 'mio-trait-done', 'aria-hidden': 'true' }, '✓') : null,
  h('div', { class: 'spirit-tip', role: 'tooltip' },
    h('div', { class: 'spirit-tip-name' }, t.name),
    h('div', { class: 'spirit-tip-kind' }, STATE_TEXT[state]),
    ...bonusGroups(t.bonuses),
    t.limit_to?.length ? h('div', { class: 'muted' }, `Only for: ${t.limit_to.join(', ')}`) : null,
    needs ? h('div', { class: 'spirit-tip-desc' }, needs) : null,
    t.exclusive.length ? h('div', { class: 'spirit-tip-desc hoi-neg' }, `Mutually exclusive with: ${t.exclusive.map((e) => byToken.get(e)?.name ?? e).join(', ')}`) : null));
}

/** The tree: column headers, an SVG of the lines and the trait nodes, in the game's grid; mouse wheel zooms, the
 * left mouse button drags it around (as the research and focus trees; the zoom level is remembered). */
export function treeView(data) {
  const byToken = new Map(data.traits.map((t) => [t.token, t]));
  const width = Math.max(1, data.width) * CELL.w;
  const height = Math.max(1, data.height) * CELL.h;
  const svg = svgEl('svg', { class: 'mio-tree-lines', width, height, viewBox: `0 0 ${width} ${height}` });
  const { links, exclusive } = treeLines(data.traits);
  for (const l of links.sort((a, b) => a.on - b.on)) {   // green drawn over blue
    svg.append(svgEl('polyline', { points: l.points.map((p) => p.join(',')).join(' '), fill: 'none',
      stroke: l.on ? LINE_ON : LINE_OFF, 'stroke-width': 2, ...(l.dotted ? { 'stroke-dasharray': '2 4', 'stroke-linecap': 'round' } : {}) }));
  }
  for (const e of exclusive) {
    if (e.row) {
      svg.append(svgEl('line', { x1: e.x1 + 6, y1: e.y, x2: e.x2 - 6, y2: e.y, stroke: LINE_OFF, 'stroke-width': 2 }));
      svg.append(svgEl('polygon', { points: `${e.x1},${e.y} ${e.x1 + 8},${e.y - 6} ${e.x1 + 8},${e.y + 6}`, fill: '#5fae3e' }));
      svg.append(svgEl('polygon', { points: `${e.x2},${e.y} ${e.x2 - 8},${e.y - 6} ${e.x2 - 8},${e.y + 6}`, fill: '#5fae3e' }));
    } else {
      svg.append(svgEl('line', { x1: e.x1, y1: e.y1, x2: e.x2, y2: e.y2, stroke: '#c84a3a', 'stroke-width': 2, 'stroke-dasharray': '6 4' }));
    }
  }
  const marks = exclusive.map((e) => h('span', { class: 'mio-excl', title: 'Mutually exclusive', 'aria-hidden': 'true',
    style: { left: `${(e.x1 + e.x2) / 2}px`, top: `${e.row ? e.y : (e.y1 + e.y2) / 2}px` } }, '!'));
  const tree = h('div', { class: 'mio-tree', style: { width: `${width}px`, height: `${height + HEAD}px` } },
    h('div', { class: 'mio-tree-heads', style: { width: `${width}px` } }, data.headers.map((hd) => h('span', {
      class: 'mio-tree-head', style: { left: `${hd.x * CELL.w + CELL.w / 2}px` } }, hd.text))),
    h('div', { class: 'mio-tree-grid', style: { top: `${HEAD}px`, width: `${width}px`, height: `${height}px` } },
      svg, ...marks, ...data.traits.map((t) => traitNode(t, traitState(t, byToken), data, byToken))));
  const view = h('div', { class: 'mio-tree-scroll', style: { height: `${Math.min(height + HEAD + 24, 640)}px` } });
  const { toolbar, sizer } = zoomable('mio', view, tree, width, height + HEAD);
  view.append(sizer);
  view.addEventListener('wheel', hideTip, { passive: true });
  view.addEventListener('pointerdown', hideTip);
  dragToScroll(view);
  return h('div', { class: 'mio-tree-wrap' }, toolbar, view);
}

/** Left side of the MIO window: icon and level, funds to the next level, attributes, initial trait and policy. */
function sideView(data) {
  const a = data.attributes ?? {};
  const fmt = (v) => Math.round(v).toLocaleString(numberLocale());
  return h('div', { class: 'mio-side' },
    h('div', { class: 'mio-side-head' },
      data.icon ? h('img', { class: 'mio-side-icon', src: data.icon, alt: '' }) : null,
      h('div', null, h('div', { class: 'mio-side-name' }, data.name),
        h('div', { class: 'mio-side-level' }, h('span', { class: 'mio-level mio-level-inline' }, String(data.size ?? 0)), ' Level'))),
    Number.isFinite(data.funds) ? h('div', { class: 'mio-progress', title: `Funds ${fmt(data.funds)} / ${fmt(a.funds_needed ?? 0)} to the next level` },
      h('div', { class: 'mio-progress-bar', style: { width: `${Math.round((a.progress ?? 0) * 100)}%` } }),
      h('span', null, `${fmt(data.funds)} / ${fmt(a.funds_needed ?? 0)} funds`)) : null,
    h('div', { class: 'mio-side-title' }, 'Attributes'),
    h('div', { class: 'hoi-line' }, h('span', null, 'Research Bonus'), h('span', { class: 'hoi-num hoi-pos' }, pct(a.research_bonus ?? 0))),
    h('div', { class: 'hoi-line' }, h('span', null, 'Design Team Assign Cost'), h('span', { class: 'hoi-num' }, `${(a.assign_cost ?? 0).toFixed(2)}/day`)),
    h('div', { class: 'hoi-line' }, h('span', null, 'Funds Gain'), h('span', { class: `hoi-num ${a.funds_gain ? 'hoi-pos' : ''}` }, pct(a.funds_gain ?? 0))),
    h('div', { class: 'hoi-line' }, h('span', null, 'Unlocked traits'), h('span', { class: 'hoi-num' }, `${data.unlocked_count} / ${data.traits.length}`)),
    data.initial_trait ? h('div', null, h('div', { class: 'mio-side-title' }, 'Equipment Bonuses'),
      h('div', { class: 'mio-initial' }, data.initial_trait.name),
      data.initial_trait.limit_to?.length ? h('div', { class: 'muted' }, data.initial_trait.limit_to.join(', ')) : null,
      data.initial_trait.bonuses.map(bonusLine)) : null,
    h('div', { class: 'mio-side-title' }, 'Policy'),
    data.policy ? h('div', { class: 'mio-policy' }, data.policy.icon ? h('img', { src: data.policy.icon, alt: '' }) : null,
      h('div', null, h('div', { class: 'mio-policy-name' }, data.policy.name), data.policy.bonuses.map(bonusLine)))
      : h('div', { class: 'muted' }, 'No policy'));
}

/** Loads and shows the MIO window of `mio` (an id) into `host`. */
export async function showMioTree(ctx, tag, mio, host) {
  if (!host.childElementCount) host.replaceChildren(h('div', { class: 'muted' }, 'Reading the MIO…'));
  host.dataset.mio = mio;   // a later click (or closing) wins over this read
  let res;
  try {
    res = await ctx.api.get(`/api/countries/${encodeURIComponent(tag)}/mios/${encodeURIComponent(mio)}`);
  } catch (err) {
    if (host.dataset.mio !== mio) return;
    host.replaceChildren(notice('warn', `MIO unavailable: ${err.message}`));
    return;
  }
  if (host.dataset.mio !== mio) return;
  const data = res.data;
  if (!data?.traits) {
    host.replaceChildren(notice('warn', `MIO unavailable: ${res.note ?? 'no data'}`));
    return;
  }
  const old = host.querySelector('.mio-tree-scroll');
  const scroll = [old?.scrollLeft ?? 0, old?.scrollTop ?? 0];
  hideTip();
  host.replaceChildren(h('div', { class: 'mio-window' }, sideView(data),
    h('div', { class: 'mio-main' }, treeView(data),
      h('p', { class: 'hint' }, data.source === 'live' ? 'Level, funds, traits and policy from game memory; the tree from the game and mod files.'
        : 'From the newest save (the game is not read); the tree from the game and mod files.'))));
  const view = host.querySelector('.mio-tree-scroll');
  if (view) [view.scrollLeft, view.scrollTop] = scroll;
}
