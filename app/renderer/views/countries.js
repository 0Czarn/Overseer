import { h, card, demoBanner, sourceBadge, table, viewHeader } from '../lib/dom.js';
import { filterByText } from '../lib/format.js';
import { loadCountries, tagChip } from './shared.js';

export default {
  id: 'countries',
  title: 'Countries & Players',
  short: 'CP',
  async render(root, ctx) {
    const res = await loadCountries(ctx);
    let filter = '';
    const listHost = h('div');
    const selectedLabel = h('span', { class: 'muted' });

    const renderList = () => {
      selectedLabel.textContent = `Selected: ${ctx.state.selectedCountry}`;
      const rows = filterByText(res.data, filter, ['tag', 'name', 'player']);
      listHost.replaceChildren(table([
        { key: 'tag', label: 'Tag', render: (r) => tagChip(r.tag) },
        { key: 'name', label: 'Name' },
        { key: 'player', label: 'Player', render: (r) => r.player ?? h('span', { class: 'muted' }, 'AI') },
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
    const open = (tag, view) => { ctx.setState({ selectedCountry: tag }); ctx.navigate(view); };

    renderList();
    root.append(
      viewHeader('Countries & Players', 'Pick any country to inspect - independent of the country you control.',
        sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : null,
      card('Countries', [
        h('input', { class: 'input', type: 'search', placeholder: 'Filter by tag, name or player…',
          onInput: (e) => { filter = e.target.value; renderList(); } }),
        listHost,
      ], { extra: selectedLabel }),
      card('Player detection', h('p', { class: 'hint' },
        'Player-to-country assignment will only be shown when it can be read reliably from the game. '
        + 'Until then the "Player" column is DEMO data.')),
    );
  },
};
