// Compare tile at the bottom of Army/Air/Navy (2026-10-20, user's request): up to four division templates, tank designs
// or plane designs of any countries side by side, read live from game memory (/api/countries/<TAG>/military). The
// first column is the reference: the others show their value and the difference to it.
import { h, notice } from '../lib/dom.js';
import { loadCountries, pinFavourite } from './shared.js';
import { loadOptions } from '../lib/options.js';
import { designerIcon } from '../lib/icons.js';
import { DESIGNER_GROUPS, PLANE_GROUPS, TANK_GROUPS, cut, mioOf } from './military.js';

export const MAX_COLUMNS = 4;
/** "Basic Heavy Tank Destroyer · Henschel" - a design's type and its MIO (military response "mios"). */
export const designNote = (x, d) => [x.type_name, mioOf(x, d.mios ?? {})?.name].filter(Boolean).join(' · ');
const PREFS_KEY = 'hoi4dbg.compare';
const COST = ['build_cost_ic', 'Production Cost', (v) => cut(v, 2)];
// [kind, label, rows of [key, label, format], items of a military response]
export const KINDS = {
  divisions: { label: 'Division templates', groups: [...DESIGNER_GROUPS, ['Cost', [
    ['cost_max', 'Production Cost', (v) => cut(v, 0)], ['fuel_capacity', 'Fuel Capacity', (v) => cut(v, 1)],
    ['fuel_usage', 'Fuel Usage', (v) => cut(v, 2)]]]],
  items: (d) => (d.army?.templates ?? []).filter((t) => t.designer?.stats).map((t) => ({ id: t.name, name: t.name,
    note: `${t.count} division${t.count === 1 ? '' : 's'}`,
    stats: { ...t.designer.stats, ...(t.designer.cost ? { cost_max: t.designer.cost.cost_max, fuel_capacity: t.designer.cost.fuel_capacity,
      fuel_usage: t.designer.cost.fuel_usage } : {}) } })) },
  tanks: { label: 'Tank designs', groups: [...TANK_GROUPS, ['Cost', [COST]]],
    items: (d) => (d.army?.tank_designs ?? []).filter((x) => !x.outdated).map((x) => ({ id: String(x.id), name: x.name, note: designNote(x, d), stats: x.stats })) },
  planes: { label: 'Plane designs', groups: [...PLANE_GROUPS, ['Cost', [COST]]],
    items: (d) => (d.air?.designs ?? []).filter((x) => !x.outdated).map((x) => ({ id: String(x.id), name: x.name, note: designNote(x, d), stats: x.stats })) },
};

// stats where less is better (a green arrow for less); combat width depends on the plan: neutral (no colour)
export const LOWER_BETTER = new Set(['build_cost_ic', 'cost_max', 'supply_consumption', 'weight', 'fuel_consumption', 'fuel_usage',
  'training_time', 'manpower', 'experience_loss_factor']);
export const NEUTRAL = new Set(['combat_width']);

/** {arrow: "▲" | "▼" | "", tone: "good" | "bad" | "same" | "neutral"} of a value against the reference: the arrow is
 * more / less, the tone better / worse for this stat. */
export function diffTone(key, value, reference) {
  if (value == null || reference == null) return { arrow: '', tone: 'neutral' };
  const d = value - reference;
  if (Math.abs(d) < 1e-9) return { arrow: '', tone: 'same' };
  if (NEUTRAL.has(key)) return { arrow: d > 0 ? '▲' : '▼', tone: 'neutral' };
  const better = LOWER_BETTER.has(key) ? d < 0 : d > 0;
  return { arrow: d > 0 ? '▲' : '▼', tone: better ? 'good' : 'bad' };
}

/** "+1.5" / "−0.30" / "=" - a value against the reference column, in the row's own format. */
export function diffText(value, reference, format) {
  if (value == null || reference == null) return '';
  const d = value - reference;
  if (Math.abs(d) < 1e-9) return '=';
  const text = format(Math.abs(d));
  return `${d > 0 ? '+' : '−'}${text}`;
}

function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {};
    return { kind: KINDS[p.kind] ? p.kind : 'divisions', columns: Array.isArray(p.columns) ? p.columns.slice(0, MAX_COLUMNS) : [] };
  } catch {
    return { kind: 'divisions', columns: [] };
  }
}
function savePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* preference only */ }
}

export function comparePanel(ctx, tag) {
  const prefs = loadPrefs();
  const cache = new Map();   // tag -> military data (read once a tile life; ↻ reads again)
  const body = h('div', { class: 'cmp-body' }, h('span', { class: 'muted' }, 'Reading…'));
  let countries = [];

  async function military(t, force = false) {
    if (!force && cache.has(t)) return cache.get(t);
    const p = ctx.api.get(`/api/countries/${encodeURIComponent(t)}/military`).then((r) => r.data ?? null, () => null);
    cache.set(t, p);
    return p;
  }

  function columns() {
    if (!prefs.columns.length) prefs.columns = [{ tag, id: null }];
    return prefs.columns;
  }

  async function render(force = false) {
    const kind = KINDS[prefs.kind];
    const cols = columns();
    const datas = await Promise.all(cols.map((c) => military(c.tag, force)));
    const lists = datas.map((d) => (d ? kind.items(d) : null));
    cols.forEach((c, i) => { if (lists[i] && !lists[i].some((x) => x.id === c.id)) c.id = lists[i][0]?.id ?? null; });
    savePrefs(prefs);
    const fav = loadOptions().favCountry;
    const countryOptions = pinFavourite(countries.filter((c) => c.exists !== false), fav);
    const head = cols.map((c, i) => h('th', { class: 'cmp-col' },
      h('select', { class: 'input input-small', 'aria-label': `Country ${i + 1}`, onchange: (e) => { c.tag = e.target.value; c.id = null; render(); } },
        countryOptions.map((x) => h('option', { value: x.tag, selected: x.tag === c.tag }, `${x.tag} - ${x.name}`))),
      lists[i] ? h('select', { class: 'input input-small', 'aria-label': `${kind.label} ${i + 1}`, onchange: (e) => { c.id = e.target.value; render(); } },
        lists[i].map((x) => h('option', { value: x.id, selected: x.id === c.id }, x.name))) : h('span', { class: 'muted' }, 'not readable'),
      h('span', { class: 'cmp-note muted' }, lists[i]?.find((x) => x.id === c.id)?.note ?? ''),
      i ? h('button', { class: 'btn btn-small btn-ghost', title: 'Remove this column', onclick: () => { cols.splice(i, 1); render(); } }, '✕')
        : h('span', { class: 'cmp-ref' }, 'reference')));
    const items = cols.map((c, i) => lists[i]?.find((x) => x.id === c.id) ?? null);
    const rows = [];
    for (const [title, group] of kind.groups) {
      const present = group.filter(([k]) => items.some((x) => x?.stats?.[k] != null));
      if (!present.length) continue;
      rows.push(h('tr', { class: 'cmp-group' }, h('th', { colspan: String(cols.length + 1) }, title)));
      for (const [k, label, f] of present) {
        const ref = items[0]?.stats?.[k];
        rows.push(h('tr', null, h('th', { class: 'cmp-label' }, h('span', { class: 'cmp-label-in' }, designerIcon(label), label)), ...items.map((x, i) => {
          const v = x?.stats?.[k];
          if (!i || v == null) return h('td', { class: 'num' }, v == null ? '—' : f(v));
          const { arrow, tone } = diffTone(k, v, ref);
          return h('td', { class: `num cmp-cell cmp-${tone}` }, f(v),
            h('span', { class: 'cmp-diff', title: tone === 'good' ? 'Better than the reference' : tone === 'bad' ? 'Worse than the reference' : '' },
              arrow ? h('span', { class: 'cmp-arrow' }, arrow) : null, diffText(v, ref, f)));
        })));
      }
    }
    body.replaceChildren(
      h('div', { class: 'mil-view cmp-kinds' }, Object.entries(KINDS).map(([k, v]) => h('button', {
        class: `mil-view-btn ${prefs.kind === k ? 'mil-view-on' : ''}`, 'aria-pressed': String(prefs.kind === k),
        onclick: () => { prefs.kind = k; cols.forEach((c) => { c.id = null; }); render(); } }, v.label))),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table cmp-table' },
        h('thead', null, h('tr', null, h('th', null, ''), ...head)),
        h('tbody', null, rows.length ? rows : h('tr', null, h('td', { colspan: String(cols.length + 1), class: 'muted' }, 'Nothing to compare'))))),
      h('div', { class: 'cmp-actions' },
        cols.length < MAX_COLUMNS ? h('button', { class: 'btn btn-small', onclick: () => { cols.push({ tag: cols[cols.length - 1].tag, id: null }); render(); } },
          '+ Add column') : null,
        h('button', { class: 'btn btn-small btn-ghost', title: 'Read the countries again from game memory', onclick: () => render(true) }, '↻ Read again')),
      h('p', { class: 'hint' }, 'From game memory (the game must run). The first column is the reference; the others show their value and '
        + 'the difference to it - a green arrow is better, a red one worse (less is better for cost, supply use, weight, fuel, training time, manpower and experience loss; combat width has no colour). Division stats as the division designer of each country (its research and doctrines); only current '
        + 'tank and plane designs.'));
  }

  loadCountries(ctx).then(({ data }) => { countries = data; return render(); })
    .catch((err) => body.replaceChildren(notice('warn', `Compare unavailable: ${err.message}`)));
  const el = h('section', { class: 'hoi-panel cmp-panel' },
    h('div', { class: 'hoi-head' }, h('span', { class: 'hoi-head-title' }, 'Compare')), body);
  return { el, stop: () => {} };
}

