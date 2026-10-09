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

const fmtInt = (v) => (v === null || v === undefined ? '—' : Math.round(v).toLocaleString());

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
      h('div', null, h('h4', null, 'State buildings'), amounts(state.buildings)),
      h('div', null, h('h4', null, 'Resources'), amounts(state.resources))),
    state.province_buildings ? h('div', null, h('h4', null, 'Province buildings (sum of levels)'), amounts(state.province_buildings)) : null,
    h('p', { class: 'hint' }, 'Buildings and resources are listed by the names the save uses, including ones added by mods. '
      + 'Names shown as #xxxx are binary-save codes not mapped yet.'),
  ].filter(Boolean);
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
      ], rows.slice(0, 400), { selectedKey: selected, onRowClick: (s) => { selected = s.id; rerender(); }, empty: 'No states match' }),
      ...(rows.length > 400 ? [h('p', { class: 'hint' }, `Showing 400 of ${rows.length} states - use the filter or the country selector.`)] : []));
      detailHost.replaceChildren(...[detail(res.data.find((s) => s.id === selected))].flat());
    };
    rerender();

    root.append(
      viewHeader('State Editor', 'Owner vs controller, buildings, resources, cores and claims.',
        sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : h('p', { class: 'hint' }, res.note),
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
