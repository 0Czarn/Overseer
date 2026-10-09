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

function demoCountriesCard(ctx, res) {
  let filter = '';
  const listHost = h('div');
  const selectedLabel = h('span', { class: 'muted' });
  const open = (tag, view) => { ctx.setState({ selectedCountry: tag }); ctx.navigate(view); };

  const renderList = () => {
    selectedLabel.textContent = `Selected: ${ctx.state.selectedCountry}`;
    const rows = filterByText(res.data, filter, ['tag', 'name', 'player']);
    listHost.replaceChildren(table([
      { key: 'tag', label: 'Tag', render: (r) => tagChip(r.tag) },
      { key: 'name', label: 'Name' },
      { key: 'player', label: 'Player (DEMO)', render: (r) => r.player ?? h('span', { class: 'muted' }, 'AI') },
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
    res.source === 'demo' ? demoBanner(`${res.note} The full country list is not read from saves yet.`) : null,
    h('input', { class: 'input', type: 'search', placeholder: 'Filter by tag, name or player…',
      onInput: (e) => { filter = e.target.value; renderList(); } }),
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
      demoCountriesCard(ctx, res),
    );
    return players.stop;
  },
};
