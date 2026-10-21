// Game summary - equipment (2026-10-20, user's request): a separate chart at the bottom of the tab for one country and
// one kind of equipment over the campaign: needed by its divisions, in its divisions, in its stockpile (one chart) and
// produced a day (a second chart, its own scale). Recorded once a game day from game memory (live/service._equipment_day).
import { h, notice } from '../lib/dom.js';
import { compact, dayText, hoverSync, lineChart } from '../lib/linechart.js';
import { numberLocale } from '../lib/options.js';

const PREFS_KEY = 'hoi4dbg.summaryEquipment';
// colours of the palette the summary charts use (validated for the dark background)
export const EQUIPMENT_LINES = [['needed', 'Needed', '#d95926'], ['held', 'In divisions', '#3987e5'], ['stockpile', 'Stockpile', '#199e70']];
const PRODUCED_COLOR = '#c98500';

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {}; } catch { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* preference only */ }
}

/** Chart series of the response: [{label, color, points: [[t, v]]}] for the needed / held / stockpile chart. */
export function equipmentSets(data) {
  return EQUIPMENT_LINES.map(([key, label, color]) => ({ label, color,
    points: (data.series?.[key] ?? []).map((v, i) => [data.t[i], v]) }));
}

/** Production forecast (2026-10-21, user's request) of every kind of equipment on the last recorded day: missing =
 * needed - in divisions - stockpile, days = missing / produced a day (null: nothing produced), the game day it is
 * filled. Missing ones first, the longest wait on top. */
export function forecast(last, archetypes, t) {
  const info = new Map((archetypes ?? []).map((a) => [a.key, a]));
  return Object.entries(last ?? {}).map(([key, [needed, held, stockpile, produced]]) => {
    const missing = Math.max(0, needed - held - stockpile);
    const days = missing <= 0 ? 0 : produced > 0 ? Math.ceil(missing / produced) : null;
    return { key, name: info.get(key)?.name ?? key, icon: info.get(key)?.icon ?? null, needed, held, stockpile, produced,
      missing, days, ready: days == null || t == null ? null : dayText(t + days) };
  }).filter((r) => r.needed > 0 || r.produced > 0)
    .sort((a, b) => (b.missing > 0) - (a.missing > 0) || (b.days ?? Infinity) - (a.days ?? Infinity) || b.missing - a.missing);
}

/** The section: el, update(gameId, countries, player) - call it whenever the summary has read its campaign again. */
export function equipmentSection(ctx) {
  const prefs = { tag: null, archetype: null, ...loadPrefs() };
  const tagSelect = h('select', { class: 'input', 'aria-label': 'Country' });
  const kinds = h('div', { class: 'gs-eq-kinds' });
  const body = h('div', { class: 'gs-eq-body' }, h('p', { class: 'muted' }, 'Choose a campaign above.'));
  let gid = null;
  let countries = [];
  let busy = false;
  tagSelect.addEventListener('change', () => { prefs.tag = tagSelect.value; prefs.archetype = null; savePrefs(prefs); refresh(); });

  function fillCountries(player) {
    if (document.activeElement === tagSelect) return;   // do not close an open list
    if (!prefs.tag || !countries.some((c) => c.tag === prefs.tag)) prefs.tag = player && countries.some((c) => c.tag === player) ? player : countries[0]?.tag ?? null;
    tagSelect.replaceChildren(...countries.map((c) => h('option', { value: c.tag, selected: c.tag === prefs.tag }, `${c.tag} - ${c.name ?? c.tag}`)));
  }

  function render(data) {
    kinds.replaceChildren(...data.archetypes.map((a) => h('button', { type: 'button',
      class: `gs-eq-kind${a.key === data.archetype ? ' gs-eq-kind-on' : ''}`, title: a.key,
      onClick: () => { prefs.archetype = a.key; savePrefs(prefs); refresh(); } },
    a.icon ? h('img', { src: a.icon, alt: '', draggable: 'false' }) : null, h('span', null, a.name))));
    if (!data.t.length || !data.archetype) {
      body.replaceChildren(notice('info', 'No equipment recorded for this country yet - it is recorded once a game day from game memory '
        + '(campaigns recorded before 2026-10-20 have none).'));
      return;
    }
    const sync = hoverSync();
    const name = data.archetypes.find((a) => a.key === data.archetype)?.name ?? data.archetype;
    const last = data.t.length - 1;
    const fmt = (v, d = 0) => (v == null ? '—' : v.toLocaleString(numberLocale(), { maximumFractionDigits: d }));
    body.replaceChildren(
      lineChart({ title: `${name} - needed, in divisions, stockpile`, series: equipmentSets(data), sync, format: compact }),
      lineChart({ title: `${name} produced a day`, series: [{ label: 'Produced a day', color: PRODUCED_COLOR,
        points: data.series.produced.map((v, i) => [data.t[i], v]) }], sync, format: (v) => fmt(v, 1) }),
      h('table', { class: 'table gs-eq-table' },
        h('thead', null, h('tr', null, h('th', null, data.dates[last]), ...EQUIPMENT_LINES.map(([, label]) => h('th', { class: 'num' }, label)),
          h('th', { class: 'num' }, 'Produced a day'), h('th', { class: 'num' }, 'Missing'))),
        h('tbody', null, h('tr', null, h('td', null, name),
          ...EQUIPMENT_LINES.map(([key]) => h('td', { class: 'num' }, fmt(data.series[key][last]))),
          h('td', { class: 'num' }, fmt(data.series.produced[last], 1)),
          h('td', { class: 'num bad-text' }, fmt(Math.max(0, data.series.needed[last] - data.series.held[last] - data.series.stockpile[last])))))),
      forecastTable(data),
      h('p', { class: 'hint' }, 'Needed = divisions of each template x the equipment of its battalions and companies; in divisions and '
        + 'stockpile as the game holds them; produced = the production lines\' output of the day divided by the cost of one unit. '
        + 'All variants of a kind summed (designs, older models).'));
  }

  function forecastTable(data) {
    const rows = forecast(data.last, data.archetypes, data.t[data.t.length - 1]);
    if (!rows.length) return null;
    const fmt = (v, d = 0) => (v == null ? '—' : v.toLocaleString(numberLocale(), { maximumFractionDigits: d }));
    return h('div', { class: 'gs-forecast' },
      h('div', { class: 'lc-title' }, 'Production forecast - every kind of equipment at today\'s production'),
      h('table', { class: 'table gs-eq-table' },
        h('thead', null, h('tr', null, h('th', null, 'Equipment'), h('th', { class: 'num' }, 'Missing'),
          h('th', { class: 'num' }, 'Produced a day'), h('th', { class: 'num' }, 'Days to fill'), h('th', null, 'Filled on'))),
        h('tbody', null, rows.map((r) => h('tr', { class: r.key === data.archetype ? 'gs-forecast-on' : null },
          h('td', null, r.icon ? h('img', { src: r.icon, alt: '', class: 'gs-forecast-icon', draggable: 'false' }) : null, r.name),
          h('td', { class: `num ${r.missing > 0 ? 'bad-text' : ''}` }, fmt(r.missing)),
          h('td', { class: 'num' }, fmt(r.produced, 1)),
          h('td', { class: 'num' }, r.missing <= 0 ? 'enough' : r.days == null ? 'never (not produced)' : fmt(r.days)),
          h('td', null, r.missing <= 0 ? '—' : r.ready ?? '—'))))));
  }

  async function refresh() {
    if (!gid || !prefs.tag || busy) return;
    busy = true;
    try {
      const q = new URLSearchParams({ tag: prefs.tag });
      if (prefs.archetype) q.set('archetype', prefs.archetype);
      render((await ctx.api.get(`/api/summary/games/${encodeURIComponent(gid)}/equipment?${q}`)).data);
    } catch (err) {
      body.replaceChildren(notice('warn', `Equipment unavailable: ${err.message}`));
    } finally {
      busy = false;
    }
  }

  const el = h('section', { class: 'card gs-eq' },
    h('div', { class: 'card-head' }, h('h2', null, 'Equipment'), h('span', { class: 'gs-eq-pick' }, tagSelect)),
    h('div', { class: 'card-body' }, kinds, body));
  return {
    el,
    update(gameId, list, player) {
      gid = gameId;
      countries = [...(list ?? [])].sort((a, b) => a.tag.localeCompare(b.tag));
      fillCountries(player);
      refresh();
    },
  };
}
