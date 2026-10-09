import { h, card, demoBanner, keyValues, notice, select, sourceBadge, table, viewHeader } from '../lib/dom.js';
import { filterByText, humanize } from '../lib/format.js';
import { loadCountries, tagChip } from './shared.js';

function chips(tags) {
  return tags?.length ? h('span', { class: 'chip-row' }, tags.map((t) => tagChip(t))) : h('span', { class: 'muted' }, '—');
}

function amounts(obj) {
  const entries = Object.entries(obj ?? {});
  if (!entries.length) return h('span', { class: 'muted' }, 'None');
  return h('ul', { class: 'amounts' }, entries.map(([k, v]) => h('li', null, h('span', null, humanize(k)), h('b', null, v))));
}

function detail(state) {
  if (!state) return notice('muted', 'Select a state to see details.');
  const occupied = state.owner !== state.controller;
  return [
    h('h3', null, state.name, ' ', h('code', { class: 'muted' }, state.id)),
    keyValues([
      ['Owner', tagChip(state.owner)],
      ['Controller', [tagChip(state.controller, occupied ? 'tag-chip-warn' : ''),
        occupied ? h('span', { class: 'warn-text' }, ' controlled by another country') : null]],
      ['Cores', chips(state.cores)],
      ['Claims', chips(state.claims)],
    ]),
    h('div', { class: 'two-col' },
      h('div', null, h('h4', null, 'Buildings'), amounts(state.buildings)),
      h('div', null, h('h4', null, 'Resources'), amounts(state.resources))),
    h('p', { class: 'hint' }, 'Modded buildings and resources will be listed here once live reading '
      + 'confirms how they appear in the game data.'),
  ];
}

export default {
  id: 'state-editor',
  title: 'State Editor',
  short: 'SE',
  async render(root, ctx) {
    const [res, countries] = await Promise.all([ctx.api.get('/api/states'), loadCountries(ctx)]);
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
      ], rows, { selectedKey: selected, onRowClick: (s) => { selected = s.id; rerender(); }, empty: 'No states match' }));
      detailHost.replaceChildren(...[detail(res.data.find((s) => s.id === selected))].flat());
    };
    rerender();

    root.append(
      viewHeader('State Editor', 'Owner vs controller, buildings, resources, cores and claims.',
        sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : null,
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
  },
};
