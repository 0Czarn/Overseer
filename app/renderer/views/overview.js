// Country Editor: who rules the country - leader, ideology, faction and party popularity pie (newest save),
// in the style of the game's politics screen.
import { h, notice } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { modifierLine } from './spirits.js';

const SVG = 'http://www.w3.org/2000/svg';

function svg(tag, attrs) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

/** SVG path of one pie slice (fractions of a turn, 0 = top, clockwise). */
export function slicePath(cx, cy, r, from, to) {
  if (to - from >= 0.9999) return `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`;
  const point = (t) => [cx + r * Math.sin(2 * Math.PI * t), cy - r * Math.cos(2 * Math.PI * t)];
  const [x1, y1] = point(from);
  const [x2, y2] = point(to);
  return `M ${cx} ${cy} L ${x1.toFixed(3)} ${y1.toFixed(3)} A ${r} ${r} 0 ${to - from > 0.5 ? 1 : 0} 1 ${x2.toFixed(3)} ${y2.toFixed(3)} Z`;
}

function partyTip(p) {
  return [h('div', { class: 'spirit-tip-name' }, `${p.name} (${+p.popularity.toFixed(1)}%)`),
    p.long_name ? h('div', { class: 'spirit-tip-kind' }, p.long_name) : null,
    h('div', null, `Ideology: ${p.ideology_name}`),
    p.ruling ? h('div', { class: 'spirit-tip-traits' }, 'Ruling party') : null].filter(Boolean);
}

function pie(parties) {
  const total = parties.reduce((s, p) => s + Math.max(0, p.popularity), 0) || 1;
  const tip = h('div', { class: 'spirit-tip pie-tip', role: 'tooltip' });
  const showAll = () => tip.replaceChildren(h('div', { class: 'spirit-tip-name' }, 'Party popularity'),
    ...parties.map((p) => h('div', { class: 'hoi-line' },
      h('span', null, h('i', { class: 'swatch', style: { background: p.color } }),
        ` ${p.name} - ${p.ideology_name}${p.ruling ? ' (ruling)' : ''}`),
      h('span', { class: 'hoi-num' }, `${+p.popularity.toFixed(2)}%`))));
  const chart = svg('svg', { viewBox: '0 0 100 100', class: 'pie', role: 'img', 'aria-label': 'Party popularity' });
  chart.append(svg('circle', { cx: 50, cy: 50, r: 48, class: 'pie-ring' }));
  let at = 0;
  for (const p of parties) {
    const share = Math.max(0, p.popularity) / total;
    if (share <= 0) continue;
    const slice = svg('path', { d: slicePath(50, 50, 44, at, at + share), fill: p.color,
      class: `pie-slice${p.ruling ? ' pie-ruling' : ''}` });
    slice.addEventListener('mouseenter', () => tip.replaceChildren(...partyTip(p)));
    slice.addEventListener('mouseleave', showAll);
    chart.append(slice);
    at += share;
  }
  chart.append(svg('circle', { cx: 50, cy: 50, r: 44, class: 'pie-gloss' }));
  showAll();
  const legend = h('div', { class: 'pie-legend' }, parties.map((p) => h('div', {
    class: `pie-row${p.ruling ? ' pie-row-ruling' : ''}`, title: p.long_name ?? '' },
  h('i', { class: 'swatch', style: { background: p.color } }), h('span', null, `${p.name} (${Math.round(p.popularity)})`))));
  return h('div', { class: 'pie-block' }, h('div', { class: 'pie-wrap', tabindex: 0 }, chart, tip), legend);
}

function leaderBlock(l, ruling) {
  return h('div', { class: 'ov-leader spirit', tabindex: 0 },
    l.portrait ? h('img', { class: 'ov-portrait', src: l.portrait, alt: '' }) : h('div', { class: 'ov-portrait spirit-noicon' }, '?'),
    h('div', { class: 'spirit-tip', role: 'tooltip' }, h('div', { class: 'spirit-tip-name' }, l.name),
      h('div', { class: 'spirit-tip-kind' }, `Country leader · ${l.ideology_name ?? l.ideology ?? ''}`),
      l.traits.length ? l.traits.map((t) => h('div', { class: 'spirit-tip-mods' }, h('div', { class: 'spirit-tip-traits' }, t.name),
        t.modifiers.map(modifierLine)))
        : h('div', { class: 'muted' }, 'No leader traits'),
      ruling?.long_name ? h('div', { class: 'spirit-tip-desc' }, ruling.long_name) : null));
}

function factionBlock(f) {
  if (!f) return h('div', { class: 'ov-faction ov-faction-none' }, h('span', { class: 'muted' }, 'Not in a faction'));
  return h('div', { class: 'ov-faction spirit', tabindex: 0 },
    f.icon ? h('img', { class: 'ov-faction-icon', src: f.icon, alt: '' }) : null,
    h('span', { class: 'ov-faction-name' }, f.name),
    h('div', { class: 'spirit-tip', role: 'tooltip' }, h('div', { class: 'spirit-tip-name' }, f.name),
      h('div', null, `Leader: ${f.leader ?? '—'}`), h('div', null, `Members: ${f.members.join(', ')}`)));
}

/** Leadership tile (refreshable; party popularity and ruling party live from game memory when possible). */
export function overviewPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Leadership', url: `/api/countries/${encodeURIComponent(tag)}/overview`,
    liveParts: (res) => (res.data?.parties_source === 'live' ? ['parties, leader, faction'] : []),
    render(body, res) {
      const d = res.data;
      if (!d?.parties) {
        body.replaceChildren(notice('warn', `Leadership unavailable: ${res.note}`));
        return;
      }
      const ruling = d.parties.find((p) => p.ruling);
      body.replaceChildren(h('div', { class: 'ov-body' }, ...[
        d.leader ? leaderBlock(d.leader, ruling) : null,
        h('div', { class: 'ov-info' },
          h('div', { class: 'ov-leader-name' }, d.leader?.name ?? 'Unknown leader'),
          h('div', { class: 'ov-line' }, h('span', { class: 'muted' }, 'Ruling party '), h('b', null, ruling?.name ?? '—'),
            ruling?.long_name ? h('span', { class: 'muted' }, ` · ${ruling.long_name}`) : null),
          h('div', { class: 'ov-line' }, h('span', { class: 'muted' }, 'Ideology '),
            h('i', { class: 'swatch', style: { background: ruling?.color ?? '#777' } }),
            h('b', null, ` ${ruling?.ideology_name ?? '—'}`),
            d.leader?.ideology_name ? h('span', null, ` (${d.leader.ideology_name})`) : null),
          factionBlock(d.faction)),
        pie(d.parties)].filter(Boolean)));
    },
  });
}
