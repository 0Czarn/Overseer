import { h, card, sourceBadge, viewHeader } from '../lib/dom.js';
import { countryLivePanel } from './country-live.js';
import { governmentPanel, spiritsPanel } from './spirits.js';
import { overviewPanel } from './overview.js';
import { resourcesPanel } from './resources.js';
import { factoriesPanel } from './factories.js';
import { countryPicker, tagChip } from './shared.js';

export default {
  id: 'country-editor',
  title: 'Country Editor',
  short: 'CE',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const [meta, saved, picker, liveStatus] = await Promise.all([
      ctx.api.get(`/api/countries/${encodeURIComponent(tag)}`),
      ctx.api.get(`/api/countries/${encodeURIComponent(tag)}/save-values`),
      countryPicker(ctx),
      ctx.api.get('/api/live').catch(() => null),
    ]);
    // Human player(s) read from game memory; the save's player is only a fallback (it may be stale).
    const livePlayers = liveStatus?.players ?? [];
    const isPlayer = livePlayers.length ? livePlayers.includes(tag) : fromSaveIsPlayer();
    function fromSaveIsPlayer() { return saved.source === 'save' && saved.data.player_tag === tag; }
    const fromSave = saved.source === 'save';

    root.append(
      viewHeader('Country Editor', 'Political, military and logistic values of the selected country.',
        picker, sourceBadge(fromSave ? 'save' : meta.source, fromSave ? saved.note : meta.note)),
      card(null, h('div', { class: 'country-head' }, tagChip(tag, 'tag-chip-lg'),
        h('div', null, h('h2', null, meta.data.name), h('p', { class: 'muted' }, [
          livePlayers.includes(tag) ? 'Player country (live)'
            : !livePlayers.length && fromSave && saved.data.player_tag === tag ? 'Player country in this save'
            : meta.data.player ? `Played by ${meta.data.player}` : 'AI country',
          meta.data.ruling_party ? ` · ruling party: ${meta.data.ruling_party}` : '',
          meta.data.exists === false ? ' · does not exist in the newest save' : ''].join(''))))),
    );
    // Live values for any country (game country table); verified console changes only for the player country.
    const live = countryLivePanel(ctx, tag, { isPlayer });
    const tiles = [overviewPanel(ctx, tag), spiritsPanel(ctx, tag)];
    const lower = [factoriesPanel(ctx, tag), resourcesPanel(ctx, tag), governmentPanel(ctx, tag)];
    root.append(...tiles.map((t) => t.el), live.el, ...lower.map((t) => t.el));
    return () => { live?.stop(); [...tiles, ...lower].forEach((t) => t.stop()); };
  },
};
