import { h, card, demoBanner, meter, notice, sourceBadge, viewHeader } from '../lib/dom.js';
import { formatValue, humanize } from '../lib/format.js';
import { countryPicker, loadCountries } from './shared.js';

function valuesList(values, fields) {
  return h('dl', { class: 'kv' }, fields.map((f) => [h('dt', null, f.label), h('dd', null, formatValue(values[f.key], f.unit))]));
}

export default {
  id: 'intel',
  title: 'Intelligence Lab',
  short: 'IL',
  async render(root, ctx) {
    const observer = ctx.state.observerCountry;
    const target = ctx.state.selectedCountry;
    const [res, targetInfo, observerPicker, targetPicker] = await Promise.all([
      ctx.api.get(`/api/intel/${encodeURIComponent(observer)}/${encodeURIComponent(target)}`),
      ctx.api.get(`/api/countries/${encodeURIComponent(target)}`),
      countryPicker(ctx, { label: 'Observer', key: 'observerCountry' }),
      countryPicker(ctx, { label: 'Target', key: 'selectedCountry' }),
      loadCountries(ctx),
    ]);
    const intel = res.data;
    const fields = targetInfo.data.fields;

    root.append(
      viewHeader('Intelligence Lab', 'What one country can know about another, versus what the debugger sees.',
        observerPicker, targetPicker, sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : null,
      card(`Intel of ${intel.observer} on ${intel.target}`, h('div', { class: 'intel-bars' },
        Object.entries(intel.intel_levels).map(([k, v]) => h('div', { class: 'intel-bar' },
          h('span', null, humanize(k)), meter(v), h('b', null, formatValue(v, 'percent')))))),
      h('div', { class: 'split' },
        card('In-game view (observer)', [
          h('p', { class: 'hint' }, intel.visible_rule),
          intel.visible ? valuesList(intel.visible, fields)
            : notice('muted', `${intel.observer} does not have enough intel to see these values.`),
        ], { extra: h('span', { class: 'badge badge-live-alt' }, 'GAME STATE') }),
        card('Debugger preview (actual values)', [
          notice('warn', 'Visible only in this debugger. It is not information the observer has in the game.'),
          valuesList(intel.actual, fields),
        ], { extra: h('span', { class: 'badge badge-debug' }, 'DEBUGGER ONLY'), cls: 'card-debug' })),
    );
  },
};
