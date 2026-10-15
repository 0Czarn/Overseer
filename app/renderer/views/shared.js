// Helpers shared by several views.
import { h, select } from '../lib/dom.js';
import { loadOptions } from '../lib/options.js';

let countriesCache = null;

export async function loadCountries(ctx) {
  if (!countriesCache) countriesCache = await ctx.api.get('/api/countries');
  return countriesCache;
}

/** Country selector bound to the app-wide "selected country" (independent of the player's own country). */
/** Countries with the favourite one (Options) first. */
export function pinFavourite(countries, fav) {
  const i = fav ? countries.findIndex((c) => c.tag === fav) : -1;
  return i < 0 ? countries : [countries[i], ...countries.slice(0, i), ...countries.slice(i + 1)];
}

export async function countryPicker(ctx, { label = 'Country', key = 'selectedCountry', onChange } = {}) {
  const { data } = await loadCountries(ctx);
  const value = ctx.state[key];
  return h('label', { class: 'field-inline' }, h('span', null, label),
    // Existing countries first (when known from a save); the current selection stays selectable.
    select(pinFavourite(data.filter((c) => c.exists !== false || c.tag === value), loadOptions().favCountry)
      .map((c) => ({ value: c.tag, label: `${c.tag === loadOptions().favCountry ? '★ ' : ''}${c.tag} - ${c.name}` })), value, (tag) => {
      if (onChange) onChange(tag);
      else ctx.setState({ [key]: tag });
    }, { class: 'input' }));
}

export function tagChip(tag, extraCls = '') {
  return h('span', { class: `tag-chip ${extraCls}`.trim() }, tag);
}
