// Game summary - campaign map (2026-10-21, user's request): the game's own map (game files and the mods it runs with,
// lib/mapview.js) coloured by the owner or controller of every state on a recorded day, played back day by day. The
// recorded changes of owners and controllers come from ic_history.add_map.
// 2026-10-23 (user's request "a more detailed map"): the full-size map with names of countries and cities, state and
// province borders; coloured by country, faction (the user's groups of the Game summary) or player (with the subjects
// when the summary includes them), in the game's colours or the colours of the chart lines; the divisions of every
// country (a counter per province, per state when zoomed out) and an approximate fog of war from a country's view.
import { card, h, notice } from '../lib/dom.js';
import { dayText } from '../lib/linechart.js';
import { TERRAIN_STYLES, loadMap, mapView, placeLabels, provinceCentre, rgb, seenProvinces, terrainSwatch } from '../lib/mapview.js';
import { numberLocale } from '../lib/options.js';
import { divisionCard, dropDivisions } from './division-card.js';

export const TIME_MACHINE_KEY = 'hoi4dbg.timeMachine';   // what the Time machine opens with: {game, t, division, tag}

/** Opens the Time machine on campaign `game`, time `t` (days), a division and its country. */
export function openTimeMachine(ctx, target) {
  try { localStorage.setItem(TIME_MACHINE_KEY, JSON.stringify(target)); } catch { /* the Time machine starts empty */ }
  ctx.navigate('time-machine');
}

/** {province id: [division]} of the divisions read (GET .../divisions), each province's list by country and name. */
export function divisionsByProvince(list) {
  const out = {};
  for (const d of list ?? []) (out[d.pid] ??= []).push(d);
  for (const l of Object.values(out)) l.sort((a, b) => a.tag.localeCompare(b.tag) || (a.name ?? '').localeCompare(b.name ?? '', undefined, { numeric: true }));
  return out;
}

export { rgb };
const SPEEDS = [['Slow', 600], ['Normal', 250], ['Fast', 80]];
const PREFS_KEY = 'hoi4dbg.summaryMap';
const SUMMARY_KEY = 'hoi4dbg.summary';   // the Game summary's choices: chart colours, subjects of the players
const AI = [92, 90, 86];                 // countries without a player (Players)

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {}; } catch { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* preference only */ }
}
function summaryPrefs() {
  try { return JSON.parse(localStorage.getItem(SUMMARY_KEY)) ?? {}; } catch { return {}; }
}

/** {state id: [owner, controller]} on recorded row `index`: from the last full row before it, its changes on top. */
export function statesAt(rows, index) {
  let start = 0;
  for (let i = Math.min(index, rows.length - 1); i >= 0; i--) if (rows[i].full) { start = i; break; }
  const out = {};
  for (let i = start; i <= index && i < rows.length; i++) Object.assign(out, rows[i].s);
  return out;
}

/** {province id: controller} of the provinces held by another country than their state's controller on row `index`:
 * the last row up to it that lists them (rows recorded before 2026-10-23 have none: {}). */
export function frontAt(rows, index) {
  for (let i = Math.min(index, rows.length - 1); i >= 0; i--) {
    if (rows[i].x) return rows[i].x;
    if (rows[i].full) break;
  }
  return {};
}

// the infrastructure toggles; province buildings of the "infra" rows in their order (live INFRA_BUILDINGS): kind, toggle
const INFRA_PREFS = ['rails', 'ports', 'forts', 'hubs'];
const FRONT_PREFS = ['battles', 'moves'];
const BUILDINGS = [['hub', 'hubs'], ['port', 'ports'], ['fort', 'forts'], ['coastal', 'forts']];
const BUILDING_NAMES = { hub: 'Supply hub', port: 'Naval base', fort: 'Land fort', coastal: 'Coastal fort' };

/** "Battle: SOV attacks SLO - 6 vs 4 divisions, attacker 85%" of a battle (ic_history "front" c<province>). */
export function battleText([att, dfn, nAtt, nDef, share]) {
  return `Battle: ${att} attacks ${dfn} - ${nAtt} vs ${nDef} ${nDef === 1 ? 'division' : 'divisions'}, attacker ${share}%`;
}

/** Time of a row of the division, "infra" and "front" files in days: its day and game hour ("h", readings within a
 * day - ic_history.FRAME_HOURS). */
export function rowTime(r) {
  return r.t + (r.h ?? 0) / 24;
}

/** "1936.02.01", with the game hour when not the day's first reading: "1936.02.01 12:00". */
export function frameText(t) {
  const day = Math.floor(t);
  const hour = Math.round((t - day) * 24);
  return hour ? `${dayText(day)} ${String(hour).padStart(2, '0')}:00` : dayText(day);
}

/** {province id: {tag: [divisions, organisation, strength, {template: divisions}]}} at time `t` (days, rowTime) from
 * the division rows (ic_history.add_units; the same for the "infra" and "front" rows: {key: value}): the last full
 * row on or before it, the changes after it up to `t` (null: none left). */
export function unitsAt(rows, t) {
  let last = -1;
  for (let i = 0; i < rows.length && rowTime(rows[i]) <= t; i++) last = i;
  if (last < 0) return {};
  let start = 0;
  for (let i = last; i >= 0; i--) if (rows[i].full) { start = i; break; }
  const out = {};
  for (let i = start; i <= last; i++) {
    for (const [pid, v] of Object.entries(rows[i].u)) {
      if (v) out[pid] = v; else delete out[pid];
    }
  }
  return out;
}

/** The countries a country sees with: itself, its faction that day and its subjects. */
export function alliesOf(tag, factions = {}, players = {}) {
  const out = new Set([tag]);
  const faction = factions[tag];
  if (faction) for (const [t, f] of Object.entries(factions)) if (f === faction) out.add(t);
  for (const s of players[tag]?.s ?? []) out.add(s);
  return out;
}

/** Index of the last map row on or before day `t` (-1: none). */
export function rowAt(rows, t) {
  let found = -1;
  for (let i = 0; i < rows.length && rows[i].t <= t; i++) found = i;
  return found;
}

/** The value of a [[day, value]] list on day `t`: the last one on or before it, else the first one (null: none). */
export function valueAt(list, t) {
  let found = list?.[0]?.[1] ?? null;
  for (const [day, v] of list ?? []) {
    if (day > t) break;
    found = v;
  }
  return found;
}

/** Countries by number of states owned and controlled on a day: [{tag, owned, controlled, vp}], most first. */
export function standings(states, vps = {}) {
  const out = new Map();
  const row = (tag) => { if (!out.has(tag)) out.set(tag, { tag, owned: 0, controlled: 0, vp: 0 }); return out.get(tag); };
  for (const [sid, [owner, controller]] of Object.entries(states)) {
    if (owner) row(owner).owned += 1;
    if (controller) { row(controller).controlled += 1; row(controller).vp += vps[sid] ?? 0; }
  }
  return [...out.values()].sort((a, b) => b.controlled - a.controlled || b.owned - a.owned);
}

/** The key each country is shown under on a day: its tag (countries), its group (factions: the user's moves, else the
 * game's faction; null = non-aligned) or its player (the account name, also for the player's subjects when
 * `subjects`; null = AI). */
export function keyFn(mode, { factions = {}, groups = {}, players = {}, subjects = false } = {}) {
  if (mode === 'factions') {
    const assign = groups.assign ?? {};
    return (tag) => (tag in assign ? assign[tag] || null : factions[tag] ?? null);
  }
  if (mode === 'players') {
    const of = {};
    for (const [tag, info] of Object.entries(players ?? {})) {
      const key = info?.n || tag;
      if (subjects) for (const s of info?.s ?? []) of[s] ??= key;
      of[tag] = key;   // a player's own country before a subject of another
    }
    return (tag) => of[tag] ?? null;
  }
  return (tag) => tag ?? null;
}

/** Totals per key: [{key, owned, controlled, vp, lead}] (lead: the country of the key with most states controlled). */
export function keyStandings(rows, keyOf) {
  const out = new Map();
  for (const r of rows) {
    const key = keyOf(r.tag);
    if (key == null) continue;
    if (!out.has(key)) out.set(key, { key, owned: 0, controlled: 0, vp: 0, lead: r.tag });
    const s = out.get(key);
    s.owned += r.owned; s.controlled += r.controlled; s.vp += r.vp;   // rows come most states first: lead = first
  }
  return [...out.values()].sort((a, b) => b.controlled - a.controlled || b.owned - a.owned);
}

/** A number per key (borders between keys). */
function numbering() {
  const numbers = new Map();
  return (key) => {
    if (key == null) return 0;
    if (!numbers.has(key)) numbers.set(key, numbers.size + 1);
    return numbers.get(key);
  };
}

const mute = ([r, g, b]) => [Math.round(r * 0.45 + 50), Math.round(g * 0.45 + 50), Math.round(b * 0.45 + 50)];

/** The section: el, update(gameId), stop(), snapshot() - call update whenever the summary has read its campaign again.
 * `seriesColors`: the chart line colours by slot (the Game summary's palette). */
export function mapSection(ctx, { seriesColors = [] } = {}) {
  const prefs = { mode: 'owner', speed: 250, show: 'countries', colors: 'game', states: false, provinces: false,
    names: true, cities: true, units: true, fog: '', relief: true, rivers: true, rails: true, ports: true, forts: false,
    hubs: false, battles: true, moves: true, types: true, ...loadPrefs() };
  const body = h('div', { class: 'gs-map' }, h('p', { class: 'muted' }, 'Choose a campaign above.'));
  const el = card('Campaign map', body, { cls: 'gs-map-card' });
  let gid = null;
  let data = null;      // the recorded rows of the campaign
  let map = null;       // lib/mapview loadMap
  let view = null;
  let days = [];        // the recorded days (the slider)
  let index = -1;       // day shown
  let unitRows = [];    // division positions (ic_history.add_units)
  let units = {};       // divisions of the day shown
  let infraRows = [];   // railways and province buildings (ic_history "infra")
  let built = {};       // province -> [supply hub, naval base, fort, coastal fort] of the day shown
  let frontRows = [];   // moves and battles (ic_history "front")
  let battles = {};     // province -> [attacker, defender, attacking, defending divisions, attacker share %]
  let divisionsAt = null;   // [time, {province: [division]}] of each division (GET .../divisions), null: none read
  let divisionTimer = 0;
  let picked = null;    // province clicked
  let pickedDivision = null;
  let panel = null;     // beside the map: the divisions of the province clicked, the card of one
  let visible = null;   // provinces seen from prefs.fog (null: no fog)
  let follow = true;    // stay on the newest day while it is recorded
  let timer = null;
  let current = {};     // states of the day shown
  let front = {};       // provinces of the day shown held by another country than their state's controller
  let keyOf = (tag) => tag;
  let vps = {};
  let cities = [];
  let dateLabel = null;
  let slider = null;
  let legend = null;
  let terrainKey = null;   // what the terrain symbols mean
  let playBtn = null;
  let controls = null;
  let busy = false;

  const tagName = (tag) => map.info.names[tag] ?? tag;

  function draw() {
    if (!view) return;
    const t = days[index] ?? 0;
    const row = rowAt(data.rows, t);
    current = row >= 0 ? statesAt(data.rows, row) : {};
    front = row >= 0 ? frontAt(data.rows, row) : {};
    units = prefs.units || prefs.fog ? unitsAt(unitRows, t) : {};
    const infra = INFRA_PREFS.some((k) => prefs[k]) ? unitsAt(infraRows, t) : {};
    const fighting = FRONT_PREFS.some((k) => prefs[k]) ? unitsAt(frontRows, t) : {};
    const moves = [];
    battles = {};
    for (const [k, v] of Object.entries(fighting)) {
      if (k[0] === 'c') battles[k.slice(1)] = v;
      else if (prefs.moves) for (const [tag, n] of Object.entries(v)) moves.push([...k.slice(1).split('-').map(Number), tag, n]);
    }
    const rails = [];
    built = {};
    for (const [k, v] of Object.entries(infra)) {
      if (k[0] === 'b') built[k.slice(1)] = v;
      else if (prefs.rails) rails.push([...k.slice(1).split('-').map(Number), v]);
    }
    const summary = summaryPrefs();
    const factions = valueAt(data.factions, t) ?? {};
    const players = valueAt(data.players, t) ?? {};
    keyOf = keyFn(prefs.show, { factions, groups: data.groups, players, subjects: !!summary.subjects });
    visible = null;
    if (prefs.fog) {   // what the chosen country and its allies hold, and the provinces next to it
      const allies = alliesOf(prefs.fog, factions, players);
      const own = [];
      for (let p = 1; p < map.provState.length; p++) {
        const sid = map.provState[p];
        if (!sid || !map.prov.count[p]) continue;
        const controller = front[p] !== undefined ? front[p] : (current[sid] ?? [])[1];
        if (allies.has(controller)) own.push(p);
      }
      visible = seenProvinces(map, own);
    }
    const ranks = standings(current, vps);
    const totals = keyStandings(ranks, keyOf);
    const lead = Object.fromEntries(totals.map((s) => [s.key, s.lead]));
    const chart = { countries: summary.colors, factions: summary.groupColors, players: summary.playerColors }[prefs.show] ?? {};
    const keyColor = (key) => (prefs.colors === 'charts' && chart[key] != null && seriesColors[chart[key]]
      ? rgb(seriesColors[chart[key]]) : rgb(map.info.colors[prefs.show === 'countries' ? key : lead[key]]));
    const colorOf = (tag) => {
      if (!tag) return null;
      const key = keyOf(tag);
      if (key != null) return keyColor(key);
      return prefs.show === 'players' ? AI : mute(rgb(map.info.colors[tag]));   // AI / non-aligned
    };
    const shown = (sid) => (current[sid] ?? [])[prefs.mode === 'controller' ? 1 : 0];
    const number = numbering();
    const area = (tag) => keyOf(tag) ?? (tag ? `#${tag}` : null);   // a key, else the country alone
    const occupied = (owner, controller) => (prefs.mode === 'owner' && owner && controller && area(owner) !== area(controller)
      ? colorOf(controller) : null);
    const overrides = new Map();   // the front inside states: each province with its own controller
    for (const [pid, controller] of Object.entries(front)) {
      const sid = map.provState[pid];
      if (!sid) continue;
      const owner = (current[sid] ?? [])[0];
      const own = prefs.mode === 'controller' ? controller : owner;
      overrides.set(Number(pid), { fill: colorOf(own), stripe: occupied(owner, controller), group: number(area(own)) });
    }
    view.draw({
      fill: (sid) => colorOf(shown(sid)),
      stripe: (sid) => occupied(...(current[sid] ?? [])),
      group: (sid) => number(area(shown(sid))),
      states: prefs.states,
      provinces: prefs.provinces,
      overrides,
      visible,
    });
    const markers = [];
    if (prefs.units) {
      for (const [pid, byTag] of Object.entries(units)) {
        if (visible && !visible.has(Number(pid))) continue;
        for (const [tag, entry] of Object.entries(byTag)) {
          markers.push({ pid: Number(pid), key: area(tag), color: colorOf(tag) ?? [110, 108, 104], count: entry[0] });
        }
      }
    }
    const keyText = (key) => (key.startsWith('#') ? tagName(key.slice(1)) : prefs.show === 'countries' ? tagName(key) : key);
    view.terrain({ relief: prefs.relief, rivers: prefs.rivers, types: prefs.types });
    const marks = [];   // ports, forts, supply hubs (not in the fog of war)
    for (const [pid, levels] of Object.entries(built)) {
      if (visible && !visible.has(Number(pid))) continue;
      BUILDINGS.forEach(([kind, pref], i) => { if (prefs[pref] && levels[i]) marks.push({ pid: Number(pid), kind, level: levels[i] }); });
    }
    const arrows = moves.filter(([a]) => !visible || visible.has(a))
      .map(([a, b, tag, n]) => ({ from: a, to: b, color: colorOf(tag) ?? [110, 108, 104], count: n, attack: !!battles[b] }));
    const fights = prefs.battles ? Object.entries(battles).filter(([pid]) => !visible || visible.has(Number(pid)))
      .map(([pid, [att, dfn, , , share]]) => ({ pid: Number(pid), attacker: colorOf(att) ?? [110, 108, 104],
        defender: colorOf(dfn) ?? [110, 108, 104], share })) : [];
    view.labels({
      names: prefs.names ? placeLabels(map, (sid) => area(shown(sid)), keyText, (sid) => vps[sid]) : [],
      cities: prefs.cities ? cities : [],
      units: markers,
      rails,
      marks,
      arrows,
      battles: fights,
    });
    dateLabel.textContent = days[index] != null ? frameText(days[index]) : '—';
    slider.value = String(Math.max(0, index));
    readDivisions();
    const fmt = (v) => v.toLocaleString(numberLocale(), { maximumFractionDigits: 0 });
    const hex = (c) => `rgb(${c.join(',')})`;
    terrainKey.replaceChildren(...(prefs.types ? Object.keys(TERRAIN_STYLES).map((t) => h('span', { class: 'gs-terrain-item' },
      terrainSwatch(t), `${t[0].toUpperCase()}${t.slice(1)}`)) : []));
    legend.replaceChildren(...totals.slice(0, 14).map((s) => h('span', { class: 'gs-map-legend-item',
      title: `${keyText(s.key)}: ${s.owned} states owned, ${s.controlled} controlled, ${fmt(s.vp)} victory points` },
    h('span', { class: 'gs-map-swatch', style: { background: hex(keyColor(s.key)) } }),
    `${prefs.show === 'countries' ? s.key : keyText(s.key)} ${s.controlled}`)));
  }

  function hover(hit, ev) {
    if (!hit || !hit.sid) { view.setTip(null); return; }
    const [owner, stateController] = current[hit.sid] ?? [];
    const controller = front[hit.pid] !== undefined ? front[hit.pid] : stateController;
    const state = map.info.states[hit.sid] ?? { name: `State ${hit.sid}`, vp: 0 };
    const name = (tag) => (tag ? `${tagName(tag)} (${tag})` : '—');
    const key = keyOf(controller ?? owner);
    const group = prefs.show === 'countries' ? null
      : h('div', { class: 'muted' }, `${prefs.show === 'players' ? 'Player' : 'Faction'}: ${key ?? (prefs.show === 'players' ? 'AI' : 'non-aligned')}`);
    const seen = !visible || visible.has(hit.pid);
    const here = prefs.units && seen ? Object.entries(units[hit.pid] ?? {}) : [];
    const named = seen && divisionsAt ? divisionsAt[1][hit.pid] ?? [] : [];   // the divisions by name, when read
    const levels = seen ? built[hit.pid] ?? [] : [];
    const buildings = BUILDINGS.map(([kind], i) => (levels[i] ? `${BUILDING_NAMES[kind]} ${levels[i]}` : null)).filter(Boolean);
    const terrain = map.terrainTypes?.[map.provTerrain?.[hit.pid]];
    view.setTip([h('strong', null, state.name), h('div', null, `Owner: ${name(owner)}`),
      terrain ? h('div', { class: 'muted' }, `Terrain: ${terrain[0].toUpperCase()}${terrain.slice(1)}`) : null,
      controller && controller !== owner ? h('div', { class: seen ? 'bad-text' : 'muted' },
        seen ? `Controller: ${name(controller)}` : 'Controller: not seen (fog of war)') : null,
      group, state.vp ? h('div', { class: 'muted' }, `Victory points: ${state.vp}`) : null,
      buildings.length ? h('div', null, buildings.join(' · ')) : null,
      seen && battles[hit.pid] ? h('div', { class: 'bad-text' }, battleText(battles[hit.pid])) : null,
      ...here.map(([tag, [count, org, strength, templates]]) => {
        const names = named.filter((d) => d.tag === tag).map((d) => d.name ?? `Division ${d.id}`);
        return h('div', { class: 'gs-map-units' },
          h('strong', null, `${tag}: ${count} ${count === 1 ? 'division' : 'divisions'}`),
          ` · organisation ${org} · strength ${strength}`,
          names.length ? h('div', { class: 'gs-map-names' }, names.slice(0, 8).map((n) => h('div', null, n)),
            names.length > 8 ? h('div', { class: 'muted' }, `+${names.length - 8} more`) : null)
            : h('div', { class: 'muted' }, Object.entries(templates).map(([n, c]) => `${n} ×${c}`).join(', ')));
      }),
      named.length ? h('div', { class: 'muted' }, 'Click: the divisions here') : null,
      visible && !seen ? h('div', { class: 'muted' }, `Not seen by ${prefs.fog} (fog of war)`) : null], ev);
  }

  function stop() {
    clearInterval(timer);
    timer = null;
    if (playBtn) playBtn.textContent = '▶ Play';
    if (view) readDivisions();
  }

  function play() {
    if (timer) { stop(); return; }
    if (index >= days.length - 1) index = 0;
    follow = false;
    playBtn.textContent = '❚❚ Pause';
    timer = setInterval(() => {
      if (index >= days.length - 1) { stop(); follow = true; return; }
      index += 1;
      draw();
    }, prefs.speed);
  }

  function build() {
    view = mapView(map, 'campaign-map', { onHover: hover, onClick: pick });
    panel = h('aside', { class: 'gs-map-panel' });
    dateLabel = h('strong', { class: 'gs-map-date' });
    slider = h('input', { type: 'range', class: 'gs-map-slider', min: 0, max: Math.max(0, days.length - 1), value: index,
      'aria-label': 'Day', oninput: (e) => { stop(); index = Number(e.target.value); follow = index === days.length - 1; draw(); } });
    playBtn = h('button', { class: 'btn btn-small', onclick: play }, timer ? '❚❚ Pause' : '▶ Play');
    controls = h('div', { class: 'gs-map-options' });
    legend = h('div', { class: 'gs-map-legend' });
    terrainKey = h('div', { class: 'gs-map-legend gs-terrain-key' });
    body.replaceChildren(
      h('div', { class: 'gs-map-controls' }, playBtn, dateLabel, slider), controls,
      h('div', { class: 'gs-map-main' }, view.el, panel), legend, terrainKey,
      h('p', { class: 'hint' }, 'The game\'s map with the mods it runs with. Owner and controller of every state, recorded once a '
        + 'game day from game memory (from 2026-10-21); from 2026-10-23 also each province held by another country than '
        + 'its state\'s controller - the front inside states (older days show whole states). Factions: the groups of the '
        + 'chart above (your moves included); Players: with '
        + 'their subjects when the chart includes them. Chart colours: the colour of each line shown in the chart, the '
        + 'game\'s colour for the rest. City names show more the closer you zoom. Units: the divisions of every country '
        + '(from 2026-10-23) - a counter per province, per state when zoomed out; hover for their templates, organisation '
        + 'and strength. Fog of war: only what the chosen country, its faction and subjects hold and the provinces next '
        + 'to it - an approximation (the game also counts intelligence, radar, planes and ships). Terrain: the relief and '
        + 'the rivers of the game map (wider rivers from further away); from 100% the borders are drawn as smooth lines. '
        + 'Terrain types: each province as the game counts it in battle (map/definition.csv) - a tint, and symbols '
        + 'from 45% zoom. '
        + 'Infrastructure (from 2026-10-23, read every 3 game days): railways by level (thicker = higher; the low ones '
        + 'when zoomed in), and from 70% the ports (blue circle), forts (grey square; blue edge: coastal) and supply hubs '
        + '(orange) with their level. Front (from 2026-10-23): battles (crossed swords; the bar: the attacker share '
        + 'of both sides organisation x strength - close to the game bar, not the same) and arrows of the divisions '
        + 'moving (thin) or attacking (thick) into the next province. Divisions, moves and battles are read every 6 game '
        + 'hours, so the slider has up to 4 steps a day. '
        + 'Hover a state for its '
        + 'name; wheel: zoom, drag: move.'));
    renderControls();
  }

  function renderControls() {
    const redraw = () => { savePrefs(prefs); renderControls(); draw(); };
    const seg = (items, value, onPick) => h('div', { class: 'gs-seg' }, items.map(([v, label]) =>
      h('button', { class: `gs-seg-btn ${v === value ? 'gs-seg-on' : ''}`, 'aria-pressed': String(v === value),
        onclick: () => onPick(v) }, label)));
    const toggles = (items) => h('div', { class: 'gs-seg' }, items.map(([k, label]) =>
      h('button', { class: `gs-seg-btn ${prefs[k] ? 'gs-seg-on' : ''}`, 'aria-pressed': String(!!prefs[k]),
        onclick: async () => {
          prefs[k] = !prefs[k];
          if (k === 'units' && prefs.units && !unitRows.length) { await loadUnits(); refreshDays(); }
          if (INFRA_PREFS.includes(k) && prefs[k] && !infraRows.length) await loadInfra();
          if (FRONT_PREFS.includes(k) && prefs[k] && !frontRows.length) { await loadFront(); refreshDays(); }
          redraw();
        } }, label)));
    const field = (label, control) => h('div', { class: 'gs-field' }, h('span', { class: 'gs-seg-label' }, label), control);
    controls.replaceChildren(
      field('Show', seg([['countries', 'Countries'], ['factions', 'Factions'], ['players', 'Players']], prefs.show,
        (v) => { prefs.show = v; redraw(); })),
      field('Colours', seg([['game', 'Game'], ['charts', 'Chart lines']], prefs.colors, (v) => { prefs.colors = v; redraw(); })),
      field('Map', seg([['owner', 'Owner (occupied: stripes)'], ['controller', 'Controller']], prefs.mode,
        (v) => { prefs.mode = v; redraw(); })),
      field('Borders', toggles([['states', 'States'], ['provinces', 'Provinces']])),
      field('Names', toggles([['names', 'Countries'], ['cities', 'Cities'], ['units', 'Units']])),
      field('Terrain', toggles([['types', 'Terrain types'], ['relief', 'Relief'], ['rivers', 'Rivers']])),
      field('Infrastructure', toggles([['rails', 'Railways'], ['ports', 'Ports'], ['forts', 'Forts'], ['hubs', 'Supply hubs']])),
      field('Front', toggles([['battles', 'Battles'], ['moves', 'Moves']])),
      field('Fog of war', fogPicker(redraw)),
      field('Speed', seg(SPEEDS.map(([l, ms]) => [ms, l]), prefs.speed, (v) => {
        prefs.speed = v; savePrefs(prefs); renderControls();
        if (timer) { stop(); play(); }
      })));
  }

  /** Off, or a country to see the map as: the players of the day shown first, then every country holding land. */
  function fogPicker(redraw) {
    const players = Object.keys(valueAt(data.players, days[index] ?? 0) ?? {});
    const row = rowAt(data.rows, days[index] ?? 0);
    const holders = [...new Set(Object.values(row >= 0 ? statesAt(data.rows, row) : {}).map((v) => v[0]).filter(Boolean))]
      .filter((t) => !players.includes(t)).sort((a, b) => tagName(a).localeCompare(tagName(b)));
    const opt = (v, label) => h('option', { value: v, selected: v === prefs.fog || null }, label);
    return h('select', { class: 'gs-map-fog', 'aria-label': 'Fog of war', onchange: async (e) => {
      prefs.fog = e.target.value;
      if (prefs.fog && !unitRows.length) await loadUnits();
      redraw();
    } },
    opt('', 'Off'),
    players.length ? h('optgroup', { label: 'Players' }, players.map((t) => opt(t, `${tagName(t)} (${t})`))) : null,
    h('optgroup', { label: 'Countries' }, holders.map((t) => opt(t, `${tagName(t)} (${t})`))));
  }

  async function loadUnits() {
    try {
      unitRows = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(gid)}/units`)).data.rows;
    } catch {
      unitRows = [];   // the map still works without them
    }
  }

  async function loadFront() {
    try {
      frontRows = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(gid)}/front`)).data.rows;
    } catch {
      frontRows = [];
    }
  }

  /** The times the slider steps over: every recorded day, the map's own rows (the light days of a fast game, 2026-10-23)
   * and the readings within a day (divisions, battles). */
  function frames() {
    const all = new Set(data.t?.length ? data.t : []);
    for (const r of data.rows) all.add(r.t);
    for (const r of [...unitRows, ...frontRows]) all.add(rowTime(r));
    return [...all].sort((a, b) => a - b);
  }

  /** New slider steps (divisions or battles loaded): the same time stays shown. */
  function refreshDays() {
    const shownAt = days[index];
    days = frames();
    index = Math.max(0, days.findLastIndex((d) => d <= shownAt));
    if (slider) slider.max = String(Math.max(0, days.length - 1));
  }

  async function loadInfra() {
    try {
      infraRows = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(gid)}/infra`)).data.rows;
    } catch {
      infraRows = [];
    }
  }

  async function update(id) {
    if (busy) return;
    if (!id) { gid = null; stop(); view = null; body.replaceChildren(h('p', { class: 'muted' }, 'Choose a campaign above.')); return; }
    busy = true;
    try {
      const changed = id !== gid;
      const res = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(id)}/map`)).data;
      const fresh = await loadMap(ctx);
      const rebuilt = changed || !view || !map || fresh.info.key !== map.info.key;
      if (changed) { stop(); follow = true; }
      gid = id;
      data = res;
      map = fresh;
      if (changed) { divisionsAt = null; picked = null; pickedDivision = null; }
      dropDivisions();   // read again: the campaign may have been recorded further
      if (!data.rows.length) {
        view = null;
        body.replaceChildren(notice('info', 'No map recorded for this campaign yet - the owner and controller of every state are '
          + 'recorded once a game day from 2026-10-21 (keep the app open while you play).'));
        return;
      }
      if (prefs.units || prefs.fog) await loadUnits();
      if (INFRA_PREFS.some((k) => prefs[k])) await loadInfra();
      if (FRONT_PREFS.some((k) => prefs[k])) await loadFront();
      days = frames();
      if (follow && !timer) index = days.length - 1;
      index = Math.min(index, days.length - 1);
      vps = Object.fromEntries(Object.entries(map.info.states).map(([k, v]) => [k, v.vp]));
      if (rebuilt) {
        cities = (map.info.cities ?? []).map(([pid, vp, text]) => {
          const c = provinceCentre(map, pid);
          return c ? { text, x: c[0], y: c[1], vp } : null;
        }).filter(Boolean);
        build();
      }
      slider.max = String(days.length - 1);
      if (!timer) draw();
      renderPanel();
    } catch (err) {
      view = null;
      body.replaceChildren(notice('warn', `Campaign map unavailable: ${err.message}`));
    } finally {
      busy = false;
    }
  }

  /** The divisions of the time shown (GET .../divisions), read when the slider stops (not while playing). */
  function readDivisions() {
    clearTimeout(divisionTimer);
    if (timer || !gid || index < 0) return;
    const t = days[index];
    if (divisionsAt?.[0] === t) return;
    divisionTimer = setTimeout(async () => {
      try {
        const list = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(gid)}/divisions?t=${t}`)).data.divisions;
        if (days[index] !== t) return;
        divisionsAt = [t, divisionsByProvince(list)];
        renderPanel();
      } catch {
        divisionsAt = null;   // older campaigns: no division recorded on its own
      }
    }, 200);
  }

  function pick(hit) {
    picked = hit.pid;
    pickedDivision = null;
    renderPanel();
  }

  const placeName = (pid) => map.info.states[map.provState[pid]]?.name ?? `Province ${pid}`;

  /** The panel beside the map: the divisions of the province clicked, then the card of the one chosen. */
  function renderPanel() {
    if (!panel) return;
    const t = days[index];
    if (picked == null) {
      panel.replaceChildren(h('p', { class: 'muted' }, divisionsAt && Object.keys(divisionsAt[1]).length
        ? 'Click a province to see its divisions.' : 'Divisions one by one are recorded from 2026-10-23 - click a province.'));
      return;
    }
    const seen = !visible || visible.has(picked);
    const list = seen && divisionsAt ? divisionsAt[1][picked] ?? [] : [];
    const choose = (d) => () => { pickedDivision = d.id; renderPanel(); };
    panel.replaceChildren(...[
      h('div', { class: 'gs-panel-head' }, h('strong', null, placeName(picked)),
        h('button', { class: 'btn btn-small', title: 'Close', onclick: () => { picked = null; renderPanel(); } }, '×')),
      !seen ? h('p', { class: 'muted' }, `Not seen by ${prefs.fog} (fog of war).`)
        : !list.length ? h('p', { class: 'muted' }, divisionsAt ? 'No division here.' : 'No division recorded on its own for this time.')
          : h('div', { class: 'gs-div-list' }, list.map((d) => h('button', {
            class: `gs-div-item ${d.id === pickedDivision ? 'gs-div-on' : ''}`.trim(), onclick: choose(d) },
          h('span', { class: 'gs-div-tag' }, d.tag), h('span', { class: 'gs-div-name' }, d.name ?? `Division ${d.id}`),
          d.s ? h('span', { class: 'muted gs-div-stats' }, `${Math.round(d.s[0])} org · ${Math.round(d.s[1])} str`) : null))),
      pickedDivision != null && list.some((d) => d.id === pickedDivision)
        ? divisionCard(ctx, gid, pickedDivision, t, { place: placeName,
          onOpen: () => openTimeMachine(ctx, { game: gid, t, division: pickedDivision, tag: list.find((d) => d.id === pickedDivision)?.tag }) })
        : null].filter(Boolean));
  }

  /** {png, date} of the map shown with its names (half size, for the report), null without one. */
  function snapshot() {
    if (!view || index < 0) return null;
    return { png: view.snapshot(0.5).toDataURL('image/png'), date: frameText(days[index]) };
  }

  return { el, update, stop, snapshot };
}
