import { h, card, demoBanner, meter, notice, sourceBadge, toast, viewHeader } from '../lib/dom.js';
import { FOCUS_COLUMNS, formatAge, freshnessInfo, groupFocuses } from '../lib/format.js';
import { countryPicker } from './shared.js';
import { dragToScroll, pathOf } from './research.js';
import { dataKey, refreshControl } from '../lib/refresh.js';

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
  const view = h('div', { class: 'ftree-scroll' },
    h('div', { class: 'ftree', style: { width: `${L.width}px`, height: `${L.height}px` } }, svg, ...links, ...nodes));
  dragToScroll(view);
  return view;
}

function queueList(byId, queue, save, move, remove) {
  if (!queue.length) return notice('muted', 'Queue is empty - click focuses in the tree to plan the order.');
  return h('ol', { class: 'focus-queue' }, queue.map((q, i) => h('li', { class: q.ok ? '' : 'bad-text' },
    h('span', { class: 'focus-queue-name' }, byId.get(q.id)?.name ?? q.id),
    h('span', { class: 'muted' }, q.ok ? ` · ${byId.get(q.id)?.days ?? '?'} days${q.conditions ? ' · game conditions not checked' : ''}` : ` · ${q.reason}`),
    h('span', { class: 'btn-row' },
      h('button', { class: 'btn btn-small btn-ghost', disabled: i === 0, onClick: () => move(i, -1), 'aria-label': 'Up' }, '↑'),
      h('button', { class: 'btn btn-small btn-ghost', disabled: i === queue.length - 1, onClick: () => move(i, 1), 'aria-label': 'Down' }, '↓'),
      h('button', { class: 'btn btn-small btn-ghost', onClick: () => remove(i), 'aria-label': 'Remove' }, '✕')))));
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
      requestAnimationFrame(() => {
        el.scrollLeft = Math.max(0, it.left - el.clientWidth / 2 + d.layout.node.w / 2);
        el.scrollTop = Math.max(0, it.top - 40);
      });
    }
    function render() {
      const scroller = treeHost.querySelector('.ftree-scroll');
      const keep = scroller ? [scroller.scrollLeft, scroller.scrollTop] : null;
      treeHost.replaceChildren(treeView(d, queue, toggle));
      const s2 = treeHost.querySelector('.ftree-scroll');
      if (keep) [s2.scrollLeft, s2.scrollTop] = keep;
      else centreOnCurrent(s2);
      queueHost.replaceChildren(queueList(byId, queue, save, move, remove));
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
        card(`Planned order (${queue.length})`, [queueHost,
          notice('info', 'The plan is checked against prerequisites and exclusions. When the current focus ends, the app '
            + 'notifies you which one to start next (the game has no command that starts a focus; focuses are never '
            + 'completed instantly).')])),
      card(countsHost, [
        h('p', { class: 'hint' }, 'Laid out like the game. Gold name plate: completed · pulsing: in progress · silver-blue plate: can be '
          + 'taken next · red plate: not yet possible (darker: excluded by an earlier choice). Red link: mutually exclusive '
          + 'focuses. Dashed lines: one of several prerequisites. Drag to move around; click a focus to add it to the plan or '
          + 'remove it; hover for its description. The game may still require conditions the app cannot check.'),
        treeHost], { extra: h('span', { class: 'hoi-head-right' }, sourceText, control.el) }),
    );
    refreshState(true);
    return () => control.stop();
  },
};
