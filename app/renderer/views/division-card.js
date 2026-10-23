// One division of a recorded campaign (2026-10-23, user's request: "hover shows the division names, a click on a
// division a graphic / text preview and its stats, and a way to a Time machine"): GET /api/summary/games/<id>/division/
// <division id> - its recorded history (ic_history "divs": n name, p position, s stats, e equipment), its template over
// time ("tmpl"), what the template's sub-units need (game files) and the designer's stats of the template when the
// running game has it. The card shows the division at a time: organisation, strength, experience level, manpower,
// dig-in, supply, equipment against the need, and the template like the game's division designer.
import { h, notice } from '../lib/dom.js';
import { dayText } from '../lib/linechart.js';
import { numberLocale } from '../lib/options.js';
import { designerGraphic, designerText, loadTemplateIcons } from './military.js';

// NDefines.NMilitary.UNIT_EXP_LEVELS {0.1, 0.3, 0.75, 0.9}: experience / manpower needed
export const EXP_LEVELS = [[0.9, 'Elite'], [0.75, 'Veteran'], [0.3, 'Regular'], [0.1, 'Trained'], [0, 'Green']];
const VIEW_KEY = 'hoi4dbg.divisionView';
const cache = new Map();   // "<campaign>|<division>" -> Promise of the backend's data

/** The last recorded value of each kind ("n", "p", "s", "e") on or before time `t` (days); null when none yet or gone. */
export function stateAt(history, t) {
  const out = { n: null, p: null, s: null, e: null };
  for (const [time, kind, value] of history) {
    if (time > t) break;
    out[kind] = value;
  }
  return out;
}

/** The template's definition {b, s, r, g, i} in force at time `t` (else its first one). */
export function templateAt(templates, key, t) {
  const list = templates?.[key] ?? [];
  let found = list[0]?.[1] ?? null;
  for (const [time, def] of list) if (time <= t) found = def;
  return found;
}

/** {manpower, equipment: {archetype: amount}} the template's sub-units need (`units`: {sub-unit: {need, manpower}}). */
export function needOf(def, units) {
  const out = { manpower: 0, equipment: {} };
  for (const u of [...(def?.b ?? []), ...(def?.s ?? []), ...(def?.r ?? [])]) {
    const unit = units?.[u];
    if (!unit) continue;
    out.manpower += unit.manpower ?? 0;
    for (const [a, n] of Object.entries(unit.need ?? {})) out.equipment[a] = (out.equipment[a] ?? 0) + n;
  }
  return out;
}

/** {fraction, name} of the experience level (experience / manpower needed, UNIT_EXP_LEVELS). */
export function expLevel(experience, manpower) {
  const fraction = manpower > 0 ? experience / manpower : 0;
  return { fraction, name: EXP_LEVELS.find(([at]) => fraction >= at)[1] };
}

/** [{archetype, held, need}] of the equipment: held by type summed per archetype (`archetype`: {type: archetype}). */
export function equipmentRows(held, archetype, need) {
  const per = {};
  for (const [type, n] of Object.entries(held ?? {})) {
    const a = archetype?.[type] ?? type.replace(/_\d+$/, '');
    per[a] = (per[a] ?? 0) + n;
  }
  const keys = [...new Set([...Object.keys(need ?? {}), ...Object.keys(per)])];
  return keys.map((a) => ({ archetype: a, held: per[a] ?? 0, need: need?.[a] ?? 0 }))
    .sort((x, y) => y.need - x.need || x.archetype.localeCompare(y.archetype));
}

export function loadDivision(ctx, gid, id) {
  const key = `${gid}|${id}`;
  if (!cache.has(key)) {
    cache.set(key, ctx.api.get(`/api/summary/games/${encodeURIComponent(gid)}/division/${id}`).then((r) => r.data)
      .catch((err) => { cache.delete(key); throw err; }));
  }
  return cache.get(key);
}

/** Forget what was read (the campaign was recorded further). */
export function dropDivisions() {
  cache.clear();
}

function bar(label, value, max, text, cls = '') {
  const pct = max > 0 ? Math.max(0, Math.min(100, (100 * value) / max)) : null;
  return h('div', { class: `dc-bar ${cls}`.trim() },
    h('div', { class: 'dc-bar-head' }, h('span', null, label), h('span', { class: 'hoi-num' }, text)),
    pct != null ? h('div', { class: 'dc-bar-track' }, h('div', { class: 'dc-bar-fill', style: { width: `${pct}%` } })) : null);
}

/**
 * The card of division `id` of campaign `gid` at time `t` (days). Options: onOpen() - the "Open in the Time machine"
 * button; place(pid) -> name of the province's state.
 */
export function divisionCard(ctx, gid, id, t, { onOpen, place } = {}) {
  const el = h('div', { class: 'dc' }, h('p', { class: 'muted' }, 'Loading the division…'));
  let view = 'graphic';
  try { view = localStorage.getItem(VIEW_KEY) === 'text' ? 'text' : 'graphic'; } catch { /* preference only */ }
  loadDivision(ctx, gid, id).then((data) => {
    const draw = () => el.replaceChildren(...content(data).filter(Boolean));
    const content = (d) => {
      const now = stateAt(d.history, t);
      if (!now.n) return [notice('info', 'This division did not exist at this time.')];
      const [tag, name, template, army, leader] = now.n;
      const key = `${tag}|${template}`;
      const def = templateAt(d.templates, key, t);
      const need = needOf(def, d.units);
      const designer = d.designer?.[key] ?? null;
      const stats = designer?.stats ?? {};
      const [org, strength, experience, manpower, digIn, supply] = now.s ?? [];
      const level = expLevel(experience ?? 0, need.manpower || stats.manpower || manpower || 0);
      const fmt = (v, digits = 0) => (v == null ? '—' : v.toLocaleString(numberLocale(), { maximumFractionDigits: digits }));
      const labels = d.labels ?? {};
      const where = now.p ? (place?.(now.p[0]) ?? `Province ${now.p[0]}`) : '—';
      const toText = now.p?.[1] ? ` → ${place?.(now.p[1]) ?? `province ${now.p[1]}`}` : '';
      const tpl = def ? { name: template, grid: def.g, battalions: def.b ?? [], support: def.s ?? [], regimental: def.r ?? [],
        designer } : null;
      if (tpl) loadTemplateIcons(ctx, [tpl], draw);
      const setView = (v) => () => {
        view = v;
        try { localStorage.setItem(VIEW_KEY, v); } catch { /* preference only */ }
        draw();
      };
      const equipment = equipmentRows(now.e, d.archetype, need.equipment);
      const first = d.history[0]?.[0];
      const gone = d.history.findLast((x) => x[1] === 'n')?.[2] === null ? d.history.findLast((x) => x[1] === 'n')[0] : null;
      const fights = (d.battles ?? []).filter((b) => b[0] <= t);
      return [
        h('div', { class: 'dc-head' },
          h('div', null, h('strong', { class: 'dc-name' }, name ?? `Division ${id}`),
            h('div', { class: 'muted' }, `${tag} · ${template ?? '?'}`),
            h('div', null, army || leader ? `${army ?? 'Army'}${leader ? ` · ${leader}` : ''}` : h('span', { class: 'muted' }, 'In no army')),
            h('div', { class: 'muted' }, `${where}${toText}`)),
          h('span', { class: `dc-level dc-level-${level.name.toLowerCase()}`, title: `Experience ${fmt(100 * level.fraction, 1)}% of the next levels at 10 / 30 / 75 / 90%` },
            level.name)),
        now.s ? h('div', { class: 'dc-bars' },
          bar('Organisation', org, stats.max_organisation, stats.max_organisation ? `${fmt(org, 1)} / ${fmt(stats.max_organisation, 1)}` : fmt(org, 1), 'dc-org'),
          bar('Strength', strength, stats.max_strength, stats.max_strength ? `${fmt(strength, 1)} / ${fmt(stats.max_strength, 1)}` : fmt(strength, 1), 'dc-str'),
          bar('Manpower', manpower, need.manpower, need.manpower ? `${fmt(manpower)} / ${fmt(need.manpower)}` : fmt(manpower), 'dc-mp'),
          bar('Experience', level.fraction, 1, `${fmt(100 * level.fraction, 1)}%`, 'dc-exp'),
          h('div', { class: 'dc-facts' },
            h('span', null, `Dig-in ${fmt(digIn, 1)}`), h('span', null, `Supply ${supply == null ? '—' : `${supply}%`}`)))
          : notice('info', 'Its stats are read once a game day - none recorded for this time yet.'),
        equipment.length ? h('div', { class: 'dc-eq' }, h('div', { class: 'dc-title' }, 'Equipment'),
          equipment.map((r) => h('div', { class: `dc-eq-row ${r.need && r.held < r.need ? 'dc-short' : ''}`.trim() },
            h('span', null, labels[r.archetype] ?? r.archetype.replace(/_/g, ' ')),
            h('span', { class: 'hoi-num' }, r.need ? `${fmt(r.held)} / ${fmt(r.need)} (${fmt((100 * r.held) / r.need)}%)` : fmt(r.held))))) : null,
        tpl ? h('div', { class: 'dc-tpl' },
          h('div', { class: 'dc-title' }, 'Template', h('span', { class: 'mil-view' }, [['graphic', 'Graphic'], ['text', 'Text']].map(([v, label]) =>
            h('button', { class: `mil-view-btn ${view === v ? 'mil-view-on' : ''}`, 'aria-pressed': String(view === v), onclick: setView(v) }, label)))),
          view === 'graphic' ? designerGraphic(tpl, labels) : designerText(tpl),
          designer ? h('p', { class: 'muted dc-note' }, 'Designer stats: the template as the running game has it now.')
            : h('p', { class: 'muted dc-note' }, 'Designer stats only while the game runs with this template.')) : null,
        h('div', { class: 'dc-facts muted' },
          first != null ? h('span', null, `Recorded from ${dayLabel(first)}`) : null,
          gone != null ? h('span', { class: 'bad-text' }, `Gone ${dayLabel(gone)}`) : null,
          h('span', null, `${fights.length} ${fights.length === 1 ? 'battle reading' : 'battle readings'} so far`)),
        onOpen ? h('button', { class: 'btn btn-small dc-open', onclick: onOpen }, 'Open in the Time machine') : null,
      ];
    };
    draw();
  }).catch((err) => el.replaceChildren(notice('warn', `Division unavailable: ${err.message}`)));
  return el;
}

/** "1936.02.01" / "1936.02.01 12:00" of a time in days. */
export function dayLabel(t) {
  const day = Math.floor(t);
  const hour = Math.round((t - day) * 24);
  return hour ? `${dayText(day)} ${String(hour).padStart(2, '0')}:00` : dayText(day);
}
