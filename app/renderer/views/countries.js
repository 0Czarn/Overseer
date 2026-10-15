import { h, card, demoBanner, keyValues, notice, sourceBadge, table, tabs, viewHeader } from '../lib/dom.js';
import { filterByText } from '../lib/format.js';
import { headerDetails, modsList, playersTable, pollAnalysis, saveBanner, saveError, saveSelect } from './save-ui.js';

const LIVE_POLL_MS = 3000;
import { loadCountries, tagChip } from './shared.js';
import { refreshMs } from '../lib/options.js';

function savePlayersCard(ctx) {
  const body = h('div', { class: 'card-body-inner' });
  const selectHost = h('div', { class: 'toolbar' });
  let stop = () => {};

  const show = (res) => {
    const analysis = res.data;
    if (!analysis) {
      body.replaceChildren(notice('muted', res.note ?? 'No save available.'));
      return;
    }
    body.replaceChildren(
      saveBanner(analysis),
      saveError(analysis) ?? '',
      analysis.header ? h('div', { class: 'split' },
        h('div', null, h('h4', null, 'Players in this save'), playersTable(analysis.header)),
        h('div', null, h('h4', null, 'Save header'), headerDetails(analysis), modsList(analysis.header))) : '',
    );
  };
  const load = (name) => {
    stop();
    body.replaceChildren(h('p', { class: 'muted' }, 'Copying and reading the save…'));
    stop = pollAnalysis(ctx, name, show);
  };

  const start = async () => {
    const list = await ctx.api.get('/api/saves');
    const saves = list.data?.saves ?? [];
    if (!saves.length) {
      body.replaceChildren(notice('muted', list.note ?? 'No save files found.'));
      return;
    }
    const current = ctx.state.selectedSave && saves.some((s) => s.name === ctx.state.selectedSave)
      ? ctx.state.selectedSave : saves[0].name;
    selectHost.replaceChildren(h('span', { class: 'muted' }, 'Save file'),
      saveSelect(saves, current, (name) => { ctx.state.selectedSave = name; load(name); }));
    load(current);
  };

  const el = card('Players (from save file)', [
    h('p', { class: 'hint' }, 'Player-to-country assignment as stored in a save. A save is a snapshot - check the '
      + 'date and session status below before relying on it.'),
    selectHost, body,
  ], { extra: sourceBadge('save') });
  return { el, start, stop: () => stop() };
}

function countriesCard(ctx, res) {
  let filter = '';
  let showAll = false;
  const known = res.source !== 'demo' && res.data.some((c) => c.exists !== undefined && c.exists !== null);
  const listHost = h('div');
  const selectedLabel = h('span', { class: 'muted' });

  const renderList = () => {
    selectedLabel.textContent = `Selected: ${ctx.state.selectedCountry}`;
    const pool = known && !showAll ? res.data.filter((c) => c.exists) : res.data;
    const rows = filterByText(pool, filter, ['tag', 'name', 'player', 'ruling_party']);
    listHost.replaceChildren(table([
      { key: 'tag', label: 'Tag', render: (r) => tagChip(r.tag) },
      { key: 'name', label: 'Name' },
      ...(res.source === 'demo' ? [] : [
        { key: 'ruling_party', label: 'Ruling party', render: (r) => r.ruling_party ?? h('span', { class: 'muted' }, '—') },
        { key: 'states', label: 'States', render: (r) => (r.exists === null ? '—' : r.exists ? String(r.states) : h('span', { class: 'muted' }, 'does not exist')) },
      ]),
      { key: 'player', label: res.source === 'demo' ? 'Player (DEMO)' : 'Player',
        render: (r) => r.player ?? h('span', { class: 'muted' }, 'AI') },
      { key: 'actions', label: '', cls: 'actions', render: (r) => countryActions(ctx, r.tag) },
    ], rows, {
      keyField: 'tag',
      selectedKey: ctx.state.selectedCountry,
      onRowClick: (r) => { ctx.setState({ selectedCountry: r.tag }); renderList(); },
      empty: 'No countries match the filter',
    }));
  };
  renderList();
  return card('Countries', [
    res.source === 'demo' ? demoBanner(`${res.note} No game installation or save was found.`) : h('p', { class: 'hint' }, res.note),
    h('div', { class: 'toolbar' },
      h('input', { class: 'input', type: 'search', placeholder: 'Filter by tag, name, party or player…',
        onInput: (e) => { filter = e.target.value; renderList(); } }),
      known ? h('label', { class: 'switch' }, h('input', { type: 'checkbox', onChange: (e) => { showAll = e.target.checked; renderList(); } }),
        h('span', null, 'Show tags that do not exist')) : null),
    listHost,
  ], { extra: h('span', { class: 'view-extras' }, selectedLabel, sourceBadge(res.source, res.note)) });
}

function countryActions(ctx, tag) {
  const open = (view) => { ctx.setState({ selectedCountry: tag }); ctx.navigate(view); };
  return h('div', { class: 'btn-row' },
    h('button', { class: 'btn btn-small', onClick: (e) => { e.stopPropagation(); open('country-editor'); } }, 'Edit'),
    h('button', { class: 'btn btn-small btn-ghost', onClick: (e) => { e.stopPropagation(); open('focus'); } }, 'Focus'));
}

/** Countries and players of the RUNNING game, re-read from game memory every few seconds. */
function liveTab(ctx) {
  const body = h('div', { class: 'card-body-inner' });
  let filter = '';
  let timer = null;
  let running = false;
  let last = null;

  const render = (res, error) => {
    if (error) {
      body.replaceChildren(notice('muted', error));
      return;
    }
    const d = res.data;
    const mode = d.game_mode === 'MULTIPLAYER' ? h('span', { class: 'session-mp' }, 'Multiplayer')
      : d.game_mode === 'SINGLEPLAYER' ? h('span', { class: 'session-sp' }, 'Single player')
        : h('span', { class: 'muted' }, 'unknown (no launch line in game.log)');
    const rows = filterByText(d.countries, filter, ['tag', 'name', 'player']);
    body.replaceChildren(
      h('p', { class: 'hint' }, res.note, ` Updated ${new Date(d.read_at * 1000).toLocaleTimeString()}.`),
      h('div', { class: 'split' },
        h('div', null, h('h4', null, 'Session'), keyValues([
          ['Game mode', mode],
          ['Countries in play', String(d.countries.length)],
        ])),
        h('div', null, h('h4', null, 'Players in this session'), table([
          { key: 'tag', label: 'Country', render: (p) => tagChip(p.tag, 'tag-chip-warn') },
          { key: 'name', label: 'Player', render: (p) => p.name ?? h('span', { class: 'muted' }, 'unknown') },
          { key: 'local', label: '', render: () => h('span', { class: 'muted' }, 'you (this computer)') },
        ], d.players, { keyField: 'tag', empty: 'Player country not readable (fog of war off?)' }),
        d.game_mode === 'MULTIPLAYER'
          ? notice('warn', 'Other players of a multiplayer session are not read from game memory yet (needs a '
            + 'test with two clients). See Save files for the list stored in the newest save.') : null)),
      h('h4', null, 'Countries in the running game'),
      table([
        { key: 'tag', label: 'Tag', render: (r) => tagChip(r.tag) },
        { key: 'name', label: 'Name' },
        { key: 'states', label: 'States', render: (r) => String(r.states) },
        { key: 'player', label: 'Player', render: (r) => r.player ?? h('span', { class: 'muted' }, 'AI / not read') },
        { key: 'actions', label: '', cls: 'actions', render: (r) => countryActions(ctx, r.tag) },
      ], rows, {
        keyField: 'tag',
        selectedKey: ctx.state.selectedCountry,
        onRowClick: (r) => { ctx.setState({ selectedCountry: r.tag }); render(res); },
        empty: 'No countries match the filter',
      }));
  };

  const tick = async () => {
    if (!running) return;
    try {
      last = await ctx.api.get('/api/live/session');
      if (running) render(last);
    } catch (err) {
      if (running) render(null, `Live data unavailable: ${err.message}`);
    }
    if (running) timer = setTimeout(tick, refreshMs(LIVE_POLL_MS));
  };
  const start = () => {
    if (running) return;
    running = true;
    if (!last) body.replaceChildren(h('p', { class: 'muted' }, 'Reading the running game…'));
    tick();
  };
  const stop = () => { running = false; clearTimeout(timer); };

  const el = card('Live session', [
    h('p', { class: 'hint' }, 'Read from the memory of the running game (read-only). Countries that own at least '
      + 'one state take part; the game mode comes from the game log.'),
    h('div', { class: 'toolbar' }, h('input', { class: 'input', type: 'search', placeholder: 'Filter by tag, name or player…',
      onInput: (e) => { filter = e.target.value; if (last) render(last); } })),
    body,
  ], { extra: sourceBadge('live') });
  return { el, start, stop };
}

export default {
  id: 'countries',
  title: 'Countries & Players',
  short: 'CP',
  async render(root, ctx) {
    const res = await loadCountries(ctx);
    const players = savePlayersCard(ctx);
    const live = liveTab(ctx);
    await players.start();
    const onMain = (id) => {
      ctx.state.countriesTab = id;
      if (id === 'live') live.start(); else live.stop();
    };
    const saveTabs = tabs([
      { id: 'players', label: 'Players (from save file)', panel: players.el },
      { id: 'countries', label: 'Countries', panel: countriesCard(ctx, res) },
    ], ctx.state.countriesSaveTab, (id) => { ctx.state.countriesSaveTab = id; }, { cls: 'tabs-sub' });
    root.append(
      viewHeader('Countries & Players', 'Pick any country to inspect - independent of the country you control.'),
      tabs([
        { id: 'saves', label: 'Save files', panel: saveTabs },
        { id: 'live', label: 'Live', panel: live.el },
      ], ctx.state.countriesTab, onMain),
    );
    if (ctx.state.countriesTab === 'live') live.start();
    return () => { players.stop(); live.stop(); };
  },
};
