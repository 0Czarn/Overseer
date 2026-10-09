import { h, card, demoBanner, notice, sourceBadge, table, viewHeader } from '../lib/dom.js';
import { filterByText } from '../lib/format.js';
import { headerDetails, modsList, playersTable, pollAnalysis, saveBanner, saveError, saveSelect } from './save-ui.js';
import { loadCountries, tagChip } from './shared.js';

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
  const open = (tag, view) => { ctx.setState({ selectedCountry: tag }); ctx.navigate(view); };

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
      { key: 'actions', label: '', cls: 'actions', render: (r) => h('div', { class: 'btn-row' },
        h('button', { class: 'btn btn-small', onClick: (e) => { e.stopPropagation(); open(r.tag, 'country-editor'); } }, 'Edit'),
        h('button', { class: 'btn btn-small btn-ghost', onClick: (e) => { e.stopPropagation(); open(r.tag, 'focus'); } }, 'Focus')) },
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

export default {
  id: 'countries',
  title: 'Countries & Players',
  short: 'CP',
  async render(root, ctx) {
    const res = await loadCountries(ctx);
    const players = savePlayersCard(ctx);
    await players.start();
    root.append(
      viewHeader('Countries & Players', 'Pick any country to inspect - independent of the country you control.'),
      players.el,
      countriesCard(ctx, res),
    );
    return players.stop;
  },
};
