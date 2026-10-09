import { h, card, demoBanner, meter, notice, sourceBadge, toast, viewHeader } from '../lib/dom.js';
import { FOCUS_COLUMNS, formatAge, freshnessInfo, groupFocuses } from '../lib/format.js';
import { focusStatuses } from '../lib/focus-status.js';
import { countryPicker } from './shared.js';

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

/** The tree laid out like in game (x/y from the focus files); click a focus to add it to / remove it from the queue. */
function treeView(focuses, queue, onToggle) {
  const minX = Math.min(...focuses.map((f) => f.x));
  const maxX = Math.max(...focuses.map((f) => f.x));
  const maxY = Math.max(...focuses.map((f) => f.y));
  const pos = new Map(focuses.map((f) => [f.id, { left: (f.x - minX) * CELL_W, top: f.y * CELL_H }]));
  const queued = new Map(queue.map((q, i) => [q.id, { ...q, n: i + 1 }]));
  const width = (maxX - minX + 1) * CELL_W;
  const height = (maxY + 1) * CELL_H;
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('class', 'focus-lines');
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  for (const f of focuses) {
    for (const group of f.prerequisites) {
      for (const p of group) {
        const a = pos.get(p);
        const b = pos.get(f.id);
        if (!a || !b) continue;
        const line = document.createElementNS(svgNS, 'line');
        line.setAttribute('x1', String(a.left + CELL_W / 2));
        line.setAttribute('y1', String(a.top + CELL_H - 14));
        line.setAttribute('x2', String(b.left + CELL_W / 2));
        line.setAttribute('y2', String(b.top + 6));
        if (group.length > 1) line.setAttribute('stroke-dasharray', '4 3'); // one of several
        svg.append(line);
      }
    }
  }
  const nodes = focuses.map((f) => {
    const q = queued.get(f.id);
    const p = pos.get(f.id);
    return h('button', {
      class: `focus-node focus-${f.status}${q ? (q.ok ? ' focus-queued' : ' focus-queued-bad') : ''}`,
      style: { left: `${p.left + 4}px`, top: `${p.top + 4}px`, width: `${CELL_W - 8}px`, height: `${CELL_H - 18}px` },
      title: `${f.name}\n${f.id}\n${STATUS_LABEL[f.status] ?? f.status} · ${f.days} days`
        + (f.missing?.length ? `\nneeds ${f.missing.map((g) => g.join(' or ')).join(' and ')}` : '')
        + (f.exclusive?.length ? `\nexcludes ${f.exclusive.join(', ')}` : '')
        + (f.has_conditions ? '\nhas game conditions the app cannot check' : '')
        + (q ? `\nqueue #${q.n}${q.ok ? '' : ` - ${q.reason}`}` : ''),
      onClick: () => onToggle(f),
    }, q ? h('span', { class: 'focus-qn' }, String(q.n)) : null, h('span', { class: 'focus-node-name' }, f.name),
    f.status === 'in_progress' ? meter(f.progress ?? 0) : null);
  });
  return h('div', { class: 'focus-tree-scroll' },
    h('div', { class: 'focus-tree', style: { width: `${width}px`, height: `${height}px` } }, svg, ...nodes));
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
    if (res.source !== 'save') {
      root.append(...[header, demoBanner(res.note), res.data.focuses.length ? demoView(res) : notice('muted', `No focus data for ${tag}.`)]);
      return undefined;
    }
    const d = res.data;
    const byId = new Map(d.focuses.map((f) => [f.id, f]));
    let queue = d.queue;
    const treeHost = h('div');
    const queueHost = h('div');
    const fresh = freshnessInfo(d.freshness?.category);
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
    let liveTimer = null;
    const pollLive = async () => {
      try {
        const live = (await ctx.api.get(`/api/live/focus?tag=${encodeURIComponent(tag)}`)).data;
        showCurrent(live);
        applyLive(live);
      } catch { /* live reading unavailable - keep the save snapshot */ }
      liveTimer = setTimeout(pollLive, 4000);
    };
    pollLive();

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
    // Live memory: focuses completed since the save turn green and their successors silver without a new save.
    const savedCompleted = new Set(d.focuses.filter((f) => f.status === 'completed').map((f) => f.id));
    let liveKey = null;
    function applyLive(live) {
      if (live.loading) return;
      const key = `${live.current}|${(live.completed_since_save ?? []).join(',')}`;
      if (key === liveKey) return;
      liveKey = key;
      const completed = new Set([...savedCompleted, ...(live.completed_since_save ?? [])]);
      const statuses = focusStatuses(d.focuses, completed, live.current);
      for (const f of d.focuses) f.status = statuses.get(f.id);
      render();
    }
    function render() {
      const scroller = treeHost.querySelector('.focus-tree-scroll');
      const keep = scroller ? [scroller.scrollLeft, scroller.scrollTop] : null;
      treeHost.replaceChildren(treeView(d.focuses, queue, toggle));
      if (keep) { const s2 = treeHost.querySelector('.focus-tree-scroll'); [s2.scrollLeft, s2.scrollTop] = keep; }
      queueHost.replaceChildren(queueList(byId, queue, save, move, remove));
    }
    render();
    const counts = groupFocuses(d.focuses);

    root.append(
      header,
      h('div', { class: `save-banner ${fresh.cls}`, role: 'note' },
        h('div', { class: 'save-banner-line' }, sourceBadge('save'), h('strong', null, d.file.name),
          d.in_game_date ? h('span', null, 'In-game date ', h('b', null, d.in_game_date.text)) : null,
          h('span', { class: 'muted' }, `file written ${new Date(d.file.modified).toLocaleString()} (${formatAge(d.freshness?.age_s)})`)),
        h('div', { class: 'fresh' }, `SNAPSHOT - ${d.freshness?.label ?? fresh.short}`)),
      h('div', { class: 'split' },
        card('Current focus', currentHost),
        card(`Planned order (${queue.length})`, [queueHost,
          notice('info', 'The plan is checked against prerequisites and exclusions. When the current focus ends, the app '
            + 'notifies you which one to start next (the game has no command that starts a focus; focuses are never '
            + 'completed instantly).')])),
      card(`Tree ${d.tree} - ${d.focuses.length} focuses (${counts.completed?.length ?? 0} completed, `
        + `${counts.available?.length ?? 0} available)`, [
        h('p', { class: 'hint' }, 'Green: completed · pulsing yellow: in progress · silver: can be taken next · grey: not yet '
          + 'possible (dark grey: excluded by an earlier choice). Click a focus to add it to the plan or remove it. Dashed '
          + 'lines: one of several prerequisites. Silver means the prerequisites are met - the game may still require other conditions.'),
        treeHost]),
    );
    return () => clearTimeout(liveTimer);
  },
};
