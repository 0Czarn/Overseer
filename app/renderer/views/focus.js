import { h, card, demoBanner, meter, notice, sourceBadge, toast, viewHeader } from '../lib/dom.js';
import { FOCUS_COLUMNS, formatAge, freshnessInfo, groupFocuses } from '../lib/format.js';
import { countryPicker } from './shared.js';
import { dragToScroll, pathOf } from './research.js';
import { dataKey, refreshControl } from '../lib/refresh.js';
import { autostartEnabled, setAutostartEnabled } from '../lib/focus-autostart.js';
import { readZoom, zoomable } from '../lib/zoom.js';

const CELL_W = 118;
const CELL_H = 74;
const STATUS_LABEL = { completed: 'Completed', in_progress: 'In progress', available: 'Available', blocked: 'Blocked',
  excluded: 'Excluded' };

function demoCard(focus) {
  return h('div', { class: `focus focus-${focus.status}` },
    h('div', { class: 'focus-name' }, focus.name),
    h('code', { class: 'focus-id' }, focus.id),
    h('div', { class: 'focus-meta' }, `${focus.days} days`),
    focus.status === 'in_progress' ? meter(focus.progress ?? 0) : null);
}

function demoView(res) {
  const groups = groupFocuses(res.data.focuses);
  return h('div', { class: 'kanban' }, FOCUS_COLUMNS.map((col) => card(`${col.label} (${groups[col.status].length})`,
    groups[col.status].length ? groups[col.status].map(demoCard) : h('p', { class: 'muted' }, 'None'))));
}

/** Tooltip text of a focus: name, description from the game, time, prerequisites, exclusions, plan position. */
export function focusTitle(f, q, byId = new Map()) {
  const name = (id) => byId.get(id)?.name ?? id;
  return [
    `${f.name} (${STATUS_LABEL[f.status] ?? f.status})`,
    f.desc,
    `${f.days} days`,
    f.missing?.length ? `Needs: ${f.missing.map((g) => g.map(name).join(' or ')).join(' and ')}` : '',
    f.exclusive?.length ? `Mutually exclusive with: ${f.exclusive.map(name).join(', ')}` : '',
    f.has_conditions ? 'Has game conditions the app cannot check' : '',
    q ? `Plan #${q.n}${q.ok ? '' : ` - ${q.reason}`}` : '',
    f.id,
  ].filter(Boolean).join('\n');
}

/** The tree laid out like the game's focus screen (positions, lines and exclusive links from the backend);
 *  drag with the left mouse button to move around; click a focus to add it to / remove it from the plan. */
function treeView(d, queue, onToggle) {
  const L = d.layout;
  const N = L.node;
  const byId = new Map(d.focuses.map((f) => [f.id, f]));
  const queued = new Map(queue.map((q, i) => [q.id, { ...q, n: i + 1 }]));
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('class', 'ftree-lines');
  svg.setAttribute('width', String(L.width));
  svg.setAttribute('height', String(L.height));
  for (const l of L.lines) {
    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', pathOf(l.points));
    const done = byId.get(l.from)?.status === 'completed';
    path.setAttribute('class', `ftree-line${done ? ' ftree-line-done' : ''}${l.alternative ? ' ftree-line-alt' : ''}`);
    svg.append(path);
  }
  for (const x of L.exclusive) {
    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', pathOf(x.points));
    path.setAttribute('class', 'ftree-exclusive');
    svg.append(path);
  }
  const links = L.exclusive.map((x) => (d.exclusive_icon
    ? h('img', { class: 'ftree-xicon', src: d.exclusive_icon, alt: '', draggable: 'false',
      title: `Mutually exclusive: ${byId.get(x.a)?.name ?? x.a} / ${byId.get(x.b)?.name ?? x.b}`,
      style: { left: `${x.at[0] - 16}px`, top: `${x.at[1] - 16}px` } })
    : h('span', { class: 'ftree-xicon ftree-xicon-text', style: { left: `${x.at[0] - 8}px`, top: `${x.at[1] - 10}px` } }, '!')));
  const nodes = L.items.map((it) => {
    const f = byId.get(it.id);
    const q = queued.get(f.id);
    const icon = f.icon_key ? d.icons[f.icon_key] : null;
    const plate = d.plates?.[f.status];
    return h('button', {
      type: 'button',
      class: `fnode fnode-${f.status}${q ? (q.ok ? ' fnode-queued' : ' fnode-queued-bad') : ''}`,
      'data-focus': f.id,
      style: { left: `${it.left}px`, top: `${it.top}px`, width: `${N.w}px`, height: `${N.h}px` },
      title: focusTitle(f, q, byId),
      onClick: (e) => { if (!e.currentTarget.closest('.ftree-scroll')?.dataset.dragged) onToggle(f); },
    },
    icon ? h('img', { class: 'fnode-icon', src: icon, alt: '', draggable: 'false', style: { height: `${N.icon_h}px` } })
      : h('span', { class: 'fnode-icon fnode-icon-none', style: { height: `${N.icon_h}px` } }),
    h('span', { class: 'fnode-plate', style: { top: `${N.plate_top}px`, height: `${N.plate_h}px`,
      backgroundImage: plate ? `url(${plate})` : 'none' } }, h('span', { class: 'fnode-name' }, f.name)),
    f.status === 'in_progress' ? h('span', { class: 'fnode-progress' },
      h('span', { style: { width: `${Math.min(100, (f.progress ?? 0) * 100)}%` } })) : null,
    q ? h('span', { class: 'fnode-qn' }, String(q.n)) : null);
  });
  const content = h('div', { class: 'ftree', style: { width: `${L.width}px`, height: `${L.height}px` } }, svg, ...links, ...nodes);
  const view = h('div', { class: 'ftree-scroll' });
  const zoom = zoomable('focus', view, content, L.width, L.height);
  view.append(zoom.sizer);
  dragToScroll(view);
  return h('div', null, zoom.toolbar, view);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];   // the game has no leap years

/** "23 Jun 1936" - `days` after the game date {year, day: 0-based day of the year}. */
export function gameDateText(date, days) {
  if (!date) return '';
  const year = date.year + Math.floor((date.day + days) / 365);
  let day = (date.day + days) % 365;
  let m = 0;
  while (day >= MONTH_DAYS[m]) { day -= MONTH_DAYS[m]; m += 1; }
  return `${day + 1} ${MONTHS[m]} ${year}`;
}

/** Plan timeline: each valid queued focus starts when the one before it ends (the current one first). Returns
 *  { items: [{ ...q, n, focus, start, end, next, manual }], total } (start/end in days from now; null for invalid
 *  entries). Focuses needing a manual start are marked (the app's auto-start leaves them to the player). */
export function planTimeline(queue, byId, current, progressDays) {
  const cur = current ? byId.get(current) : null;
  let at = cur ? Math.max(0, cur.days - (progressDays ?? 0)) : 0;
  let nextFound = false;
  const items = queue.map((q, i) => {
    const f = byId.get(q.id);
    if (!q.ok || !f) return { ...q, n: i + 1, focus: f, start: null, end: null, next: false, manual: false };
    const item = { ...q, n: i + 1, focus: f, start: at, end: at + f.days, next: !nextFound,
      // conditions: the focus's `available` checked on game memory (true / false / null = the app cannot tell;
      // undefined = not checked, e.g. from a save)
      manual: Boolean(f.select_effect || (f.start_conditions && (q.conditions === null || q.conditions === undefined))),
      waiting: q.conditions === false };
    nextFound = true;
    at += f.days;
    return item;
  });
  return { items, total: at };
}

function queueList(d, byId, queue, move, remove) {
  if (!queue.length) {
    return h('div', { class: 'plan-empty' }, h('strong', null, 'No focuses planned yet'),
      h('span', { class: 'muted' }, 'Click focuses in the tree below to add them here in the order you want to take them.'));
  }
  const { items, total } = planTimeline(queue, byId, d.current, d.progress_days);
  const bad = items.filter((x) => !x.ok).length;
  const summary = h('div', { class: 'plan-summary' },
    h('span', null, h('b', null, items.length), ` focus${items.length === 1 ? '' : 'es'} planned`),
    h('span', null, h('b', null, total), ' days'),
    d.game_date ? h('span', null, 'plan ends ', h('b', null, gameDateText(d.game_date, total))) : null,
    bad ? h('span', { class: 'plan-bad-count' }, `${bad} cannot follow - see red`) : null);
  const rows = items.map((x, i) => {
    const f = x.focus;
    const icon = f?.icon_key ? d.icons?.[f.icon_key] : null;
    const range = d.game_date ? `${gameDateText(d.game_date, x.start)} → ${gameDateText(d.game_date, x.end)}` : `starts in ${x.start} days`;
    const when = x.ok ? `${f.days} days · ${range}` : x.reason;
    return h('li', { class: `plan-row${x.ok ? '' : ' plan-row-bad'}${x.next ? ' plan-row-next' : ''}` },
      h('span', { class: 'plan-n' }, x.n),
      icon ? h('img', { class: 'plan-icon', src: icon, alt: '' }) : h('span', { class: 'plan-icon' }),
      h('div', { class: 'plan-main' },
        h('div', { class: 'plan-name' }, f?.name ?? x.id,
          x.next ? h('span', { class: 'plan-badge plan-badge-next' }, 'NEXT') : null,
          x.manual ? h('span', { class: 'plan-badge plan-badge-manual', title: 'Has conditions the app cannot check'
            + (x.unknown?.length ? ` (${x.unknown.join(', ')})` : '') + ' or effects when picked: start it yourself in the game '
            + '(auto-start leaves it to you)' }, 'START IN GAME') : null,
          x.waiting ? h('span', { class: 'plan-badge plan-badge-manual', title: 'Its conditions (available) are not met in '
            + 'the game now - auto-start waits until they are' }, 'CONDITIONS NOT MET') : null),
        h('div', { class: 'plan-when' }, when)),
      h('span', { class: 'plan-btns' },
        h('button', { class: 'btn btn-small btn-ghost', disabled: i === 0, onClick: () => move(i, -1), 'aria-label': 'Move up', title: 'Move up' }, '↑'),
        h('button', { class: 'btn btn-small btn-ghost', disabled: i === items.length - 1, onClick: () => move(i, 1), 'aria-label': 'Move down', title: 'Move down' }, '↓'),
        h('button', { class: 'btn btn-small btn-ghost', onClick: () => remove(i), 'aria-label': 'Remove', title: 'Remove from the plan' }, '✕')));
  });
  return h('div', null, summary, h('ol', { class: 'plan-list focus-queue' }, rows));
}

const AUTO_STATE = { busy: 'a focus is in progress - the next one starts when it ends',
  empty: 'no valid focus in your plan', ready: 'would start now', manual: 'next one must be started in the game',
  waiting: 'its conditions are not met yet - waiting',
  started: 'started' };

/** "Auto-start the next focus" switch with what it would do now (your country only, single player). */
function autostartSwitch(ctx) {
  const info = h('span', { class: 'muted cons-sort-info' });
  const box = h('input', { type: 'checkbox', checked: autostartEnabled() });
  const preview = async () => {
    try {
      const r = await ctx.api.get('/api/live/focus/autostart');
      info.textContent = `${r.tag}: ${r.name ? `${r.name} - ` : ''}${r.state === 'manual' ? r.reason : AUTO_STATE[r.state] ?? r.state}`;
    } catch (err) {
      info.textContent = `Not available: ${err.message}`;
    }
  };
  box.addEventListener('change', () => { setAutostartEnabled(box.checked); preview(); });
  preview();
  return h('div', { class: 'cons-sort' },
    h('label', { class: 'cons-sort-label', title: 'Your country only; single player, or multiplayer when allowed in Options. '
      + 'When no focus is selected, the app starts the next valid focus of this plan by writing game memory on this computer '
      + '(0 days: saved days are dropped, no political power is taken). Its conditions (available) are checked on game '
      + 'memory first; focuses with conditions the app cannot check or with effects on picking are left to you - you get a notice.' },
    box, h('span', null, 'Auto-start the next focus of the plan')), info);
}

export default {
  id: 'focus',
  title: 'National Focus Manager',
  short: 'NF',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const [res, picker] = await Promise.all([ctx.api.get(`/api/focus/${encodeURIComponent(tag)}`), countryPicker(ctx)]);
    const header = viewHeader('National Focus Manager', 'Focus tree of the selected country, its state and your planned order.',
      picker, sourceBadge(res.source, res.note));
    if (res.source !== 'save' && res.source !== 'live') {
      root.append(...[header, demoBanner(res.note), res.data.focuses.length ? demoView(res) : notice('muted', `No focus data for ${tag}.`)]);
      return undefined;
    }
    const d = res.data;
    const byId = new Map(d.focuses.map((f) => [f.id, f]));
    let queue = d.queue;
    const treeHost = h('div');
    const queueHost = h('div');
    const fresh = freshnessInfo(d.freshness?.category ?? 'current_session');
    const currentHost = h('div');
    const showCurrent = (live) => {
      const id = live ? live.current : d.current;
      const f = byId.get(id ?? '');
      const days = live ? live.progress_days : d.progress_days;
      currentHost.replaceChildren(...[
        live ? h('span', { class: 'badge badge-live' }, 'LIVE') : sourceBadge('save'),
        f ? [h('div', { class: 'focus-name' }, f.name), h('code', { class: 'focus-id' }, f.id),
          meter(f.days ? Math.min(1, days / f.days) : 0),
          h('div', { class: 'focus-meta' }, `${Math.round(days)} of ${f.days} days${!live && d.paused ? ' · paused' : ''}`)]
          : notice('warn', 'No focus in progress - start one in the game.'),
        live?.next ? h('p', { class: 'hint' }, `Next in your plan: ${live.next.name} (${live.next.days} days)`) : null,
      ].flat().filter(Boolean));
    };
    showCurrent(null);
    const save = async (ids) => {
      try {
        queue = (await ctx.api.post(`/api/focus/${encodeURIComponent(tag)}/queue`, { queue: ids })).data;
        render();
      } catch (err) { toast(err.message, 'error'); }
    };
    const ids = () => queue.map((q) => q.id);
    const toggle = (f) => {
      if (['completed', 'in_progress'].includes(f.status)) { toast(`${f.name} is already ${STATUS_LABEL[f.status].toLowerCase()}`); return; }
      save(ids().includes(f.id) ? ids().filter((x) => x !== f.id) : [...ids(), f.id]);
    };
    const move = (i, step) => { const next = ids(); [next[i], next[i + step]] = [next[i + step], next[i]]; save(next); };
    const remove = (i) => save(ids().filter((_, j) => j !== i));
    // Live / On refresh: re-reads only the state of the tree (statuses, current focus, plan) - the graphics stay.
    // Another tree (e.g. the country switched trees) reloads the whole view.
    let stateKey = null;
    const sourceText = h('span', { class: 'hoi-status' });
    async function refreshState(force) {
      try {
        const r = await ctx.api.get(`/api/focus/${encodeURIComponent(tag)}/state`);
        const st = r.data;
        if (!st) { sourceText.textContent = r.note ?? ''; return; }
        if (st.tree !== d.tree) { ctx.rerender(); return; }
        sourceText.textContent = `${st.focus_source === 'live' ? 'game memory' : 'save'} · read ${new Date().toLocaleTimeString()}`;
        sourceText.className = `hoi-status ${st.focus_source === 'live' ? 'hoi-status-on' : ''}`.trim();
        showCurrent(st.focus_source === 'live' ? st : null);
        const key = dataKey({ s: st.statuses, q: st.queue, c: st.current, p: Math.round(st.progress_days) });
        if (!force && key === stateKey) return;
        stateKey = key;
        for (const f of d.focuses) Object.assign(f, st.statuses[f.id] ?? {});
        d.current = st.current;
        d.progress_days = st.progress_days;
        d.game_date = st.game_date ?? d.game_date;
        queue = st.queue;
        render();
        countsHost.textContent = treeTitle();
      } catch (err) {
        sourceText.textContent = `not read: ${err.message}`;
        sourceText.className = 'hoi-status';
      }
    }
    const control = refreshControl('Focus tree', 'Focus tree', refreshState);
    const countsHost = h('span');
    const treeTitle = () => {
      const c = groupFocuses(d.focuses);
      return `Tree ${d.tree} - ${d.focuses.length} focuses (${c.completed?.length ?? 0} completed, ${c.available?.length ?? 0} available)`;
    };
    // first view: the focus in progress (else the first available one) in the middle, like the game opens
    function centreOnCurrent(el) {
      const f = d.focuses.find((x) => x.status === 'in_progress') ?? d.focuses.find((x) => x.status === 'available');
      const it = f && d.layout.items.find((i) => i.id === f.id);
      if (!it) return;
      const z = readZoom('focus');
      requestAnimationFrame(() => {
        el.scrollLeft = Math.max(0, (it.left + d.layout.node.w / 2) * z - el.clientWidth / 2);
        el.scrollTop = Math.max(0, it.top * z - 40);
      });
    }
    function render() {
      const scroller = treeHost.querySelector('.ftree-scroll');
      const keep = scroller ? [scroller.scrollLeft, scroller.scrollTop] : null;
      treeHost.replaceChildren(treeView(d, queue, toggle));
      const s2 = treeHost.querySelector('.ftree-scroll');
      if (keep) [s2.scrollLeft, s2.scrollTop] = keep;
      else centreOnCurrent(s2);
      queueHost.replaceChildren(queueList(d, byId, queue, move, remove));
    }
    render();
    countsHost.textContent = treeTitle();

    root.append(
      header,
      d.file ? h('div', { class: `save-banner ${fresh.cls}`, role: 'note' },
        h('div', { class: 'save-banner-line' }, sourceBadge('save'), h('strong', null, d.file.name),
          d.in_game_date ? h('span', null, 'In-game date ', h('b', null, d.in_game_date.text)) : null,
          h('span', { class: 'muted' }, `file written ${new Date(d.file.modified).toLocaleString()} (${formatAge(d.freshness?.age_s)})`)),
        h('div', { class: 'fresh' }, `SNAPSHOT - ${d.freshness?.label ?? fresh.short}`))
        : h('p', { class: 'hint' }, h('span', { class: 'badge badge-live' }, 'LIVE'), ` Tree ${d.tree} and its state read from game memory - no save needed.`),
      h('div', { class: 'split' },
        card('Current focus', currentHost),
        card('Planned order', [autostartSwitch(ctx), queueHost,
          h('p', { class: 'hint plan-hint' }, 'Checked against prerequisites and exclusions. Dates follow the game date and '
            + 'assume each focus starts when the one before it ends. When a focus ends the app tells you the next one - '
            + 'or starts it itself with auto-start on.')])),
      card(countsHost, [
        h('p', { class: 'hint' }, 'Laid out like the game. Gold name plate: completed · pulsing: in progress · silver-blue plate: can be '
          + 'taken next · dark plate, grey icon: not yet possible (faded: excluded by an earlier choice). Red link: mutually exclusive '
          + 'focuses. Dashed lines: one of several prerequisites. Drag to move around; click a focus to add it to the plan or '
          + 'remove it; hover for its description. The game may still require conditions the app cannot check.'),
        treeHost], { extra: h('span', { class: 'hoi-head-right' }, sourceText, control.el) }),
    );
    refreshState(true);
    return () => control.stop();
  },
};
