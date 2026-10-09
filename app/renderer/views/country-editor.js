import { h, card, demoBanner, notice, scopeBadge, sourceBadge, viewHeader } from '../lib/dom.js';
import { formatValue } from '../lib/format.js';
import { countryPicker, tagChip } from './shared.js';

function fieldTile(field, value, editable) {
  return h('div', { class: 'stat-tile' },
    h('div', { class: 'stat-label' }, field.label),
    h('div', { class: 'stat-value' }, formatValue(value, field.unit)),
    h('div', { class: 'stat-edit' },
      h('input', { class: 'input input-small', type: 'number', disabled: !editable, placeholder: 'New value',
        'aria-label': `New ${field.label}` }),
      h('button', { class: 'btn btn-small', disabled: !editable, title: editable ? '' : 'Editing not available yet' },
        'Apply')));
}

export default {
  id: 'country-editor',
  title: 'Country Editor',
  short: 'CE',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const [res, picker] = await Promise.all([
      ctx.api.get(`/api/countries/${encodeURIComponent(tag)}`),
      countryPicker(ctx),
    ]);
    const country = res.data;

    root.append(
      viewHeader('Country Editor', 'Political, military and logistic values of the selected country.',
        picker, sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : null,
      notice('info', [
        'Changing these values alters the ', scopeBadge('shared'),
        ' of the game. Editing stays disabled until a write method is implemented and verified '
        + '(singleplayer first, multiplayer only after a two-client sync test).',
      ]),
      card(null, h('div', { class: 'country-head' }, tagChip(country.tag, 'tag-chip-lg'),
        h('div', null, h('h2', null, country.name),
          h('p', { class: 'muted' }, country.player ? `Player: ${country.player}` : 'AI-controlled')))),
      h('div', { class: 'tile-grid' }, country.fields.map((f) => fieldTile(f, country.values[f.key], country.editable))),
    );
  },
};
