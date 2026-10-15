// Game summary: IC history of a campaign, like HOI4-IC-Graphs - IC a day on military production, naval production or
// construction per country or summed per faction, daily and cumulative, the number of factories, the IC idle factories
// waste and the IC of equipment lost in combat and to attrition, optionally against a second campaign. The backend
// records every country once per game day while the app runs (ic_history.py).
import { h, notice, viewHeader } from '../lib/dom.js';
import { compact, dayText, hoverSync, lineChart } from '../lib/linechart.js';
import { refreshMs } from '../lib/options.js';
import { numberLocale } from '../lib/options.js';

// categorical slots in fixed order (dark steps of the validated reference palette); a colour follows its series
export const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
export const MAX_SERIES = SERIES_COLORS.length;
// [key, chart title, button]
const IC_METRICS = [['mil', 'Military IC', 'Military'], ['nav', 'Naval IC', 'Naval'], ['civ', 'Civilian IC (construction)', 'Civilian']];
const FACTORY_METRICS = [['fciv', 'Civilian factories', 'Civilian'], ['fmil', 'Military factories', 'Military'],
  ['fdock', 'Dockyards', 'Dockyards'], ['fall', 'All factories', 'All']];
const WASTED_METRICS = [['wmil', 'IC wasted by idle military factories', 'Military'],
  ['wnav', 'IC wasted by idle dockyards', 'Naval'], ['wciv', 'IC wasted by idle civilian factories', 'Civilian'],
  ['wall', 'IC wasted by idle factories', 'All']];
const LOSS_METRICS = [['lcom', 'IC of equipment lost in combat', 'Combat'], ['latt', 'IC of equipment lost to attrition', 'Attrition'],
  ['lall', 'IC of equipment lost', 'All'], ['lenemy', 'IC of enemy equipment destroyed', 'Enemy']];
const METRICS = [...IC_METRICS, ...FACTORY_METRICS, ...WASTED_METRICS, ...LOSS_METRICS];
export const isLossMetric = (m) => LOSS_METRICS.some(([k]) => k === m);
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

/** Running total of IC: each sample's value counts for the days until the next sample (skipped days); unknown
 * days (null) add nothing, and the total is unknown until the first known day. */
export function cumulative(t, values) {
  const out = [];
  let sum = null;
  for (let i = 0; i < values.length; i++) {
    if (values[i] != null) sum = (sum ?? 0) + values[i] * (i === 0 ? 1 : t[i] - t[i - 1]);
    out.push(sum == null ? null : Math.round(sum * 100) / 100);
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

/** "2026-10-15 09:28" of the backend's "2026-10-15 09:28:01" - the real day and time the recording began. */
export function startedText(created) {
  return created ? created.slice(0, 16) : 'unknown';
}

/** "POL · 1936.01.02 → 1936.05.15 (114 days)" - the game dates a campaign covers. */
export function gameLabel(g) {
  return `${g.player ?? '?'} · ${g.first ?? '-'} → ${g.last ?? '-'} (${g.days} ${g.days === 1 ? 'day' : 'days'})`;
}

export default {
  id: 'summary',
  title: 'Game summary',
  short: 'GS',
  async render(root, ctx) {
    const prefs = { metric: 'mil', factions: false, tags: [], colors: {}, groupColors: {}, hiddenGroups: [],
      customColors: { countries: {}, groups: {} }, openGroups: {}, ...loadPrefs() };
    const persist = () => savePrefs({ metric: prefs.metric, factions: prefs.factions, tags: prefs.tags, colors: prefs.colors,
      game: prefs.game, compare: prefs.compare, groupColors: prefs.groupColors, hiddenGroups: prefs.hiddenGroups,
      customColors: prefs.customColors, openGroups: prefs.openGroups });
    const status = h('div', { class: 'gs-rec' });
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
    let running = null;   // the running game: {campaign, player, date, known}
    let main = null;
    let other = null;
    let stopped = false;
    let timer = null;
    let tableOpen = false;
    let groups = { custom: [], assign: {} };   // the user's grouping of the chosen campaign
    let newGroup = '';
    let patch = null;   // combat log for every country: {enabled, state, error} (backend live/code_patch.py)
    let patchBusy = false;
    let campaignOpen = false;   // the campaign list is unfolded
    const closeCampaigns = (e) => {
      if (!campaignOpen || (e.type === 'keydown' ? e.key !== 'Escape' : e.target.closest?.('.gs-camp'))) return;
      campaignOpen = false;
      renderControls();
    };
    document.addEventListener('click', closeCampaigns);
    document.addEventListener('keydown', closeCampaigns);

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

    // A folding group of the picker that stays as the user left it: the list is rebuilt every few seconds. A search
    // opens every group without changing what is remembered.
    function fold(key, byDefault, summary, children) {
      const forced = search.trim() !== '';
      let open = forced || (prefs.openGroups[key] ?? byDefault);
      return h('details', { class: 'gs-group', open: open || null, ontoggle: (e) => {
        if (e.target.open === open) return;   // the toggle event of the element being created
        open = e.target.open;
        if (!forced) { prefs.openGroups[key] = open; persist(); }
      } }, summary, children);
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
      pickerHead.replaceChildren(...[`Groups (${visible.length}/${MAX_SERIES} shown)`,
        changed ? h('button', { class: 'btn btn-small btn-ghost', title: 'Back to the factions of the game',
          onclick: () => saveGroups({ custom: [], assign: {} }) }, 'Reset') : null].filter(Boolean));   // no "null" text
      const searching = search.trim() !== '';
      pickerList.replaceChildren(
        h('div', { class: 'gs-new' }, input, h('button', { class: 'btn btn-small', onclick: add }, 'Add')),
        ...[...members.entries()].map(([g, all]) => [g, all.filter((c) => matches(c, search)), all.length])
          .filter(([g, list]) => !searching || list.length || g.toLowerCase().includes(search.trim().toLowerCase()))
          .map(([g, list, total]) => {
          const shown = visible.includes(g);
          return fold(`g:${g}`, g !== NO_FACTION && total <= 12,
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

    async function requestRecording(body) {
      try {
        const res = await ctx.api.post('/api/summary/recording', body);
        recorder = res.data.recorder;
        running = res.data.running ?? null;
        renderStatus();
      } catch (err) {
        charts.prepend(notice('warn', `Recording not changed: ${err.message}`));
      }
    }

    // What is recorded and why (the game's campaign id, the date, the user's choice), and the user's override:
    // a new campaign file or another recorded campaign from the next game day on.
    // The recording panel: the running game and its campaign id (read live), the recorded campaign it goes to and how
    // that was decided (the id, the date, the user's choice), and the user's override - a new campaign file or another
    // recorded campaign from the next game day on.
    function renderStatus() {
      const byId = (id) => games.find((g) => g.id === id);
      const rec = byId(recorder.recording);
      const known = (running?.known ?? []).map(byId).filter(Boolean);
      const live = running && running.date;
      const on = live && rec && (!running.campaign || running.campaign === recorder.campaign);
      const state = on ? ['gs-rec-on', 'Recording'] : live ? ['gs-rec-wait', 'Waiting for the next game day']
        : ['gs-rec-off', 'Not recording'];
      const target = on ? `${gameLabel(rec)} · started ${startedText(rec.created)}`
        : known.length ? `${gameLabel(known[0])} (continues - recognised by the campaign id)`
          : live ? 'a new campaign (this campaign id was not recorded before)' : '-';
      const pending = recorder.pending === 'new' ? 'a new recording'
        : recorder.pending ? `continuing ${byId(recorder.pending) ? gameLabel(byId(recorder.pending)) : recorder.pending}` : null;
      const others = games.filter((g) => !g.active);
      const cont = (e) => {
        const g = byId(e.target.value);
        e.target.value = '';
        if (g && window.confirm(`Record the running game into ${gameLabel(g)} from the next game day on?\n\n`
          + 'Days of that campaign from that game day on are replaced.')) requestRecording({ action: 'continue', game: g.id });
      };
      const row = (label, ...value) => [h('dt', null, label), h('dd', null, ...value)];
      status.className = `gs-rec ${state[0]}`;
      status.replaceChildren(...[
        h('div', { class: 'gs-rec-head' }, h('span', { class: 'gs-rec-dot' }), h('strong', null, state[1]),
          !live && recorder.error ? h('span', { class: 'muted' }, ` - ${recorder.error}`) : null,
          !live ? h('span', { class: 'muted' }, ' - start or load a game; the recorder reads it once a game day.') : null),
        h('dl', { class: 'gs-rec-grid' },
          ...row('Game running', live ? `${running.player ?? '?'} · ${running.date}` : 'none'),
          ...row('Campaign ID', live && running.campaign ? h('code', { class: 'gs-rec-id' }, running.campaign)
            : live ? 'not readable - the campaign is matched by the date' : '-'),
          ...row('Recorded into', target),
          ...row('Chosen', on && recorder.how ? recorder.how : '-')),
        pending ? h('div', { class: 'gs-pending' }, `Next game day: ${pending}`,
          h('button', { class: 'btn btn-small btn-ghost', onclick: () => requestRecording({ action: 'cancel' }) }, 'Cancel')) : null,
        h('div', { class: 'gs-rec-actions' },
          h('button', { class: 'btn btn-small', title: 'Record the running game as a new campaign from the next game day on',
            onclick: () => requestRecording({ action: 'new' }) }, 'Start new recording'),
          others.length ? h('select', { class: 'gs-rec-continue', title: 'Record the running game into a recorded campaign', onchange: cont },
            h('option', { value: '' }, 'Continue in…'),
            others.map((g) => h('option', { value: g.id }, `${gameLabel(g)} · started ${startedText(g.created)}`))) : null),
      ].filter(Boolean));   // replaceChildren would print a null
    }

    function select(options, value, onChange, empty) {
      const el = h('select', { onchange: (e) => onChange(e.target.value) },
        empty ? h('option', { value: '' }, empty) : null,
        options.map(([v, label]) => h('option', { value: v, selected: v === value || null }, label)));
      return el;
    }

    async function deleteGame(g) {
      if (!window.confirm(`Delete the campaign ${gameLabel(g)}, started ${startedText(g.created)}?\n\n`
        + 'Its recorded days and groups are removed for good.')) return;
      try {
        await ctx.api.post(`${gameUrl(g.id)}/delete`, {});
      } catch (err) {
        charts.prepend(notice('warn', `Campaign not deleted: ${err.message}`));
        return;
      }
      if (prefs.game === g.id) prefs.game = null;
      if (prefs.compare === g.id) prefs.compare = null;
      load();
    }

    // The campaign list: game dates, the real date the recording began, and a delete button (not for the campaign
    // being recorded). A list of its own - a <select> cannot hold buttons.
    function campaignPicker() {
      const cur = games.find((g) => g.id === prefs.game);
      const toggle = () => { campaignOpen = !campaignOpen; renderControls(); };
      return h('div', { class: 'gs-camp' },
        h('button', { class: 'gs-camp-btn', 'aria-haspopup': 'listbox', 'aria-expanded': String(campaignOpen), onclick: toggle },
          cur ? [h('span', null, gameLabel(cur)), h('span', { class: 'gs-camp-started' }, `started ${startedText(cur.created)}`)]
            : h('span', null, games.length ? 'Choose a campaign' : 'No campaign yet'),
          h('span', { class: 'gs-camp-caret' }, '▾')),
        campaignOpen ? h('div', { class: 'gs-camp-list', role: 'listbox' }, games.map((g) =>
          h('div', { class: `gs-camp-row ${g.id === prefs.game ? 'gs-camp-on' : ''}`, role: 'option',
            'aria-selected': String(g.id === prefs.game),
            onclick: () => { campaignOpen = false; prefs.game = g.id; renderControls(); load(); } },
          h('span', { class: 'gs-camp-main' }, gameLabel(g)),
          h('span', { class: 'gs-camp-started' }, `started ${startedText(g.created)}`),
          g.active ? h('span', { class: 'gs-camp-rec', title: 'Being recorded - it can be deleted once another game runs' }, 'recording')
            : h('button', { class: 'btn btn-small btn-ghost gs-camp-del', title: 'Delete this campaign',
              onclick: (e) => { e.stopPropagation(); deleteGame(g); } }, 'Delete')))) : null);
    }

    function renderControls() {
      const opts = games.map((g) => [g.id, `${gameLabel(g)} · started ${startedText(g.created)}`]);
      // a click shows the new choice at once; the data follows from load()
      const pick = (apply) => (v) => { apply(v); renderControls(); load(); };
      const seg = (items, value, onPick) => h('div', { class: 'gs-seg' }, items.map(([v, label]) =>
        h('button', { class: `gs-seg-btn ${v === value ? 'gs-seg-on' : ''}`, 'aria-pressed': String(v === value),
          onclick: () => onPick(v) }, label)));
      controls.replaceChildren(
        h('div', { class: 'gs-row' },
          h('div', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, 'Campaign'), campaignPicker()),
          h('label', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, 'Compare with'),
            select(opts.filter(([v]) => v !== prefs.game), prefs.compare, pick((v) => { prefs.compare = v || null; }), '-'))),
        h('div', { class: 'gs-row' },
          ...[['IC a day', IC_METRICS], ['Factories', FACTORY_METRICS], ['Wasted IC', WASTED_METRICS], ['IC lost', LOSS_METRICS]]
            .map(([label, list]) => h('div', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, label),
              seg(list.map(([k, , b]) => [k, b]), prefs.metric, pick((v) => { prefs.metric = v; })))),
          h('div', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, 'Show'),
            seg([[false, 'Countries'], [true, 'Factions']], prefs.factions, pick((v) => { prefs.factions = v; })))));
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
      pickerHead.replaceChildren(`Countries (${prefs.tags.length}/${MAX_SERIES})`,
        prefs.tags.length ? h('button', { class: 'btn btn-small btn-ghost', onclick: () => { prefs.tags = []; load(); } }, 'Clear') : null);
      const row = (c) => {
        const on = prefs.tags.includes(c.tag);
        return h('label', { class: `gs-country ${on ? 'gs-country-on' : ''}`, title: c.name },
          h('input', { type: 'checkbox', checked: on || null, disabled: (!on && full) || null,
            onchange: () => { prefs.tags = on ? prefs.tags.filter((t) => t !== c.tag) : [...prefs.tags, c.tag]; load(); } }),
          h('span', { class: 'gs-country-tag' }, c.tag, on && prefs.colors[c.tag] != null ? colorInput(c.tag) : null),
          h('span', { class: 'gs-country-value' }, c[prefs.metric] == null ? '-' : compact(c[prefs.metric])));
      };
      // the chosen countries on top, whatever group they are in and however the groups are folded (not while searching)
      const chosen = search.trim() ? [] : prefs.tags.map((t) => main.countries.find((c) => c.tag === t)).filter(Boolean);
      const blocks = [...groups.entries()].sort((a, b) => (a[0] === NO_FACTION) - (b[0] === NO_FACTION))
          .map(([f, all]) => [f, all.filter((c) => matches(c, search))]).filter(([, list]) => list.length).map(([f, list]) =>
          fold(`c:${f}`, f !== NO_FACTION, h('summary', null, `${f} (${list.length})`), list.map(row)));
      pickerList.replaceChildren(
        chosen.length ? h('div', { class: 'gs-chosen' }, h('div', { class: 'gs-chosen-head' }, 'Shown on the chart'), chosen.map(row)) : null,
        ...(blocks.length ? blocks : [h('p', { class: 'muted' }, 'No country matches.')]));
    }

    async function setPatch(on) {
      if (on && !window.confirm('Keep a combat log for every country?\n\nThe debugger changes 5 bytes of the game\'s code '
        + 'in memory (single player only, nothing on disk) so the game logs the losses of all countries, not only yours. '
        + 'It stays until you turn it off or close the game and comes back when the game starts again. '
        + 'Saves and the game\'s memory grow a little with the logs.')) { renderCharts(); return; }
      patchBusy = true;
      renderCharts();
      try {
        patch = (await ctx.api.post('/api/live/combat-log-patch', { enabled: on, confirm_local: on })).data;
      } catch (err) {
        patch = { ...(patch ?? {}), error: err.message };
      }
      patchBusy = false;
      renderCharts();
    }

    function patchBar() {
      const on = !!patch?.enabled;
      const state = patch?.error ? `Not active: ${patch.error}`
        : patch?.state === 'on' ? 'Active in the running game'
          : patch?.state === 'unknown' ? 'The game\'s code is not the expected one - not active'
            : on ? 'Waiting for the game' : 'Off: the game logs only your country';
      return h('div', { class: 'gs-patch' },
        h('label', { class: 'gs-patch-toggle', title: 'LOCAL change of the game in memory, single player only' },
          h('input', { type: 'checkbox', checked: on || null, disabled: patchBusy || null, onchange: (e) => setPatch(e.target.checked) }),
          'Combat log for every country'),
        h('span', { class: `gs-patch-state ${patch?.state === 'on' && !patch?.error ? 'gs-patch-on' : 'muted'}` }, patchBusy ? '…' : state));
    }

    /** Which chosen series have no combat log - the game keeps one for the player and only some countries at war with
     * it (POL 1936 at war with SOV: SOV's log stays empty). */
    function lossNotice(keys) {
      const empty = main.series.filter((s) => keys.includes(s.key) && !s.values.some((v) => v != null)).map((s) => s.key);
      const logged = main.countries.filter((c) => c[prefs.metric] != null).map((c) => c.tag);
      const text = (patch?.state === 'on' ? 'Every country keeps a combat log from the day it was turned on. '
        : 'The game keeps a combat log only for the player\'s country. ')
        + `With a log now: ${logged.length ? logged.join(', ') : 'none'}. A country without one shows as combat losses only `
        + 'its equipment destroyed by the countries with a log (no attrition). The first day after the app starts or a save '
        + 'is loaded is not known.';
      return notice(empty.length ? 'warn' : 'info', empty.length
        ? [h('strong', null, `No losses known for ${empty.join(', ')}. `), text] : text);
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
            h('td', { class: 'num' }, s.values[last] == null ? '—' : s.values[last].toLocaleString(numberLocale(), { maximumFractionDigits: 1 })),
            isFactoryMetric(prefs.metric) ? null
              : h('td', { class: 'num' }, cumulative(main.t, s.values)[last]?.toLocaleString(numberLocale(), { maximumFractionDigits: 0 }) ?? '—'))))));
      const factories = isFactoryMetric(prefs.metric);
      const sync = hoverSync();   // the hovered day shows in both charts
      charts.replaceChildren(...[   // replaceChildren would print a null
        isLossMetric(prefs.metric) ? patchBar() : null,
        isLossMetric(prefs.metric) ? lossNotice(keys) : null,
        prefs.metric.startsWith('w') ? notice('info', 'Factories without a production or construction line, at the '
          + 'country\'s own IC per assigned factory that day (a construction line takes at most 15 factories).') : null,
        lineChart({ title: factories ? metric : `Daily ${metric}`, series: sets(false), sync,
          format: factories ? (v) => String(Math.round(v)) : compact }),
        factories ? null : lineChart({ title: `Cumulative ${metric}`, series: sets(true), sync }),
        table].filter(Boolean));
    }

    async function load() {
      persist();
      try {
        const res = await ctx.api.get('/api/summary/games');
        if (stopped) return;
        games = res.data.games;
        recorder = res.data.recorder;
        running = res.data.running ?? null;
        if (!games.some((g) => g.id === prefs.game)) prefs.game = (games.find((g) => g.active) ?? games[0])?.id;
        if (prefs.compare && (!games.some((g) => g.id === prefs.compare) || prefs.compare === prefs.game)) prefs.compare = null;
        if (!status.contains(document.activeElement)) renderStatus();   // do not close the open campaign list
        const focused = document.activeElement;   // do not close an open <select> (a focused button is fine)
        if (!(controls.contains(focused) && focused.tagName === 'SELECT')) renderControls();
        main = prefs.game ? await fetchGame(prefs.game) : null;
        if (main && !prefs.factions && !prefs.tags.length) {   // first visit: the player and the biggest producers
          prefs.tags = [...new Set([main.player, ...main.countries.map((c) => c.tag)].filter((t) => main.countries.some((c) => c.tag === t)))].slice(0, 5);
          main = await fetchGame(prefs.game);
        }
        other = prefs.compare ? await fetchGame(prefs.compare, prefs.game) : null;
        groups = main ? (await ctx.api.get(`${gameUrl(prefs.game)}/groups`)).data : { custom: [], assign: {} };
        if (isLossMetric(prefs.metric) && !patchBusy) {
          patch = await ctx.api.get('/api/live/combat-log-patch').then((r) => r.data, (err) => ({ ...(patch ?? {}), error: err.message }));
        }
        if (stopped) return;
        const a = document.activeElement;   // do not reset a list being picked or a group name being typed
        if (!(pickerList.contains(a) && (a.tagName === 'SELECT' || a.type === 'text'))) renderPicker();
        renderCharts();
      } catch (err) {
        if (!stopped) charts.replaceChildren(notice('warn', `Game summary unavailable: ${err.message}`));
      }
      clearTimeout(timer);
      if (!stopped && games.find((g) => g.id === prefs.game)?.active) timer = setTimeout(load, refreshMs(REFRESH_MS));
    }

    await load();
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener('click', closeCampaigns);
      document.removeEventListener('keydown', closeCampaigns);
    };
  },
};
