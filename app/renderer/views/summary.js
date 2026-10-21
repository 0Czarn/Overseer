// Game summary: IC history of a campaign, like HOI4-IC-Graphs - IC a day on military production, naval production or
// construction per country, summed per faction or per player (with or without the player's subjects), daily and cumulative, the number of factories, the IC idle factories
// waste and the IC of equipment lost in combat and to attrition, optionally against a second campaign. The backend
// records every country once per game day while the app runs (ic_history.py).
import { card, h, notice, viewHeader } from '../lib/dom.js';
import { compact, dayText, hoverSync, lineChart } from '../lib/linechart.js';
import { refreshMs } from '../lib/options.js';
import { equipmentSection } from './summary-equipment.js';
import { notesSection, rankingSection, sessionsSection } from './summary-extra.js';
import { mapSection } from './summary-map.js';
import { REPORT_METRICS, download, reportHtml, reportName } from './summary-report.js';
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
// recorded from 2026-10-21 (user's request) - states of a day, not flows
const KD_METRICS = [['kd', 'Enemy equipment destroyed per equipment lost (IC, running sums)', 'Destroyed / lost']];
const POLITICS_METRICS = [['pp', 'Political power', 'PP'], ['stab', 'Stability', 'Stability'], ['ws', 'War support', 'War support'],
  ['cp', 'Command power', 'CP'], ['fuel', 'Fuel', 'Fuel']];
const ARMY_METRICS = [['divs', 'Divisions', 'Divisions'], ['bat', 'Battalions in divisions', 'Battalions'],
  ['cover', 'Equipment of the divisions (% of what the templates need)', 'Equipped %']];
const TERRITORY_METRICS = [['sown', 'States owned', 'Owned'], ['sctl', 'States controlled', 'Controlled'],
  ['vp', 'Victory points controlled', 'Victory points']];
const RESEARCH_METRICS = [['tech', 'Technologies researched', 'Technologies']];
const MANPOWER_METRICS = [['mpf', 'Free manpower', 'Free'], ['mpa', 'Manpower in the field', 'In the field'],
  ['mpt', 'Manpower in training', 'Training'], ['mpall', 'All manpower (free + field + training)', 'All']];
const EXTRA_METRICS = [...KD_METRICS, ...POLITICS_METRICS, ...ARMY_METRICS, ...TERRITORY_METRICS, ...RESEARCH_METRICS, ...MANPOWER_METRICS];
export const PERCENT_METRICS = ['stab', 'ws', 'cover'];
// groups of buttons: [label, metrics]
export const METRIC_GROUPS = [['IC a day', null], ['Factories', null], ['IC per factory', null], ['Wasted IC', null],
  ['IC lost', null], ['Politics', POLITICS_METRICS], ['Army', ARMY_METRICS], ['Territory', TERRITORY_METRICS],
  ['Research', RESEARCH_METRICS], ['Manpower', MANPOWER_METRICS]];
// IC a day per factory working on a line (efficiency, output and construction bonuses); groups: their IC / their factories
const PER_FACTORY_METRICS = [['pmil', 'Military IC per military factory', 'Military'],
  ['pnav', 'Naval IC per dockyard', 'Naval'], ['pciv', 'Construction IC per civilian factory', 'Civilian']];
const METRICS = [...IC_METRICS, ...FACTORY_METRICS, ...PER_FACTORY_METRICS, ...WASTED_METRICS, ...LOSS_METRICS, ...EXTRA_METRICS];
export const isExtraMetric = (m) => EXTRA_METRICS.some(([k]) => k === m);
export const isLossMetric = (m) => LOSS_METRICS.some(([k]) => k === m);
/** Factory counts are a level, not a flow: no cumulative chart, whole numbers. */
export const isFactoryMetric = (m) => FACTORY_METRICS.some(([k]) => k === m);
export const isPerFactoryMetric = (m) => PER_FACTORY_METRICS.some(([k]) => k === m);
/** A state of the day (factories, IC per factory), not a flow: no cumulative chart. */
export const isLevelMetric = (m) => isFactoryMetric(m) || isPerFactoryMetric(m) || isExtraMetric(m);

/** How a value of `metric` is written: whole numbers for counts, % for stability / war support / coverage. */
export function metricFormat(m) {
  if (PERCENT_METRICS.includes(m)) return (v) => `${v.toFixed(1)}%`;
  if (m === 'kd') return (v) => v.toFixed(2);
  if (isPerFactoryMetric(m)) return (v) => v.toFixed(2);
  if (isFactoryMetric(m) || ['divs', 'bat', 'sown', 'sctl', 'tech'].includes(m)) return (v) => String(Math.round(v));
  return compact;
}
/** What a value recorded from 2026-10-21 is, shown above its chart. */
export function extraNote(m) {
  const what = {
    kd: 'IC of enemy equipment destroyed divided by the IC of equipment lost, both summed from the first known day - above 1: '
      + 'the enemy loses more. Only countries with a combat log (see IC lost).',
    cover: 'Equipment in the divisions of what their templates need, each kind up to its need (pieces), summed over all kinds.',
    vp: 'Victory points of the states the country controls (state history files of the game and the mods); a state counts '
      + 'whole for its controller.',
    mpf: 'Free manpower: the available manpower of the states the country controls, as the game counts it.',
    stab: 'A group shows the mean of its countries.', ws: 'A group shows the mean of its countries.',
    bat: 'Battalions of all divisions (templates x divisions), without support companies.',
  }[m];
  return `${what ? `${what} ` : ''}Recorded once a game day from 2026-10-21 - older days have no value.`;
}

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
    const prefs = { metric: 'mil', factions: false, players: false, subjects: true, tags: [], colors: {}, groupColors: {},
      playerColors: {}, hiddenGroups: [], hiddenPlayers: [], openGroups: {}, ...loadPrefs() };
    prefs.customColors = { countries: {}, groups: {}, players: {}, ...(prefs.customColors ?? {}) };
    const persist = () => savePrefs({ metric: prefs.metric, factions: prefs.factions, players: prefs.players,
      subjects: prefs.subjects, tags: prefs.tags, colors: prefs.colors, game: prefs.game, compare: prefs.compare,
      groupColors: prefs.groupColors, playerColors: prefs.playerColors, hiddenGroups: prefs.hiddenGroups,
      hiddenPlayers: prefs.hiddenPlayers, customColors: prefs.customColors, openGroups: prefs.openGroups });
    // what one line of the chart is: a country, a group (faction) or a human player
    const mode = () => (prefs.players ? 'players' : prefs.factions ? 'factions' : 'countries');
    const status = h('div', { class: 'gs-rec' });
    const controls = h('div', { class: 'gs-controls' });
    let search = '';
    const searchInput = h('input', { type: 'search', class: 'gs-search', placeholder: 'Search tag or name',
      oninput: (e) => { search = e.target.value; renderPicker(); } });
    const pickerHead = h('div', { class: 'gs-picker-head' });
    const pickerList = h('div', { class: 'gs-picker-list' });
    const picker = h('div', { class: 'gs-picker' }, pickerHead, searchInput, pickerList);
    const charts = h('div', { class: 'gs-charts' });
    const equipment = equipmentSection(ctx);   // the separate equipment chart at the bottom
    const notesBox = notesSection(ctx, () => renderCharts());
    const ranking = rankingSection(ctx);
    const campaignMap = mapSection(ctx);
    const sessions = sessionsSection(ctx);
    const pickDay = (t) => notesBox.pick(t);
    root.append(viewHeader('Game summary', 'IC a day per country over the campaign, recorded from game memory while the app runs.'),
      status, card('IC a day', [controls, h('div', { class: 'gs-body' }, picker, charts)], { cls: 'gs-main' }), notesBox.el,
      ranking.el, campaignMap.el, equipment.el, sessions.el);

    let games = [];
    let recorder = {};
    let running = null;   // the running game: {campaign, player, date, known}
    let knownActive;      // id of the campaign being recorded at the last load (watch)
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
      if (mode() === 'players') { p.set('players', '1'); p.set('subjects', prefs.subjects ? '1' : '0'); }
      else if (prefs.factions) p.set('factions', '1'); else p.set('tags', prefs.tags.join(','));
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
    const colorMap = () => prefs.customColors[{ players: 'players', factions: 'groups', countries: 'countries' }[mode()]];
    const colorSlots = () => ({ players: prefs.playerColors, factions: prefs.groupColors, countries: prefs.colors }[mode()]);
    const seriesColor = (k) => colorMap()[k] ?? SERIES_COLORS[colorSlots()[k]];
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

    function visiblePlayers() {
      return main.series.map((s) => s.key).filter((k) => !prefs.hiddenPlayers.includes(k)).slice(0, MAX_SERIES);
    }

    // Players: one line per human player (the player's country, plus its subjects when "Include subjects" is on)
    function renderPlayers() {
      const visible = visiblePlayers();
      pickerHead.replaceChildren(`Players (${visible.length}/${main.players.length} shown)`);
      const toggle = (k, shown) => {
        prefs.hiddenPlayers = shown ? [...prefs.hiddenPlayers, k] : prefs.hiddenPlayers.filter((x) => x !== k);
        load();
      };
      const subjectsSwitch = h('label', { class: 'gs-country', title: 'Count the IC of each player\'s subjects (puppets, '
        + 'dominions...) with the player - the subjects of each day, as recorded' },
        h('input', { type: 'checkbox', checked: prefs.subjects || null,
          onchange: (e) => { prefs.subjects = e.target.checked; load(); } }),
        h('span', null, 'Include subjects'));
      const list = main.players.filter((p) => matches({ tag: p.tag, name: `${p.name} ${p.country}` }, search));
      pickerList.replaceChildren(subjectsSwitch,
        ...(list.length ? list.map((p) => {
          const shown = visible.includes(p.name);
          return h('div', { class: 'gs-player' },
            h('label', { class: `gs-country ${shown ? 'gs-country-on' : ''}`, title: `${p.name} - ${p.country}` },
              h('input', { type: 'checkbox', checked: shown || null, disabled: (!shown && visible.length >= MAX_SERIES) || null,
                onchange: () => toggle(p.name, shown) }),
              h('span', { class: 'gs-country-tag' }, p.name, shown ? colorInput(p.name) : null),
              h('span', { class: 'gs-country-tag muted' }, p.tag),
              h('span', { class: 'gs-country-value' }, p.value == null ? '-' : compact(p.value))),
            prefs.subjects && p.subjects.length ? h('div', { class: 'gs-member muted', title: 'Subjects counted with the player' },
              `+ ${p.subjects.join(', ')}`) : null);
        }) : [h('p', { class: 'muted' }, main.players.length ? 'No player matches.'
          : 'No players recorded for this campaign.')]));
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
      const state = on ? ['gs-rec-on', 'Recording'] : live ? ['gs-rec-wait', 'Waiting for the game (in the menu, or the next game day)']
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
            select(opts.filter(([v]) => v !== prefs.game), prefs.compare, pick((v) => { prefs.compare = v || null; }), '-')),
          prefs.game ? h('button', { class: 'btn btn-small gs-report-btn', disabled: reporting || null,
            title: 'One HTML file with the charts of the lines shown, the ranking, the sessions, the notes and the map - to send to the other players',
            onclick: exportReport }, reporting ? 'Making the report…' : 'Export report') : null),
        h('div', { class: 'gs-row' },
          ...[['IC a day', IC_METRICS], ['Factories', FACTORY_METRICS], ['IC per factory', PER_FACTORY_METRICS],
            ['Wasted IC', WASTED_METRICS], ['IC lost', [...LOSS_METRICS, ...KD_METRICS]],
            ...METRIC_GROUPS.filter(([, list]) => list)]
            .map(([label, list]) => h('div', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, label),
              seg(list.map(([k, , b]) => [k, b]), prefs.metric, pick((v) => { prefs.metric = v; })))),
          h('div', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, 'Show'),
            seg([['countries', 'Countries'], ['factions', 'Factions'], ['players', 'Players']], mode(),
              pick((v) => { prefs.players = v === 'players'; prefs.factions = v === 'factions'; })))));
    }

    function renderPicker() {
      if (!main) { picker.hidden = true; return; }
      picker.hidden = false;
      if (mode() === 'players') { renderPlayers(); return; }
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
      const keys = mode() === 'players' ? visiblePlayers() : prefs.factions ? visibleGroups()
        : main.series.map((s) => s.key).slice(0, MAX_SERIES);
      if (mode() === 'players') prefs.playerColors = assignColors(keys, prefs.playerColors);
      else if (prefs.factions) prefs.groupColors = assignColors(keys, prefs.groupColors);
      else prefs.colors = assignColors(keys, prefs.colors);
      const slots = colorSlots();
      const colorOf = (k) => (keys.includes(k) ? (colorMap()[k] ?? SERIES_COLORS[slots[k]]) : null);
      const build = (game, cum, dash, suffix) => game.series
        .filter((s) => colorOf(s.key))
        .map((s) => ({ label: `${s.key}${suffix}`, color: colorOf(s.key), dash,
          points: (cum ? cumulative(game.t, s.values) : s.values).map((v, j) => [game.t[j], v]).filter((p) => p[1] != null) }));
      const metric = METRICS.find(([k]) => k === prefs.metric)[1];
      const sets = (cum) => [...build(main, cum, false, other ? ' (1)' : ''), ...(other ? build(other, cum, true, ' (2)') : [])];
      if (!keys.length) {
        charts.replaceChildren(notice('info', mode() === 'players' ? (main.players.length ? 'Tick the players to show on the left.'
          : 'No players recorded for this campaign yet - the recorder notes them once a game day from now on.')
          : prefs.factions ? 'Tick the groups to show on the left.' : 'Pick up to 8 countries on the left.'));
        return;
      }
      const last = main.t.length - 1;
      const table = h('details', { class: 'gs-table', open: tableOpen || null, ontoggle: (e) => { tableOpen = e.target.open; } },
        h('summary', null, 'Table'),
        h('table', { class: 'table' },
          h('thead', null, h('tr', null, h('th', null, { players: 'Player', factions: 'Faction', countries: 'Country' }[mode()]),
            h('th', null, `${isLevelMetric(prefs.metric) ? metric : 'IC a day'} (${dayText(main.t[last])})`),
            isLevelMetric(prefs.metric) ? null : h('th', null, 'Cumulative IC'))),
          h('tbody', null, main.series.filter((s) => keys.includes(s.key)).map((s) => h('tr', null, h('td', null, s.key),
            h('td', { class: 'num' }, s.values[last] == null ? '—' : PERCENT_METRICS.includes(prefs.metric) || prefs.metric === 'kd'
              ? metricFormat(prefs.metric)(s.values[last]) : s.values[last].toLocaleString(numberLocale(),
                { maximumFractionDigits: isPerFactoryMetric(prefs.metric) ? 2 : 1 })),
            isLevelMetric(prefs.metric) ? null
              : h('td', { class: 'num' }, cumulative(main.t, s.values)[last]?.toLocaleString(numberLocale(), { maximumFractionDigits: 0 }) ?? '—'))))));
      const level = isLevelMetric(prefs.metric);
      const markers = notesBox.notes.map((n) => ({ t: n.t, label: n.text }));
      const sync = hoverSync();   // the hovered day shows in both charts
      charts.replaceChildren(...[   // replaceChildren would print a null
        isLossMetric(prefs.metric) || prefs.metric === 'kd' ? patchBar() : null,
        isLossMetric(prefs.metric) ? lossNotice(keys) : null,
        isExtraMetric(prefs.metric) ? notice('info', extraNote(prefs.metric)) : null,
        prefs.metric.startsWith('w') ? notice('info', 'Factories without a production or construction line, at the '
          + 'country\'s own IC per assigned factory that day (a construction line takes at most 15 factories).') : null,
        isPerFactoryMetric(prefs.metric) ? notice('info', 'IC a day the game produced per factory working on a line - '
          + 'production efficiency, factory / dockyard output and construction speed bonuses, resource shortages. Idle '
          + 'factories do not count; a group is its IC divided by its factories. Civilian: construction only (not consumer '
          + 'goods or trade), on days recorded from 2026-10-20.') : null,
        lineChart({ title: level ? metric : `Daily ${metric}`, series: sets(false), sync, format: metricFormat(prefs.metric),
          markers, onPick: pickDay }),
        level ? null : lineChart({ title: `Cumulative ${metric}`, series: sets(true), sync, markers, onPick: pickDay }),
        table].filter(Boolean));
    }

    let reporting = false;
    async function exportReport() {
      if (!main || reporting) return;
      reporting = true;
      renderControls();
      try {
        const keys = mode() === 'players' ? visiblePlayers() : prefs.factions ? visibleGroups() : prefs.tags.slice(0, MAX_SERIES);
        const slots = colorSlots();
        const colorOf = (k) => colorMap()[k] ?? SERIES_COLORS[slots[k] ?? keys.indexOf(k) % SERIES_COLORS.length];
        const series = {};
        for (const [metric] of REPORT_METRICS) {
          const p = new URLSearchParams(query());
          p.set('metric', metric);
          series[metric] = (await ctx.api.get(`${gameUrl(prefs.game)}?${p}`)).data;
        }
        const get = (part) => ctx.api.get(`${gameUrl(prefs.game)}/${part}`).then((r) => r.data, () => null);
        const [rank, sess] = await Promise.all([get(`ranking?subjects=${prefs.subjects ? 1 : 0}`), get('sessions')]);
        const g = games.find((x) => x.id === prefs.game);
        const html = reportHtml({ title: `Campaign ${gameLabel(g)}`, subtitle: `Recording started ${startedText(g.created)} · report made `
          + `${new Date().toLocaleString()}`, series, keys, colorOf, ranking: rank, sessions: sess, notes: notesBox.notes,
        map: campaignMap.snapshot(), mode: { players: 'players', factions: 'groups', countries: 'countries' }[mode()] });
        download(reportName(prefs.game), html);
      } catch (err) {
        charts.prepend(notice('warn', `Report not made: ${err.message}`));
      }
      reporting = false;
      renderControls();
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
        if (main && mode() === 'countries' && !prefs.tags.length) {   // first visit: the player and the biggest producers
          prefs.tags = [...new Set([main.player, ...main.countries.map((c) => c.tag)].filter((t) => main.countries.some((c) => c.tag === t)))].slice(0, 5);
          main = await fetchGame(prefs.game);
        }
        other = prefs.compare ? await fetchGame(prefs.compare, prefs.game) : null;
        groups = main ? (await ctx.api.get(`${gameUrl(prefs.game)}/groups`)).data : { custom: [], assign: {} };
        if ((isLossMetric(prefs.metric) || prefs.metric === 'kd') && !patchBusy) {
          patch = await ctx.api.get('/api/live/combat-log-patch').then((r) => r.data, (err) => ({ ...(patch ?? {}), error: err.message }));
        }
        if (stopped) return;
        const a = document.activeElement;   // do not reset a list being picked or a group name being typed
        if (!(pickerList.contains(a) && (a.tagName === 'SELECT' || a.type === 'text'))) renderPicker();
        renderCharts();
        if (main) equipment.update(prefs.game, main.countries, main.player);
        notesBox.update(main ? prefs.game : null, main?.t[main.t.length - 1] ?? null);
        ranking.update(main ? prefs.game : null, prefs.subjects);
        campaignMap.update(main ? prefs.game : null);
        sessions.update(main ? prefs.game : null);
      } catch (err) {
        if (!stopped) charts.replaceChildren(notice('warn', `Game summary unavailable: ${err.message}`));
      }
      clearTimeout(timer);
      knownActive = games.find((g) => g.active)?.id ?? null;
      // the campaign being recorded is read again; otherwise only the list is watched for a new recording
      if (!stopped) timer = setTimeout(games.find((g) => g.id === prefs.game)?.active ? load : watch, refreshMs(REFRESH_MS));
    }

    /** Light check while an old campaign (or none) is shown: a new recording (a game started, 2026-10-20 user's
     * report: the view stayed on "No campaign recorded yet") is opened, another change of the list shown. */
    async function watch() {
      if (stopped) return;
      try {
        const list = (await ctx.api.get('/api/summary/games')).data.games;
        if (stopped) return;
        const active = list.find((g) => g.active)?.id ?? null;
        if (active !== knownActive || list.length !== games.length) {
          if (active && active !== knownActive) prefs.game = active;
          load();
          return;
        }
      } catch { /* the backend is restarting: try again */ }
      timer = setTimeout(watch, refreshMs(REFRESH_MS));
    }

    await load();
    return () => {
      stopped = true;
      clearTimeout(timer);
      campaignMap.stop();
      document.removeEventListener('click', closeCampaigns);
      document.removeEventListener('keydown', closeCampaigns);
    };
  },
};
