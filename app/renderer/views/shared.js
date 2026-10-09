// Helpers shared by several views.
import { h, select } from '../lib/dom.js';

let countriesCache = null;

export async function loadCountries(ctx) {
  if (!countriesCache) countriesCache = await ctx.api.get('/api/countries');
  return countriesCache;
}

/** Country selector bound to the app-wide "selected country" (independent of the player's own country). */
export async function countryPicker(ctx, { label = 'Country', key = 'selectedCountry', onChange } = {}) {
  const { data } = await loadCountries(ctx);
  const value = ctx.state[key];
  return h('label', { class: 'field-inline' }, h('span', null, label),
    select(data.map((c) => ({ value: c.tag, label: `${c.tag} - ${c.name}` })), value, (tag) => {
      if (onChange) onChange(tag);
      else ctx.setState({ [key]: tag });
    }, { class: 'input' }));
}

export function tagChip(tag, extraCls = '') {
  return h('span', { class: `tag-chip ${extraCls}`.trim() }, tag);
}
