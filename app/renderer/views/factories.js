// Country Editor: factories like the game's factory tooltip - military, naval dockyards, civilian: the number in use
// and where it comes from (owned, occupation, subject relations, trade, damaged) - plus energy (game memory).
import { h, notice } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';

const KINDS = [['military', 'Military Factories'], ['dockyards', 'Naval Dockyards'], ['civilian', 'Civilian Factories']];
const PARTS = [['owned', 'Owned'], ['occupation', 'From occupation'], ['subjects', 'Subject Relations'],
  ['trade', 'From trade'], ['damaged', 'Damaged']];

/** Lines of one factory type as the game lists them: [label, signed value] - owned always, the rest when not 0;
 *  damaged as a negative number. */
export function factoryLines(f) {
  return PARTS.filter(([k]) => k === 'owned' || f[k]).map(([k, label]) => [label, k === 'damaged' ? -f[k] : f[k], k]);
}

/** "4091.6 (97.1%)" - energy demand and how much of it is covered. */
export function energyText(e) {
  return `${e.demand.toFixed(1)} (${(Math.round(e.coverage * 1000) / 10).toFixed(1)}%)`;
}

const signed = (v, k) => (k === 'owned' ? String(v) : `${v > 0 ? '+' : ''}${v}`);

function kindBox(d, kind, label) {
  const f = d[kind];
  return h('div', { class: 'fac-kind' },
    h('div', { class: 'fac-head' },
      d.icons?.[kind] ? h('img', { class: 'fac-icon', src: d.icons[kind], alt: '' }) : null,
      h('span', { class: 'fac-label' }, label),
      h('span', { class: 'fac-total', title: `${label} in use` }, `${f.total}/${f.total}`)),
    h('div', { class: 'fac-lines' }, factoryLines(f).map(([name, v, k]) => h('div', { class: 'hoi-line' },
      h('span', null, name),
      h('span', { class: `hoi-num ${k === 'owned' ? '' : v > 0 ? 'hoi-pos' : 'hoi-neg'}` }, signed(v, k))))));
}

function energyBox(e) {
  const short = e.coal_needed - e.coal_used;
  return h('div', { class: 'fac-kind fac-energy' },
    h('div', { class: 'fac-head' }, h('span', { class: 'fac-label' }, '⚡ Energy')),
    h('div', { class: 'fac-lines' },
      h('div', { class: 'hoi-line' }, h('span', null, 'Energy Demand'),
        h('span', { class: `hoi-num ${e.coverage < 1 ? 'hoi-neg' : ''}` }, energyText(e))),
      h('div', { class: 'hoi-line' }, h('span', null, 'Energy Generated'), h('span', { class: 'hoi-num' }, e.generated.toFixed(1))),
      h('div', { class: 'hoi-line' }, h('span', null, 'Coal currently used'), h('span', { class: 'hoi-num' }, Math.round(e.coal_used))),
      short > 0.05 ? h('div', { class: 'hoi-line' }, h('span', null, 'Coal still needed'),
        h('span', { class: 'hoi-num hoi-neg' }, short.toFixed(1))) : null));
}

/** Factories tile (refreshable). Returns { el, refresh, stop }. */
export function factoriesPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Factories', url: `/api/countries/${encodeURIComponent(tag)}/factories`,
    liveParts: (res) => (res.data?.factories_source === 'live' ? ['factories, energy'] : []),
    render(body, res) {
      const d = res.data;
      if (!d?.military) {
        body.replaceChildren(notice('warn', `Factories unavailable: ${res.note}`));
        return;
      }
      body.replaceChildren(h('div', { class: 'fac-grid' }, ...KINDS.map(([k, label]) => kindBox(d, k, label)), energyBox(d.energy)));
    },
  });
}
