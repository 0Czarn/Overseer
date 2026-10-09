import { h, card, demoBanner, meter, notice, sourceBadge, table, viewHeader } from '../lib/dom.js';
import { formatValue, humanize, stockBalance } from '../lib/format.js';
import { countryPicker } from './shared.js';

export default {
  id: 'equipment',
  title: 'Equipment Manager',
  short: 'EQ',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const [res, picker] = await Promise.all([
      ctx.api.get(`/api/equipment/${encodeURIComponent(tag)}`), countryPicker(ctx)]);
    const editable = res.data.editable;

    root.append(
      viewHeader('Equipment Manager', 'Stockpiles and variants of the selected country.',
        picker, sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : null,
      editable ? null : notice('info', 'Adding or removing equipment stays disabled until a safe method has been '
        + 'implemented and tested.'),
      card('Stockpile', table([
        { key: 'type', label: 'Type', render: (r) => humanize(r.type) },
        { key: 'variant', label: 'Variant' },
        { key: 'stockpile', label: 'Stockpile', cls: 'num', render: (r) => formatValue(r.stockpile, 'integer') },
        { key: 'required', label: 'Required', cls: 'num', render: (r) => formatValue(r.required, 'integer') },
        { key: 'balance', label: 'Balance', render: (r) => {
          const { ratio, delta } = stockBalance(r.stockpile, r.required);
          return h('div', { class: 'balance' }, meter(ratio, delta < 0 ? 'meter-bad' : 'meter-good'),
            h('span', { class: delta < 0 ? 'bad-text' : 'good-text' },
              `${delta >= 0 ? '+' : ''}${formatValue(delta, 'integer')}`));
        } },
        { key: 'actions', label: '', cls: 'actions', render: () => h('div', { class: 'btn-row' },
          h('button', { class: 'btn btn-small', disabled: !editable, 'aria-label': 'Remove' }, '−'),
          h('button', { class: 'btn btn-small', disabled: !editable, 'aria-label': 'Add' }, '+')) },
      ], res.data.items, { keyField: 'variant', empty: `No equipment data for ${tag}` })),
    );
  },
};
