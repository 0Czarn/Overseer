// Game summary: IC history of a campaign, like HOI4-IC-Graphs - IC a day on military production, naval production or
// construction per country or summed per faction, daily and cumulative, and the number of factories, optionally against
// a second campaign. The backend records every country once per game day while the app runs (ic_history.py).
import { h, notice, viewHeader } from '../lib/dom.js';
import { compact, dayText, hoverSync, lineChart } from '../lib/linechart.js';

// categorical slots in fixed order (dark steps of the validated reference palette); a colour follows its series
export const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
export const MAX_SERIES = SERIES_COLORS.length;
const IC_METRICS = [['mil', 'Military IC'], ['nav', 'Naval IC'], ['civ', 'Civilian IC (construction)']];
const FACTORY_METRICS = [['fciv', 'Civilian factories'], ['fmil', 'Military factories'], ['fdock', 'Dockyards'], ['fall', 'All factories']];
const METRICS = [...IC_METRICS, ...FACTORY_METRICS];
/** Factory counts are a level, not a flow: no cumulative chart, whole numbers. */
export const isFactoryMetric = (m) => FACTORY_METRICS.some(([k]) => k === m);
const PREFS_KEY = 'hoi4dbg.summary';
const REFRESH_MS = 5000;

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {}; } catch { return {}; }
}

function savePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* preference only */ }
}

/** Running total of IC: each sample's value counts for the days until the next sample (skipped days). */
export function cumulative(t, values) {
  const out = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i] * (i === 0 ? 1 : t[i] - t[i - 1]);
    out.push(Math.round(sum * 100) / 100);
  }
  return out;
}

/** Keeps each chosen key on its colour slot; new keys take the first free slot. */
export function assignColors(keys, previous = {}) {
  const out = {};
  const used = new Set();
  for (const k of keys) {
    if (previous[k] != null && !used.has(previous[k])) { out[k] = previous[k]; used.add(previous[k]); }
  }
  for (const k of keys) {
    if (out[k] != null) continue;
    const free = SERIES_COLORS.findIndex((_, i) => !used.has(i));
    out[k] = free; used.add(free);
  }
  return out;
}

export const NO_FACTION = 'Non-aligned';

/** Grouping after moving `country` ({tag, game_faction}) to `target` (a group name or NO_FACTION): only changes against
 * the game's faction are kept. */
export function moveCountry(groups, country, target) {
  const assign = { ...groups.assign };
  const home = country.game_faction || NO_FACTION;
  if (target === home) delete assign[country.tag];
  else assign[country.tag] = target === NO_FACTION ? '' : target;
  return { ...groups, assign };
}

/** Grouping without the user's group `name`: its countries go back to their game factions. */
export function deleteGroup(groups, name) {
  return { custom: groups.custom.filter((g) => g !== name),
    assign: Object.fromEntries(Object.entries(groups.assign).filter(([, g]) => g !== name)) };
}

export function addGroup(groups, name) {
  const n = name.trim();
  if (!n || n.length > 40 || n === NO_FACTION || groups.custom.includes(n)) return groups;
  return { ...groups, custom: [...groups.custom, n] };
}

/** Countries matching a search by tag or name (case-insensitive); all when the search is empty. */
export function matches(country, search) {
  const q = search.trim().toLowerCase();
  return !q || country.tag.toLowerCase().includes(q) || (country.name ?? '').toLowerCase().includes(q);
}

export default {
  id: 'summary',
  title: 'Game summary',
  short: 'GS',
  async render(root, ctx) {
    const prefs = { metric: 'mil', factions: false, tags: [], colors: {}, groupColors: {}, hiddenGroups: [],
      customColors: { countries: {}, groups: {} }, ...loadPrefs() };
    const status = h('div', { class: 'gs-status muted' });
    const controls = h('div', { class: 'gs-controls' });
    let search = '';
    const searchInput = h('input', { type: 'search', class: 'gs-search', placeholder: 'Search tag or name',
      oninput: (e) => { search = e.target.value; renderPicker(); } });
    const pickerHead = h('div', { class: 'gs-picker-head' });
    const pickerList = h('div', { class: 'gs-picker-list' });
    const picker = h('div', { class: 'gs-picker' }, pickerHead, searchInput, pickerList);
    const charts = h('div', { class: 'gs-charts' });
    root.append(viewHeader('Game summary', 'IC a day per country over the campaign, recorded from game memory while the app runs.'),
      status, controls, h('div', { class: 'gs-body' }, picker, charts));

    let games = [];
    let recorder = {};
    let main = null;
    let other = null;
    let stopped = false;
    let timer = null;
    let tableOpen = false;
    let groups = { custom: [], assign: {} };   // the user's grouping of the chosen campaign
    let newGroup = '';

    const query = (groupsFrom) => {
      const p = new URLSearchParams({ metric: prefs.metric });
      if (prefs.factions) p.set('factions', '1'); else p.set('tags', prefs.tags.join(','));
      if (groupsFrom) p.set('groups_from', groupsFrom);   // a compared campaign uses the grouping of the first one
      return p.toString();
    };
    const gameUrl = (id) => `/api/summary/games/${encodeURIComponent(id)}`;
    const fetchGame = (id, groupsFrom) => ctx.api.get(`${gameUrl(id)}?${query(groupsFrom)}`).then((r) => r.data);

    async function saveGroups(next) {
      try {
        groups = (await ctx.api.post(`${gameUrl(prefs.game)}/groups`, next)).data;
      } catch (err) {
        charts.prepend(notice('warn', `Groups not saved: ${err.message}`));
        return;
      }
      load();
    }

    // colour of a series: the user's own, else its slot of the validated palette
    const colorMap = () => (prefs.factions ? prefs.customColors.groups : prefs.customColors.countries);
    const seriesColor = (k) => colorMap()[k] ?? SERIES_COLORS[(prefs.factions ? prefs.groupColors : prefs.colors)[k]];
    function colorInput(key) {
      return h('input', { type: 'color', class: 'gs-color', value: seriesColor(key), title: 'Change the colour (right-click: default)',
        onclick: (e) => e.stopPropagation(),
        onchange: (e) => { colorMap()[key] = e.target.value; load(); },
        oncontextmenu: (e) => { e.preventDefault(); delete colorMap()[key]; load(); } });
    }

    function visibleGroups() {
      return main.series.map((s) => s.key).filter((k) => !prefs.hiddenGroups.includes(k)).slice(0, MAX_SERIES);
    }

    function renderGroupEditor() {
      const visible = visibleGroups();
      const names = [...main.factions, NO_FACTION];
      const members = new Map(main.series.map((s) => [s.key, []]));
      for (const c of main.countries) {
        const g = c.faction || NO_FACTION;
        if (!members.has(g)) members.set(g, []);
        members.get(g).push(c);
      }
      const changed = groups.custom.length || Object.keys(groups.assign).length;
      const add = () => {
        const next = addGroup(groups, newGroup);
        if (next !== groups) { newGroup = ''; saveGroups(next); }
      };
      const input = h('input', { type: 'text', class: 'gs-new-group', placeholder: 'New group name', maxlength: 40, value: newGroup,
        oninput: (e) => { newGroup = e.target.value; },
        onkeydown: (e) => { if (e.key === 'Enter') add(); } });
      const toggle = (g, shown) => {
        prefs.hiddenGroups = shown ? [...prefs.hiddenGroups, g] : prefs.hiddenGroups.filter((x) => x !== g);
        load();
      };
      pickerHead.replaceChildren(`Groups (${visible.length}/${MAX_SERIES} shown)`,
        changed ? h('button', { class: 'btn btn-small btn-ghost', title: 'Back to the factions of the game',
          onclick: () => saveGroups({ custom: [], assign: {} }) }, 'Reset') : null);
      const searching = search.trim() !== '';
      pickerList.replaceChildren(
        h('div', { class: 'gs-new' }, input, h('button', { class: 'btn btn-small', onclick: add }, 'Add')),
        ...[...members.entries()].map(([g, all]) => [g, all.filter((c) => matches(c, search)), all.length])
          .filter(([g, list]) => !searching || list.length || g.toLowerCase().includes(search.trim().toLowerCase()))
          .map(([g, list, total]) => {
          const shown = visible.includes(g);
          return h('details', { class: 'gs-group', open: (searching || (g !== NO_FACTION && total <= 12)) || null },
            h('summary', null,
              h('input', { type: 'checkbox', checked: shown || null, title: 'Show on the chart',
                disabled: (!shown && visible.length >= MAX_SERIES) || null, onclick: (e) => e.stopPropagation(),
                onchange: () => toggle(g, shown) }),
              shown ? colorInput(g) : null,
              h('span', { class: 'gs-group-name' }, `${g} (${total})`),
              groups.custom.includes(g) ? h('button', { class: 'btn btn-small btn-ghost gs-del',
                title: 'Delete this group - its countries go back to their factions',
                onclick: (e) => { e.preventDefault(); saveGroups(deleteGroup(groups, g)); } }, 'x') : null),
            list.map((c) => h('div', { class: 'gs-member',
              title: c.game_faction && c.game_faction !== g ? `${c.name} - in the game: ${c.game_faction}` : c.name },
              h('span', { class: 'gs-country-tag' }, c.tag, (c.game_faction || null) !== (c.faction || null) ? ' *' : ''),
              h('span', { class: 'gs-country-value' }, c[prefs.metric] == null ? '-' : compact(c[prefs.metric])),
              h('select', { class: 'gs-move', title: 'Move to group', onchange: (e) => saveGroups(moveCountry(groups, c, e.target.value)) },
                names.map((n) => h('option', { value: n, selected: n === g || null }, n))))));
        }));
    }

    function renderStatus() {
      const rec = games.find((g) => g.active);
      status.textContent = recorder.recording
        ? `Recording ${rec?.player ?? ''} campaign - last day ${recorder.last ?? '…'}`
        : `Not recording${recorder.error ? `: ${recorder.error}` : ''} - start or load a game (the recorder reads it once a day).`;
    }

    function select(options, value, onChange, empty) {
      const el = h('select', { onchange: (e) => onChange(e.target.value) },
        empty ? h('option', { value: '' }, empty) : null,
        options.map(([v, label]) => h('option', { value: v, selected: v === value || null }, label)));
      return el;
    }

    function gameLabel(g) {
      return `${g.player ?? '?'} · ${g.first ?? '-'} → ${g.last ?? '-'} (${g.days} days)${g.active ? ' · recording' : ''}`;
    }

    function renderControls() {
      const opts = games.map((g) => [g.id, gameLabel(g)]);
      const seg = (items, value, onPick) => h('div', { class: 'gs-seg' }, items.map(([v, label]) =>
        h('button', { class: `gs-seg-btn ${v === value ? 'gs-seg-on' : ''}`, onclick: () => onPick(v) }, label)));
      controls.replaceChildren(
        h('label', null, 'Campaign ', select(opts, prefs.game, (v) => { prefs.game = v; load(); })),
        h('label', null, 'Compare with ', select(opts.filter(([v]) => v !== prefs.game), prefs.compare,
          (v) => { prefs.compare = v || null; load(); }, '-')),
        h('span', { class: 'gs-seg-label' }, 'IC a day'),
        seg(IC_METRICS.map(([k, l]) => [k, l.split(' ')[0]]), prefs.metric, (v) => { prefs.metric = v; load(); }),
        h('span', { class: 'gs-seg-label' }, 'Factories'),
        seg(FACTORY_METRICS.map(([k, l]) => [k, l.split(' ')[0]]), prefs.metric, (v) => { prefs.metric = v; load(); }),
        seg([[false, 'Countries'], [true, 'Factions']], prefs.factions, (v) => { prefs.factions = v; load(); }));
    }

    function renderPicker() {
      if (!main) { picker.hidden = true; return; }
      picker.hidden = false;
      if (prefs.factions) { renderGroupEditor(); return; }
      const groups = new Map();
      for (const c of main.countries) {
        const f = c.faction || 'Non-aligned';
        if (!groups.has(f)) groups.set(f, []);
        groups.get(f).push(c);
      }
      const full = prefs.tags.length >= MAX_SERIES;
      const searching = search.trim() !== '';
      pickerHead.replaceChildren(`Countries (${prefs.tags.length}/${MAX_SERIES})`,
        prefs.tags.length ? h('button', { class: 'btn btn-small btn-ghost', onclick: () => { prefs.tags = []; load(); } }, 'Clear') : null);
      const blocks = [...groups.entries()].sort((a, b) => (a[0] === 'Non-aligned') - (b[0] === 'Non-aligned'))
          .map(([f, all]) => [f, all.filter((c) => matches(c, search))]).filter(([, list]) => list.length).map(([f, list]) =>
          h('details', { class: 'gs-group', open: (searching || f !== 'Non-aligned') || null },
            h('summary', null, `${f} (${list.length})`),
            list.map((c) => {
              const on = prefs.tags.includes(c.tag);
              return h('label', { class: 'gs-country', title: c.name },
                h('input', { type: 'checkbox', checked: on || null, disabled: (!on && full) || null,
                  onchange: () => { prefs.tags = on ? prefs.tags.filter((t) => t !== c.tag) : [...prefs.tags, c.tag]; load(); } }),
                h('span', { class: 'gs-country-tag' }, c.tag, on && prefs.colors[c.tag] != null ? colorInput(c.tag) : null),
                h('span', { class: 'gs-country-value' }, c[prefs.metric] == null ? '-' : compact(c[prefs.metric])));
            })));
      pickerList.replaceChildren(...(blocks.length ? blocks : [h('p', { class: 'muted' }, 'No country matches.')]));
    }

    function renderCharts() {
      if (!main) {
        charts.replaceChildren(notice('info', games.length ? 'Choose a campaign.' : 'No campaign recorded yet - keep the app open while you play; one point is recorded per game day.'));
        return;
      }
      const keys = prefs.factions ? visibleGroups() : main.series.map((s) => s.key).slice(0, MAX_SERIES);
      if (prefs.factions) prefs.groupColors = assignColors(keys, prefs.groupColors);
      else prefs.colors = assignColors(keys, prefs.colors);
      const slots = prefs.factions ? prefs.groupColors : prefs.colors;
      const colorOf = (k) => (keys.includes(k) ? (colorMap()[k] ?? SERIES_COLORS[slots[k]]) : null);
      const build = (game, cum, dash, suffix) => game.series
        .filter((s) => colorOf(s.key))
        .map((s) => ({ label: `${s.key}${suffix}`, color: colorOf(s.key), dash,
          points: (cum ? cumulative(game.t, s.values) : s.values).map((v, j) => [game.t[j], v]).filter((p) => p[1] != null) }));
      const metric = METRICS.find(([k]) => k === prefs.metric)[1];
      const sets = (cum) => [...build(main, cum, false, other ? ' (1)' : ''), ...(other ? build(other, cum, true, ' (2)') : [])];
      if (!keys.length) {
        charts.replaceChildren(notice('info', prefs.factions ? 'Tick the groups to show on the left.' : 'Pick up to 8 countries on the left.'));
        return;
      }
      const last = main.t.length - 1;
      const table = h('details', { class: 'gs-table', open: tableOpen || null, ontoggle: (e) => { tableOpen = e.target.open; } },
        h('summary', null, 'Table'),
        h('table', { class: 'table' },
          h('thead', null, h('tr', null, h('th', null, prefs.factions ? 'Faction' : 'Country'),
            h('th', null, `${isFactoryMetric(prefs.metric) ? metric : 'IC a day'} (${dayText(main.t[last])})`),
            isFactoryMetric(prefs.metric) ? null : h('th', null, 'Cumulative IC'))),
          h('tbody', null, main.series.filter((s) => keys.includes(s.key)).map((s) => h('tr', null, h('td', null, s.key),
            h('td', { class: 'num' }, s.values[last] == null ? '—' : s.values[last].toLocaleString(undefined, { maximumFractionDigits: 1 })),
            isFactoryMetric(prefs.metric) ? null
              : h('td', { class: 'num' }, cumulative(main.t, s.values)[last].toLocaleString(undefined, { maximumFractionDigits: 0 })))))));
      const factories = isFactoryMetric(prefs.metric);
      const sync = hoverSync();   // the hovered day shows in both charts
      charts.replaceChildren(...[   // replaceChildren would print a null
        lineChart({ title: factories ? metric : `Daily ${metric}`, series: sets(false), sync,
          format: factories ? (v) => String(Math.round(v)) : compact }),
        factories ? null : lineChart({ title: `Cumulative ${metric}`, series: sets(true), sync }),
        table].filter(Boolean));
    }

    async function load() {
      savePrefs({ metric: prefs.metric, factions: prefs.factions, tags: prefs.tags, colors: prefs.colors, game: prefs.game,
        compare: prefs.compare, groupColors: prefs.groupColors, hiddenGroups: prefs.hiddenGroups, customColors: prefs.customColors });
      try {
        const res = await ctx.api.get('/api/summary/games');
        if (stopped) return;
        games = res.data.games;
        recorder = res.data.recorder;
        if (!games.some((g) => g.id === prefs.game)) prefs.game = (games.find((g) => g.active) ?? games[0])?.id;
        if (prefs.compare && (!games.some((g) => g.id === prefs.compare) || prefs.compare === prefs.game)) prefs.compare = null;
        renderStatus();
        if (!controls.contains(document.activeElement)) renderControls();   // do not close an open list
        main = prefs.game ? await fetchGame(prefs.game) : null;
        if (main && !prefs.factions && !prefs.tags.length) {   // first visit: the player and the biggest producers
          prefs.tags = [...new Set([main.player, ...main.countries.map((c) => c.tag)].filter((t) => main.countries.some((c) => c.tag === t)))].slice(0, 5);
          main = await fetchGame(prefs.game);
        }
        other = prefs.compare ? await fetchGame(prefs.compare, prefs.game) : null;
        groups = main ? (await ctx.api.get(`${gameUrl(prefs.game)}/groups`)).data : { custom: [], assign: {} };
        if (stopped) return;
        const a = document.activeElement;   // do not reset a list being picked or a group name being typed
        if (!(pickerList.contains(a) && (a.tagName === 'SELECT' || a.type === 'text'))) renderPicker();
        renderCharts();
      } catch (err) {
        if (!stopped) charts.replaceChildren(notice('warn', `Game summary unavailable: ${err.message}`));
      }
      clearTimeout(timer);
      if (!stopped && games.find((g) => g.id === prefs.game)?.active) timer = setTimeout(load, REFRESH_MS);
    }

    await load();
    return () => { stopped = true; clearTimeout(timer); };
  },
};
