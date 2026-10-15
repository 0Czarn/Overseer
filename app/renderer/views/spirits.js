// National spirits of the selected country (newest save): HOI4-like icon row; modifiers show on hover / focus.
import { h, notice } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { modifierIcon } from '../lib/icons.js';
import { numberLocale } from '../lib/options.js';

// Modifiers where a higher value is worse for the country (shown red when positive), as in the game's tooltips.
const BAD_WHEN_HIGH = /cost|penalty|accident|consumption|losses|attrition|requirement|need|to_others|weekly_casualties|enemy_|weight/;

export function formatModifier(key, value) {
  const percent = key.endsWith('_factor') || (!Number.isInteger(value) && Math.abs(value) < 5);
  const shown = percent ? `${+(value * 100).toFixed(2)}%` : `${+value.toFixed(2)}`;
  return `${value > 0 ? '+' : ''}${shown}`;
}

/** One modifier as the game lists it: icon (Descriptive Icons), name, coloured value. */
export function modifierLine(m) {
  return h('div', { class: 'hoi-line' }, h('span', { class: 'hoi-mod' }, modifierIcon(m.key), m.label),
    h('span', { class: `hoi-num ${modifierClass(m.key, m.value)}` }, formatModifier(m.key, m.value)));
}

export function modifierClass(key, value) {
  if (!value) return '';
  return (value > 0) !== BAD_WHEN_HIGH.test(key) ? 'hoi-pos' : 'hoi-neg';
}

/** Icon with a HOI4-like tooltip (name, traits, modifiers, description) on hover / keyboard focus.
 *  `item` from the backend (_present); kind "empty" = free slot. */
export function iconTile(item, { round = false } = {}) {
  if (item.kind === 'empty') {
    return h('div', { class: 'spirit spirit-empty-slot', tabindex: 0, 'aria-label': `Empty: ${item.slot_label}` },
      h('div', { class: 'spirit-icon spirit-slot' }, h('span', { class: 'spirit-plus' }, '+')),
      h('div', { class: 'spirit-tip', role: 'tooltip' },
        h('div', { class: 'spirit-tip-name' }, item.slot_label), h('div', { class: 'muted' }, 'Empty slot')));
  }
  const iconCls = `spirit-icon${round ? ' spirit-round' : ''}`;
  return h('div', { class: 'spirit', tabindex: 0, 'aria-label': item.name },
    item.icon ? h('img', { class: iconCls, src: item.icon, alt: '' }) : h('div', { class: `${iconCls} spirit-noicon` }, '?'),
    h('div', { class: 'spirit-tip', role: 'tooltip' },
      h('div', { class: 'spirit-tip-name' }, item.name),
      item.slot_label ? h('div', { class: 'spirit-tip-kind' }, item.slot_label) : null,
      item.traits?.length ? h('div', { class: 'spirit-tip-traits' }, item.traits.join(' · ')) : null,
      item.modifiers.length || item.tooltips.length
        ? h('div', { class: 'spirit-tip-mods' },
          item.modifiers.map(modifierLine),
          item.tooltips.map((t) => h('div', { class: 'spirit-tip-custom' }, t)))
        : h('div', { class: 'muted' }, 'No direct modifiers'),
      item.description ? h('div', { class: 'spirit-tip-desc' }, item.description) : null,
      item.kind === 'dynamic' ? h('div', { class: 'spirit-tip-kind' }, 'Dynamic modifier (values from the save)') : null));
}

/** National spirits tile (refreshable). Returns { el, refresh, stop }. */
export function spiritsPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'National spirits', url: `/api/countries/${encodeURIComponent(tag)}/spirits`,
    liveParts: (res) => (res.data?.ideas_source === 'live' ? ['spirits'] : []),
    render(body, res) {
      const list = res.data?.spirits;
      body.replaceChildren(h('div', { class: 'spirit-row' }, ...(!list ? [notice('warn', `National spirits unavailable: ${res.note}`)]
        : list.length ? list.map((x) => iconTile(x)) : [h('span', { class: 'muted' }, 'No national spirits')])));
    },
  });
}

const pctText = (v) => `${v > 0 ? '+' : ''}${+(v * 100).toFixed(2)}%`;
const MIO_SLOTS = new Set(['tank_manufacturer', 'naval_manufacturer', 'aircraft_manufacturer', 'materiel_manufacturer']);

/** One MIO with its level badge; tooltip: level, funds, policy, traits and the bonuses they give now. */
export function mioTile(m) {
  return h('div', { class: 'spirit mio', tabindex: 0, 'aria-label': `${m.name}, level ${m.size}` },
    m.icon ? h('img', { class: 'spirit-icon', src: m.icon, alt: '' }) : h('div', { class: 'spirit-icon spirit-noicon' }, '?'),
    h('span', { class: 'mio-level' }, String(m.size ?? 0)),
    h('div', { class: 'spirit-tip', role: 'tooltip' },
      h('div', { class: 'spirit-tip-name' }, m.name),
      h('div', { class: 'spirit-tip-kind' }, `Level ${m.size ?? 0}`
        + (Number.isFinite(m.funds) ? ` · funds ${Math.round(m.funds).toLocaleString(numberLocale())}` : '')
        + (Number.isFinite(m.research_bonus) ? ` · research bonus ${pctText(m.research_bonus)}` : '')),
      m.policy ? h('div', { class: 'spirit-tip-traits' }, `Policy: ${m.policy}`) : null,
      m.bonuses.length
        ? m.bonuses.map((g) => h('div', { class: 'spirit-tip-mods' }, h('div', { class: 'mio-group' }, g.group),
          g.entries.map((e) => h('div', { class: 'hoi-line' }, h('span', null, e.label),
            h('span', { class: `hoi-num ${modifierClass(e.key, e.value)}` }, pctText(e.value))))))
        : h('div', { class: 'muted' }, 'No bonuses yet'),
      h('div', { class: 'spirit-tip-desc' }, [
        m.initial_trait ? `Initial trait: ${m.initial_trait}` : null,
        m.traits.length ? `Unlocked traits (${m.traits.length}): ${m.traits.join(', ')}` : 'No traits unlocked yet',
      ].filter(Boolean).join('\n'))));
}

/** Design slot tile that opens the list of the country's MIOs of that kind. */
function mioSlotTile(item, mios, onToggle) {
  const best = mios[0];
  return h('div', { class: 'spirit mio-slot', tabindex: 0, role: 'button', 'aria-expanded': 'false',
    'aria-label': `${item.slot_label}: ${mios.length} organisations`,
    onClick: (e) => onToggle(e.currentTarget), onKeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(e.currentTarget); } } },
  best.icon ? h('img', { class: 'spirit-icon spirit-round', src: best.icon, alt: '' })
    : h('div', { class: 'spirit-icon spirit-round spirit-noicon' }, '?'),
  h('span', { class: 'mio-count' }, String(mios.length)),
  h('div', { class: 'spirit-tip', role: 'tooltip' }, h('div', { class: 'spirit-tip-name' }, item.slot_label),
    h('div', { class: 'muted' }, `${mios.length} military industrial organisations - click to show`)));
}

// Section icons of the game's politics screen, drawn as simple shapes (no game art needed).
const SECTION_ICONS = {
  laws: 'M3 20h18v2H3zM5 9h2v9H5zm4 0h2v9H9zm4 0h2v9h-2zm4 0h2v9h-2zM2 7l10-5 10 5v1H2z',
  research: 'M9 2h2l.4 2.2 1.6.7 1.9-1.3 1.4 1.4-1.3 1.9.7 1.6L18 9v2l-2.2.4-.7 1.6 1.3 1.9-1.4 1.4-1.9-1.3-1.6.7L11 18H9l-.4-2.2-1.6-.7-1.9 1.3-1.4-1.4 1.3-1.9-.7-1.6L2 11V9l2.2-.4.7-1.6-1.3-1.9 1.4-1.4 1.9 1.3 1.6-.7zm1 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  military: 'M12 3C7 3 4 7 4 12v2h16v-2c0-5-3-9-8-9zM2 15h20v2H2z',
};
const SECTIONS = [['laws', 'Laws & Government'], ['research', 'Research & Production'], ['military', 'Military Staff']];

function sectionIcon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'gov-icon');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', SECTION_ICONS[name]);
  svg.append(path);
  return svg;
}

/** Laws & Government, Research & Production, Military Staff (refreshable), like the game's politics screen. */
export function governmentPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Government & staff', cls: 'gov-panel', url: `/api/countries/${encodeURIComponent(tag)}/government`,
    liveParts: (res) => [res.data?.ideas_source === 'live' && 'laws, companies',
      res.data?.advisors_source === 'live' && 'advisors, staff'].filter(Boolean),
    unavailable: 'Government & staff',
    render(body, res) {
      if (!res.data?.laws) {
        body.replaceChildren(notice('warn', `Unavailable: ${res.note}`));
        return;
      }
      const rows = Object.fromEntries(SECTIONS.map(([id]) => [id, h('div', { class: 'spirit-row gov-row' })]));
      const mioList = h('div', { class: 'mio-list', hidden: true });
      let openSlot = null;
      const toggle = (slot, tile) => {
        const same = openSlot === slot;
        rows.research.querySelectorAll('.mio-slot').forEach((t) => t.setAttribute('aria-expanded', 'false'));
        openSlot = same ? null : slot;
        mioList.hidden = same;
        if (!same) {
          tile.setAttribute('aria-expanded', 'true');
          mioList.replaceChildren(h('div', { class: 'mio-list-title' }, tile.getAttribute('aria-label')),
            h('div', { class: 'spirit-row' }, res.data.mios[slot].map(mioTile)));
        }
      };
      for (const [id] of SECTIONS) {
        rows[id].replaceChildren(...res.data[id].map((item) => {
          const mios = MIO_SLOTS.has(item.slot) && item.kind === 'empty' ? res.data.mios?.[item.slot] ?? [] : [];
          return mios.length ? mioSlotTile(item, mios, (tile) => toggle(item.slot, tile))
            : iconTile(item, { round: item.kind === 'law' || item.kind === 'company' });
        }));
      }
      body.replaceChildren(...SECTIONS.map(([id, title]) => h('div', { class: 'gov-section' },
        h('div', { class: 'gov-bar' }, sectionIcon(id), h('span', null, title)), rows[id],
        id === 'research' ? mioList : null)));
    },
  });
}
