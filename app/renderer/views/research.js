// Research: how many research slots the selected country has and what each one researches (game memory while
// the game runs, else the newest save). The tile has the usual [Live | On refresh] switch.
import { h, notice, viewHeader } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { countryPicker, tagChip } from './shared.js';

/** "+13%" for a research speed factor of 1.13 ('' when unknown or 1). */
export function speedText(speed) {
  if (speed == null || Math.abs(speed - 1) < 1e-9) return '';
  const pct = Math.round((speed - 1) * 1000) / 10;
  return `${pct > 0 ? '+' : ''}${pct}%`;
}

/** "2 of 3 slots researching" summary line. */
export function slotSummary(slots) {
  const busy = slots.filter((s) => s.technology).length;
  return `${busy} of ${slots.length} slot${slots.length === 1 ? '' : 's'} researching`;
}

/** "18.7% finished · 146 days left" (game rounding: progress cut to 0.1 %, days rounded up by the backend). */
export function progressText(s) {
  if (s.progress == null) return '';
  const pct = `${(Math.floor(s.progress * 1000) / 10).toFixed(1)}% finished`;
  if (s.days_left == null) return pct;
  return `${pct} · ${s.estimate ? '~' : ''}${s.days_left} day${s.days_left === 1 ? '' : 's'} left`;
}

/** "2.3 years ahead of time: -82% speed" for a technology researched before its start year ('' otherwise). */
export function aheadText(s) {
  if (!s.ahead_years || !s.base_speed || s.speed == null) return '';
  const pct = Math.round((s.speed / s.base_speed - 1) * 100);
  return `${s.ahead_years.toFixed(1)} years ahead of time: ${pct}% speed`;
}

function slotRow(s) {
  const speed = speedText(s.base_speed ?? s.speed);
  const ahead = aheadText(s);
  const info = h('span', { class: 'research-name' }, s.technology ? s.name : 'Empty slot',
    s.technology && s.name !== s.technology ? h('span', { class: 'muted research-id' }, ` ${s.technology}`) : null);
  const progress = s.progress == null ? null : h('div', { class: 'research-progress' },
    h('div', { class: 'research-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100,
      'aria-valuenow': Math.round(s.progress * 100) },
    h('div', { class: 'research-bar-fill', style: { width: `${Math.min(100, s.progress * 100)}%` } })),
    h('span', { class: 'research-progress-text', title: s.estimate
      ? 'Estimate: ahead of time the day count can differ by a day; from a save the technology bonus is unknown' : `Cost ${Math.round(s.cost)} research points` },
    progressText(s)),
    ahead ? h('span', { class: 'research-ahead', title: 'The game divides the research speed by 1 + 2 x years ahead; '
      + 'the penalty shrinks every day until the start year' }, ahead) : null);
  return h('div', { class: `research-slot ${s.technology ? '' : 'research-empty'}` },
    h('span', { class: 'research-no' }, s.slot),
    s.icon ? h('img', { class: 'research-icon', src: s.icon, alt: '' }) : h('span', { class: 'research-icon research-icon-none' }),
    h('div', { class: 'research-main' }, info, progress),
    h('span', { class: 'research-speed', title: 'Research speed bonus of this slot' }, speed));
}

/** "+50% · Motorization Research Speed · 1 use left" for a limited (one-time) research bonus. */
export function bonusText(b) {
  const pct = Math.round(b.bonus * 1000) / 10;
  const cats = (b.category_labels?.length ? b.category_labels : b.categories).join(', ');
  return `+${pct}% · ${cats} · ${b.uses} use${b.uses === 1 ? '' : 's'} left`;
}

/** "Field Hospital I, Basic Armored Car (1940, ahead of time)" - technologies a bonus can be used on now. */
export function usableText(usable, year) {
  if (!usable) return '';
  if (!usable.length) return 'No technology of these categories can be researched now';
  return usable.map((t) => (year && t.start_year > year ? `${t.name} (${t.start_year}, ahead of time)` : t.name)).join(', ');
}

function bonusList(bonuses, year) {
  if (!bonuses) return null;
  return h('div', { class: 'research-bonuses' },
    h('h3', { class: 'research-subhead' }, `Limited bonuses: ${bonuses.length}`),
    bonuses.length
      ? h('ul', { class: 'research-bonus-list' }, bonuses.map((b) => h('li', { class: 'research-bonus' },
        h('span', { class: 'research-bonus-name' }, b.label || b.name),
        h('span', { class: 'research-bonus-info', title: `${b.name} · ${b.categories.join(', ')}` }, bonusText(b)),
        b.usable ? h('span', { class: 'research-bonus-usable', title: 'From the technology tree: researched predecessors, '
          + 'no exclusive technology researched; country-only technologies are left out' },
        h('b', null, 'Can be used for: '), usableText(b.usable, year)) : null)))
      : h('p', { class: 'muted' }, 'No one-time research bonuses available.'));
}

/** Research slots tile (refreshable). Returns { el, refresh, stop }. */
export function researchPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Research slots', url: `/api/countries/${encodeURIComponent(tag)}/research`,
    liveParts: (res) => (res.data?.research_source === 'live' ? ['research slots'] : []),
    render(body, res) {
      const slots = res.data?.slots;
      if (!slots) {
        body.replaceChildren(notice('warn', `Research unavailable: ${res.note}`));
        return;
      }
      body.replaceChildren(
        h('p', { class: 'muted research-summary' }, slotSummary(slots)),
        h('div', { class: 'research-slots' }, slots.map(slotRow)),
        bonusList(res.data.bonuses, res.data.game_year));
    },
  });
}

const TAB_KEY = 'hoi4dbg.researchTab';
const SVG = 'http://www.w3.org/2000/svg';

/** Remembered research tab, or the first one when it is not among `tabs`. */
export function pickTab(tabs, remembered) {
  return tabs.find((t) => t.id === remembered)?.id ?? tabs[0]?.id ?? null;
}

function readTab() {
  try { return localStorage.getItem(TAB_KEY); } catch { return null; }
}

function writeTab(id) {
  try { localStorage.setItem(TAB_KEY, id); } catch { /* preference only */ }
}

const CONDITION = { always: '', dlc: 'shown because of an owned DLC',
  unknown: 'condition of a mod not checked - may be hidden in game' };
const STATE_LABEL = { researched: 'Researched', researching: 'Researching', available: 'Can be researched',
  excluded: 'Excluded by a researched alternative', unavailable: 'Not available yet' };

/** Tooltip of a technology in the tree. */
export function techTitle(t) {
  return [t.name, STATE_LABEL[t.state] ?? t.state,
    t.state === 'researching' && t.progress != null ? progressText(t) : '',
    t.start_year ? `${t.start_year}${t.ahead && t.state !== 'researched' ? ' (ahead of time)' : ''}` : '',
    t.excluded_by?.length ? `excluded by ${t.excluded_by.join(', ')}` : '',
    t.excludes?.length ? `mutually exclusive with ${t.excludes.map((x) => x.name).join(', ')}` : '',
    t.id].filter(Boolean).join(' · ');
}

/** SVG path "d" of a routed line (points from the backend). */
export function pathOf(points) {
  return points.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ');
}

/** Lets the left mouse button drag the tree around (like the game's research screen). */
export function dragToScroll(el) {
  let start = null;
  el.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    start = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', (e) => {
    if (!start) return;
    const dx = e.clientX - start.x; const dy = e.clientY - start.y;
    if (!start.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    start.moved = true;
    el.classList.add('tech-dragging');
    el.scrollLeft = start.left - dx;
    el.scrollTop = start.top - dy;
  });
  const stop = (e) => {
    if (!start) return;
    if (start.moved) {   // the click that ends a drag must not act on the item under the mouse
      el.dataset.dragged = '1';
      setTimeout(() => { delete el.dataset.dragged; }, 0);
    }
    start = null;
    el.classList.remove('tech-dragging');
    if (el.hasPointerCapture?.(e.pointerId)) el.releasePointerCapture(e.pointerId);
  };
  el.addEventListener('pointerup', stop);
  el.addEventListener('pointercancel', stop);
}

function treeItem(d, t) {
  const bg = d.backgrounds[`${t.size}_${t.state}`] ?? d.backgrounds[`${t.size}_available`];
  return h('div', {
    class: `tech-item tech-${t.size} tech-${t.state} ${t.ahead && t.state !== 'researched' ? 'tech-ahead' : ''}`,
    title: techTitle(t), tabindex: 0,
    style: { left: `${t.x}px`, top: `${t.y}px`, width: `${t.w}px`, height: `${t.h}px`,
      backgroundImage: bg ? `url(${bg})` : 'none' },
  },
  t.icon ? h('img', { class: 'tech-icon', src: t.icon, alt: '', draggable: 'false' }) : null,
  t.size === 'big' ? h('span', { class: 'tech-name' }, t.name) : null,
  t.state === 'researching' && t.progress != null
    ? h('div', { class: 'tech-progress' }, h('div', { style: { width: `${Math.min(100, t.progress * 100)}%` } })) : null,
  t.excludes?.length ? h('span', { class: 'tech-xor', title: `Mutually exclusive with ${t.excludes.map((x) => x.name).join(', ')}` }, 'XOR') : null,
  t.ahead && t.state !== 'researched' && t.start_year ? h('span', { class: 'tech-year' }, t.start_year) : null);
}

function tabStrip(tabs, selected, onPick) {
  return h('div', { class: 'research-tab-strip', role: 'group', 'aria-label': 'Research tabs' }, tabs.map((t) => {
    const b = h('button', {
      type: 'button', class: `research-tab ${t.image ? '' : 'research-tab-text'} ${t.id === selected ? 'research-tab-on' : ''}`,
      'data-tab': t.id, 'aria-pressed': t.id === selected ? 'true' : 'false', 'aria-label': t.name,
      title: [t.name, `${t.technologies} technologies`, CONDITION[t.condition]].filter(Boolean).join(' · '),
      style: t.image ? { backgroundImage: `url(${t.image})` } : {},
    }, t.image ? null : t.name);
    b.addEventListener('click', () => onPick(t.id));
    return b;
  }));
}

/** Research tile: the research screen's tab strip with the technology tree of the selected tab (refreshable).
 *  Picking another tab reloads the tile for it. Returns { el, stop }. */
export function researchTreePanel(ctx, tag) {
  const host = h('div');
  let panel = null;
  const open = (folder) => {
    panel?.stop();
    let scroll = { left: 0, top: 0 };
    panel = livePanel(ctx, {
      title: 'Research tabs & technology tree', id: 'Technology tree', unavailable: 'Technology tree',
      url: `/api/countries/${encodeURIComponent(tag)}/research/tree?folder=${encodeURIComponent(folder ?? '')}`,
      liveParts: (res) => (res.data?.research_source === 'live' ? ['researched, research'] : []),
      render(body, res) {
        const d = res.data;
        if (!d?.items) {
          body.replaceChildren(notice('warn', `Technology tree unavailable: ${res.note}`));
          return;
        }
        const old = body.querySelector('.tech-tree-scroll');
        if (old) scroll = { left: old.scrollLeft, top: old.scrollTop };   // keep the view on a live update
        const tab = d.tabs.find((t) => t.id === d.folder);
        const byId = Object.fromEntries(d.items.map((t) => [t.id, t]));
        const svg = document.createElementNS(SVG, 'svg');
        svg.setAttribute('class', 'tech-lines');
        svg.setAttribute('width', d.width);
        svg.setAttribute('height', d.height);
        d.lines.forEach((l) => {
          const path = document.createElementNS(SVG, 'path');
          path.setAttribute('d', pathOf(l.points));
          path.setAttribute('class', byId[l.from].state === 'researched' ? 'tech-line-done' : 'tech-line');
          svg.append(path);
        });
        const labels = d.labels.map((lb) => h('span', { class: 'tech-label',
          style: { left: `${lb.x}px`, top: `${lb.y}px`, fontSize: `${Math.max(12, Math.round(lb.size * 0.55))}px` } }, lb.text));
        const legend = h('div', { class: 'tech-legend' }, ['researched', 'researching', 'available', 'excluded', 'unavailable']
          .map((st) => h('span', { class: `tech-legend-item tech-legend-${st}` }, STATE_LABEL[st])),
        h('span', { class: 'tech-legend-item tech-legend-ahead' }, 'Year: ahead of time'),
        h('span', { class: 'muted' }, 'Drag with the left mouse button to move around'));
        const view = h('div', { class: 'tech-tree-scroll' },
          h('div', { class: 'tech-tree', style: { width: `${d.width}px`, height: `${d.height}px` } },
            svg, ...labels, ...d.items.map((t) => treeItem(d, t))));
        dragToScroll(view);
        body.replaceChildren(
          tabStrip(d.tabs, d.folder, (id) => { writeTab(id); open(id); }),
          h('div', { class: 'research-tab-info' }, h('strong', null, tab?.name ?? d.folder),
            h('span', { class: 'muted' }, ` · ${d.items.length} technologies`)),
          legend, view);
        view.scrollLeft = scroll.left;
        view.scrollTop = scroll.top;
      },
    });
    host.replaceChildren(panel.el);
  };
  open(readTab());
  return { el: host, stop: () => panel?.stop() };
}

export default {
  id: 'research',
  title: 'Research',
  short: 'RS',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const picker = await countryPicker(ctx);
    const tiles = [researchPanel(ctx, tag), researchTreePanel(ctx, tag)];
    root.append(
      viewHeader('Research', 'Research slots of the selected country and what each one researches.', picker),
      h('div', { class: 'country-head research-head' }, tagChip(tag, 'tag-chip-lg')),
      ...tiles.map((t) => t.el));
    return () => tiles.forEach((t) => t.stop());
  },
};
