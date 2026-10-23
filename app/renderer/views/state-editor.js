import { h, card, demoBanner, keyValues, notice, select, sourceBadge, table, viewHeader } from '../lib/dom.js';
import { filterByText, humanize } from '../lib/format.js';
import { loadCountries, tagChip } from './shared.js';
import { refreshControl } from '../lib/refresh.js';
import { iconImg, modifierIcon } from '../lib/icons.js';
import { numberLocale } from '../lib/options.js';
import { loadMap, mapView, rgb, shade } from '../lib/mapview.js';

function chips(tags) {
  return tags?.length ? h('span', { class: 'chip-row' }, tags.map((t) => tagChip(t))) : h('span', { class: 'muted' }, '—');
}

/** Buildings / resources with their icons (mods Modifier Icons / Descriptive Icons, by the building or resource
 *  id); a building without one (landmarks, mod buildings) gets the generic building icon. */
function amounts(obj, fallback = null) {
  const entries = Object.entries(obj ?? {});
  if (!entries.length) return h('span', { class: 'muted' }, 'None');
  return h('ul', { class: 'amounts' }, entries.map(([k, v]) => h('li', null,
    h('span', { class: 'amount-name' }, modifierIcon(k) ?? (fallback ? iconImg(fallback) : null), humanize(k)), h('b', null, v))));
}

const fmtInt = (v) => (v === null || v === undefined ? '—' : Math.round(v).toLocaleString(numberLocale()));

function detail(state) {
  if (!state) return notice('muted', 'Select a state to see details.');
  const occupied = state.owner !== state.controller;
  const split = Object.keys(state.controllers ?? {}).length > 1;
  return [
    h('h3', null, state.name, ' ', h('code', { class: 'muted' }, state.id)),
    keyValues([
      ['Owner', tagChip(state.owner)],
      ['Controller', [tagChip(state.controller, occupied ? 'tag-chip-warn' : ''),
        occupied ? h('span', { class: 'warn-text' }, ' controlled by another country') : null,
        split ? h('span', { class: 'muted' }, ` (provinces: ${Object.entries(state.controllers).map(([t, n]) => `${t} ${n}`).join(', ')})`) : null]],
      ['Cores', chips(state.cores)],
      ['Claims', chips(state.claims)],
      state.category ? ['Category', humanize(state.category)] : null,
      state.manpower ? ['Manpower pool', `${fmtInt(state.manpower.available)} available · ${fmtInt(state.manpower.locked)} locked · ${fmtInt(state.manpower.total)} total`] : null,
      state.provinces ? ['Provinces', String(state.provinces)] : null,
    ].filter(Boolean)),
    h('div', { class: 'two-col' },
      h('div', null, h('h4', null, 'State buildings'), amounts(state.buildings, 'building_slot_building_texticon.png')),
      h('div', null, h('h4', null, 'Resources'), amounts(state.resources))),
    state.province_buildings ? h('div', null, h('h4', null, 'Province buildings (sum of levels)'), amounts(state.province_buildings, 'building_slot_building_texticon.png')) : null,
    h('p', { class: 'hint' }, 'Buildings and resources are listed by the names the save uses, including ones added by mods. '
      + 'Names shown as #xxxx are binary-save codes not mapped yet.'),
  ].filter(Boolean);
}

// Save: the newest save (every detail, a snapshot). Live: game memory (owner, controller, cores, claims, category,
// buildings, resources, manpower - no province buildings), re-read every few seconds or with the ↻ button.
const SOURCE_KEY = 'hoi4dbg.stateSource';
const MAP_KEY = 'hoi4dbg.stateMap';   // {mode: owner | controller, provinces, states}
const loadMapPrefs = () => { try { return { mode: 'owner', provinces: true, states: true, ...JSON.parse(localStorage.getItem(MAP_KEY)) }; } catch { return { mode: 'owner', provinces: true, states: true }; } };

/** The map tile of the State Editor (2026-10-22, user's request: "the map divided into states and provinces"): the
 *  game's map coloured by owner or controller, province, state and country borders, the chosen state outlined; a
 *  click chooses a state. {el, draw()} - `get()` gives {states, selected, owner}, `pick(id)` chooses a state. */
function stateMap(ctx, get, pick) {
  const prefs = loadMapPrefs();
  const body = h('div', { class: 'se-map' }, h('p', { class: 'muted' }, 'Reading the game\'s map…'));
  const options = h('div', { class: 'se-map-options' });
  const el = card('Map', [options, body], { cls: 'se-map-card' });
  let map = null;
  let view = null;
  let byId = new Map();
  const save = () => { try { localStorage.setItem(MAP_KEY, JSON.stringify(prefs)); } catch { /* preference only */ } };

  function renderOptions() {
    const seg = (items, value, onPick) => h('div', { class: 'gs-seg' }, items.map(([v, label]) =>
      h('button', { class: `gs-seg-btn ${v === value ? 'gs-seg-on' : ''}`, onclick: () => onPick(v) }, label)));
    const box = (key, label, title) => h('label', { class: 'se-map-check', title },
      h('input', { type: 'checkbox', checked: prefs[key] || null, onchange: (e) => { prefs[key] = e.target.checked; save(); draw(); } }), label);
    options.replaceChildren(
      seg([['owner', 'Owner (occupied: stripes)'], ['controller', 'Controller']], prefs.mode,
        (v) => { prefs.mode = v; save(); renderOptions(); draw(); }),
      box('states', 'State borders', 'Dark lines between states'),
      box('provinces', 'Province borders', 'Thin lines between the provinces of a state'),
      h('span', { class: 'muted se-map-hint' }, 'Click a state to choose it · country borders in black'));
  }

  function hover(hit, ev) {
    if (!hit) { view.setTip(null); return; }
    const st = byId.get(hit.sid);
    const name = (tag) => (tag ? `${map.info.names[tag] ?? tag} (${tag})` : '—');
    view.setTip([h('strong', null, st?.name ?? map.info.states[hit.sid]?.name ?? (hit.sid ? `State ${hit.sid}` : 'No state')),
      h('div', { class: 'muted' }, `State ${hit.sid || '—'} · province ${hit.pid}`),
      st ? h('div', null, `Owner: ${name(st.owner)}`) : null,
      st && st.controller !== st.owner ? h('div', { class: 'bad-text' }, `Controller: ${name(st.controller)}`) : null,
      st?.category ? h('div', { class: 'muted' }, humanize(st.category)) : null], ev);
  }

  function draw() {
    if (!view) return;
    const { states, selected, owner } = get();
    byId = new Map(states.map((st) => [st.id, st]));
    const shown = (st) => (prefs.mode === 'controller' ? st.controller : st.owner);
    const numbers = new Map();
    const number = (tag) => { if (!tag) return 0; if (!numbers.has(tag)) numbers.set(tag, numbers.size + 1); return numbers.get(tag); };
    // with a country chosen in the list's filter, the other countries' states are dimmed
    const dim = (st, c) => (owner && st.owner !== owner && st.controller !== owner ? shade(c, 0.45) : c);
    view.draw({
      fill: (sid) => { const st = byId.get(sid); return st && shown(st) ? dim(st, rgb(map.info.colors[shown(st)])) : null; },
      stripe: (sid) => {
        const st = byId.get(sid);
        return st && prefs.mode === 'owner' && st.controller && st.owner && st.controller !== st.owner ? dim(st, rgb(map.info.colors[st.controller])) : null;
      },
      group: (sid) => { const st = byId.get(sid); return st ? number(shown(st)) : 0; },
      states: prefs.states, provinces: prefs.provinces, highlight: selected,
    });
  }

  (async () => {
    try {
      map = await loadMap(ctx);
    } catch (err) {
      body.replaceChildren(notice('warn', `The game's map is not readable: ${err.message}`));
      return;
    }
    view = mapView(map, 'state-map', { onHover: hover, onClick: (hit) => { if (hit.sid && byId.has(hit.sid)) pick(hit.sid); } });
    body.replaceChildren(view.el, h('p', { class: 'hint' }, 'The game\'s map with the mods it runs with (provinces from '
      + 'map/provinces.bmp, states from history/states); colours of the countries as on the game\'s political map.'));
    renderOptions();
    draw();
  })();
  renderOptions();
  return { el, draw };
}
const loadSource = () => { try { return localStorage.getItem(SOURCE_KEY) === 'live' ? 'live' : 'save'; } catch { return 'save'; } };

export default {
  id: 'state-editor',
  title: 'State Editor',
  short: 'SE',
  async render(root, ctx) {
    let source = loadSource();
    const fetchStates = () => ctx.api.get(`/api/states${source === 'live' ? '?source=live' : ''}`);
    let [res, countries] = await Promise.all([fetchStates(), loadCountries(ctx)]);
    let control = null;
    const badgeHost = h('span');
    const noteHost = h('div');
    const controlHost = h('span');
    const sourceSeg = h('div', { class: 'gs-seg', role: 'group', 'aria-label': 'Data source' });
    let owner = '';
    let text = '';
    let selected = res.data[0]?.id;
    const listHost = h('div');
    const detailHost = h('div', { class: 'detail' });

    const rerender = () => {
      const rows = filterByText(res.data.filter((s) => !owner || s.owner === owner || s.controller === owner),
        text, ['name', 'id']);
      listHost.replaceChildren(table([
        { key: 'name', label: 'State' },
        { key: 'owner', label: 'Owner', render: (s) => tagChip(s.owner) },
        { key: 'controller', label: 'Controller',
          render: (s) => tagChip(s.controller, s.controller !== s.owner ? 'tag-chip-warn' : '') },
        { key: 'cores', label: 'Cores', render: (s) => chips(s.cores) },
      ], rows.slice(0, 400), { selectedKey: selected, onRowClick: (s) => { selected = s.id; rerender(); }, empty: 'No states match' }),
      ...(rows.length > 400 ? [h('p', { class: 'hint' }, `Showing 400 of ${rows.length} states - use the filter or the country selector.`)] : []));
      detailHost.replaceChildren(...[detail(res.data.find((s) => s.id === selected))].flat());
      mapTile?.draw();
    };
    const mapTile = stateMap(ctx, () => ({ states: res.data, selected, owner }), (id) => {
      selected = id;
      rerender();
      listHost.querySelector('tr.selected, tr[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    });
    function meta() {
      badgeHost.replaceChildren(sourceBadge(res.source, res.note));
      noteHost.replaceChildren(res.source === 'demo' ? demoBanner(res.note) : h('p', { class: 'hint' }, res.note));
      sourceSeg.replaceChildren(...[['save', 'Save'], ['live', 'Live']].map(([k, label]) => h('button', {
        class: `gs-seg-btn ${source === k ? 'gs-seg-on' : ''}`, 'aria-pressed': String(source === k),
        title: k === 'live' ? 'From game memory - re-read every few seconds (no province buildings)' : 'From the newest save - a snapshot',
        onclick: () => setSource(k) }, label)));
      control?.stop();
      control = source === 'live' ? refreshControl('state-editor', 'States', () => reload()) : null;
      controlHost.replaceChildren(...(control ? [control.el] : []));
    }
    async function reload() {
      try {
        res = await fetchStates();
      } catch (err) {
        res = { source: 'unavailable', data: [], note: err.message };
      }
      if (!res.data.some((s) => s.id === selected)) selected = res.data[0]?.id;
      meta();
      rerender();
    }
    function setSource(k) {
      if (k === source) return;
      source = k;
      try { localStorage.setItem(SOURCE_KEY, k); } catch { /* preference only */ }
      reload();
    }
    meta();
    rerender();

    root.append(
      viewHeader('State Editor', 'Owner vs controller, buildings, resources, cores and claims.', sourceSeg, controlHost, badgeHost),
      noteHost,
      mapTile.el,
      h('div', { class: 'split' },
        card('States', [
          h('div', { class: 'toolbar' },
            h('input', { class: 'input', type: 'search', placeholder: 'Filter states…',
              onInput: (e) => { text = e.target.value; rerender(); } }),
            select([{ value: '', label: 'All countries' },
              ...countries.data.map((c) => ({ value: c.tag, label: `${c.tag} - ${c.name}` }))],
            owner, (v) => { owner = v; rerender(); }, { class: 'input', 'aria-label': 'Owner or controller' })),
          listHost,
        ]),
        card('Details', [detailHost, h('button', { class: 'btn', disabled: true,
          title: 'Editing not available yet' }, 'Edit state (not available)')])),
    );
    return () => control?.stop();
  },
};
