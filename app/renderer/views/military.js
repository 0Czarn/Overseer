// Army / Air / Navy tiles: what the selected country has in the field, like the game's military overview -
// divisions per template with their composition and stats like the division designer, free manpower, manpower in
// the field and in training; planes per role and design with the
// design stats and planes in the stockpile; fleets, task forces and ships per type and class (game memory).
import { designerIcon } from '../lib/icons.js';
import { h, notice } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';

const url = (tag) => `/api/countries/${encodeURIComponent(tag)}/military`;
const liveParts = (res) => (res.data?.military_source === 'live' ? ['army, air force, navy'] : []);

/** "4.35M" / "38.2K" / "950" - a count the way the game's top bar shortens it. */
export function shortCount(n) {
  if (n == null) return '—';
  if (n >= 1e6) return `${(Math.floor(n / 1e4) / 100).toFixed(2)}M`;
  if (n >= 1e4) return `${(Math.floor(n / 100) / 10).toFixed(1)}K`;
  return String(Math.round(n));
}

/** "461.56K" / "4.64M" - manpower the way the game's manpower tooltip shows it (two decimals, cut off). */
export function manpowerText(n) {
  if (n == null) return '—';
  if (n >= 1e6) return `${(Math.floor(n / 1e4) / 100).toFixed(2)}M`;
  if (n >= 1e3) return `${(Math.floor(n / 10) / 100).toFixed(2)}K`;
  return String(Math.round(n));
}

/** "9 Infantry" lines of a template part. */
export function unitLines(units) {
  return units.map((u) => `${u.count} ${u.name}`);
}

/** Stat value as the game's design tooltip shows it (reliability in %, speed in km/h, range in km). */
export function statText(key, value) {
  if (key === 'reliability') return `${(value * 100).toFixed(1)}%`;
  if (key === 'maximum_speed') return `${+value.toFixed(1)} km/h`;
  if (key === 'range') return `${Math.round(value)} km`;
  return `${+value.toFixed(2)}`;
}

function bigNumber(label, value, title) {
  return h('div', { class: 'mil-big', title }, h('span', { class: 'mil-big-value' }, value), h('span', { class: 'mil-big-label' }, label));
}

/** Value cut off like the division designer shows it (122.96 -> "122.9"). */
function cut(v, decimals) {
  const f = 10 ** decimals;
  return ((Math.sign(v) * Math.trunc(Math.abs(v) * f + 1e-9)) / f).toFixed(decimals);
}

// [key, label, format] in the designer's order: base stats, combat stats, cost
const DESIGNER_GROUPS = [
  ['Base Stats', [
    ['maximum_speed', 'Max Speed', (v) => `${cut(v, 1)} km/h`], ['max_strength', 'HP', (v) => cut(v, 1)],
    ['max_organisation', 'Organization', (v) => cut(v, 1)], ['default_morale', 'Recovery Rate', (v) => cut(v, 2)],
    ['recon', 'Reconnaissance', (v) => cut(v, 1)], ['suppression', 'Suppression', (v) => cut(v, 1)],
    ['weight', 'Weight', (v) => cut(v, 1)], ['supply_consumption', 'Supply Use', (v) => cut(v, 2)],
    ['reliability', 'Av. Reliability ≈', (v) => `${cut(v * 100, 1)}%`],
    ['casualty_trickleback', 'Trickleback', (v) => `${cut(v * 100, 2)}%`],
    ['experience_loss_factor', 'Exp. Loss', (v) => `${cut(v * 100, 2)}%`]]],
  ['Combat Stats', [
    ['soft_attack', 'Soft Attack', (v) => cut(v, 1)], ['hard_attack', 'Hard Attack', (v) => cut(v, 1)],
    ['air_attack', 'Air Attack', (v) => cut(v, 1)], ['defense', 'Defense', (v) => cut(v, 1)],
    ['breakthrough', 'Breakthrough', (v) => cut(v, 1)], ['armor_value', 'Armor', (v) => cut(v, 1)],
    ['ap_attack', 'Piercing', (v) => cut(v, 1)], ['initiative', 'Initiative', (v) => `${cut(v * 100, 2)}%`],
    ['entrenchment', 'Entrenchment', (v) => cut(v, 1)], ['combat_width', 'Combat Width', (v) => cut(v, 0)]]],
  ['Equipment Cost', [
    ['manpower', 'Manpower', (v) => cut(v, 0)], ['training_time', 'Training Time', (v) => cut(v, 0)]]],
];

/** [[group title, [[label, text]]]] of a template's designer stats (missing values left out); `cost` (backend
 * divisions.equipment_cost) adds fuel and the equipment the division needs to the Equipment Cost column, as the game. */
export function designerLines(stats, cost = null) {
  const lines = DESIGNER_GROUPS.map(([title, rows]) => [title, rows.filter(([k]) => stats[k] != null).map(([k, label, f]) => [label, f(stats[k])])]);
  if (cost) {
    lines[lines.length - 1][1].push(['Fuel Capacity', cut(cost.fuel_capacity, 1)], ['Fuel Usage', cut(cost.fuel_usage, 2)],
      ...Object.entries(cost.equipment).map(([a, n]) => [cost.names?.[a] ?? a, String(Math.round(n))]));
  }
  return lines;
}

/** "444 to 510" / "510" - the designer's Estimated Production Cost (cheapest to dearest design of each equipment). */
export function productionCostText(cost) {
  if (!cost) return null;
  const lo = Math.round(cost.cost_min);
  const hi = Math.round(cost.cost_max);
  return lo === hi ? String(hi) : `${lo} to ${hi}`;
}

function designerBlock(d) {
  if (!d) return null;
  const notes = [];
  if (d.estimate.length) notes.push(`Estimate: several current designs of ${d.estimate.join(', ')} - the first is used.`);
  if (d.missing_equipment.length) notes.push(`No design of ${d.missing_equipment.join(', ')} - counted as 0.`);
  const designs = Object.values(d.designs);
  return h('details', { class: 'mil-designer' },
    h('summary', null, 'Division designer stats', d.estimate.length ? h('span', { class: 'muted' }, ' (estimate)') : null),
    h('div', { class: 'mil-designer-grid' }, designerLines(d.stats, d.cost).map(([title, rows]) => h('div', { class: 'mil-designer-group' },
      h('div', { class: 'mil-part-title' }, title),
      rows.map(([label, text]) => h('div', { class: 'hoi-line' }, h('span', { class: 'hoi-mod' }, designerIcon(label), label), h('span', { class: 'hoi-num' }, text)))))),
    d.cost ? h('div', { class: 'hoi-line mil-dd-prodcost' }, h('span', { class: 'hoi-mod' }, designerIcon('Estimated Production Cost'), 'Estimated Production Cost'),
      h('span', { class: 'hoi-num' }, productionCostText(d.cost))) : null,
    designs.length ? h('p', { class: 'muted mil-designer-note' }, `Equipment: ${designs.join(', ')}`) : null,
    notes.map((n) => h('p', { class: 'muted mil-designer-note' }, n)),
    h('p', { class: 'muted mil-designer-note', title: 'Reliability is still an estimate; doctrine milestones are not counted' },
      'From the game files, the newest designs, researched technologies and unlocked doctrines.'));
}

export const GRID_SIDE = 5;

/** Columns of the designer grid: [[unit id | null] x 5 rows] x 5 (the backend's slot = column * 5 + row). */
export function gridColumns(slots) {
  return Array.from({ length: GRID_SIDE }, (_, c) => Array.from({ length: GRID_SIDE }, (_, r) => slots?.[c * GRID_SIDE + r] ?? null));
}

// icons of the designer, fetched once (GET /api/military/icons) and kept for the session: unit id / template number
const icons = { units: new Map(), templates: new Map(), modules: new Map(), blueprints: new Map(), designer: {} };
const PLANE_VIEW_KEY = 'hoi4dbg.planeView';
// slots in the game's plane designer: 5 weapons above the blueprint, 7 below (engine and specials); more are locked
const PLANE_SLOTS = { top: 5, bottom: 7 };
// the designer's stats the debugger has no memory offset for yet (supply use is computed by the game)
const PLANE_UNREAD = ['Supply Use', 'Ground Attack', 'Strat. Bombing', 'Night Penalty', 'Minelaying', 'Minesweeping'];

// [title, [[key, label, format]]] as the plane designer's Base / Combat / Misc. Stats
const PLANE_GROUPS = [
  ['Base Stats', [['maximum_speed', 'Max Speed', (v) => `${cut(v, 1)} km/h`], ['range', 'Range', (v) => `${Math.round(v)} km`],
    ['weight', 'Weight', (v) => cut(v, 1)], ['thrust', 'Thrust', (v) => cut(v, 1)]]],
  ['Combat Stats', [['air_defence', 'Air Defense', (v) => cut(v, 1)], ['air_attack', 'Air Attack', (v) => cut(v, 1)],
    ['air_agility', 'Agility', (v) => cut(v, 1)], ['air_superiority', 'Air Superiority', (v) => cut(v, 2)],
    ['naval_strike_attack', 'Naval Attack', (v) => cut(v, 2)], ['naval_strike_targetting', 'Naval Targeting', (v) => cut(v, 2)]]],
  ['Misc. Stats', [['reliability', 'Reliability', (v) => `${cut(v * 100, 1)}%`], ['fuel_consumption', 'Fuel Usage', (v) => cut(v, 2)],
    ['surface_detection', 'Surface Detection', (v) => cut(v, 1)], ['sub_detection', 'Sub Detection', (v) => cut(v, 1)]]],
];

/** [[group title, [[label, text]]]] of a plane design like the game's designer (zero values shown, as the game does). */
export function planeStatLines(stats) {
  return PLANE_GROUPS.map(([title, rows]) => [title, rows.filter(([k]) => stats[k] != null).map(([k, label, f]) => [label, f(stats[k])])]);
}

function saveView(key, v) {
  try { localStorage.setItem(key, v); } catch { /* preference only */ }
}

/** "Main weapon" / "Weapon 2" / "Engine" / "Special 1" - a plane designer slot (the game has no name for them). */
export function slotLabel(slot) {
  if (slot === 'fixed_main_weapon_slot') return 'Main weapon';
  const aux = /^fixed_auxiliary_weapon_slot_(\d+)$/.exec(slot);
  if (aux) return `Weapon ${Number(aux[1]) + 1}`;
  if (slot === 'engine_type_slot') return 'Engine';
  const special = /^special_type_slot_(\d+)$/.exec(slot);
  if (special) return `Special ${special[1]}`;
  return slot.replace(/_slot$/, '').replace(/_/g, ' ');
}

/** [weapon slots, engine and special slots] - the plane designer's top and bottom row. */
export function slotRows(slots) {
  const weapon = (s) => s.slot.includes('weapon');
  return [slots.filter(weapon), slots.filter((s) => !weapon(s))];
}
const VIEW_KEY = 'hoi4dbg.armyView';

function loadView(key = VIEW_KEY) {
  try { return localStorage.getItem(key) === 'text' ? 'text' : 'graphic'; } catch { return 'graphic'; }
}

function iconImg(uri, alt, cls) {
  return uri ? h('img', { class: cls, src: uri, alt, draggable: 'false' }) : h('span', { class: `${cls} mil-icon-missing` }, alt.slice(0, 2));
}

function templateIcon(t) {
  const uri = t.icon?.template != null ? icons.templates.get(String(t.icon.template)) : icons.units.get(t.icon?.unit);
  return h('span', { class: 'mil-tpl-icon' }, uri ? h('img', { src: uri, alt: '', draggable: 'false' }) : null);
}

function slot(id, names, cls = '') {
  if (!id) return h('div', { class: `mil-slot mil-slot-empty ${cls}`.trim() });
  return h('div', { class: `mil-slot ${cls}`.trim(), title: names[id] ?? id }, iconImg(icons.units.get(id), names[id] ?? id, 'mil-slot-img'));
}

/** The template drawn like the game's division designer: battalion columns, support companies, regimental support. */
function designerGraphic(t, names) {
  const cols = gridColumns(t.grid?.battalions);
  const width = t.designer?.stats?.combat_width;
  return h('div', { class: 'mil-dd' },
    h('div', { class: 'mil-dd-board' },
      width != null ? h('div', { class: 'mil-dd-width', title: 'Combat width' }, cut(width, 0)) : null,
      h('div', { class: 'mil-dd-main' },
        h('div', { class: 'mil-dd-cols' }, cols.map((col) => h('div', { class: 'mil-dd-col' }, col.map((id) => slot(id, names))))),
        h('div', { class: 'mil-dd-support' }, h('div', { class: 'mil-dd-label' }, 'Support'),
          (t.grid?.support ?? []).map((id) => slot(id, names, 'mil-slot-small')))),
      h('div', { class: 'mil-dd-regimental' },
        h('div', { class: 'mil-dd-regrow' }, (t.grid?.regimental ?? []).map((id) => slot(id, names, 'mil-slot-small'))),
        h('div', { class: 'mil-dd-label' }, 'Regimental Support'))),
    t.designer ? h('div', { class: 'mil-dd-side' },
      h('div', { class: 'mil-dd-stats' }, designerLines(t.designer.stats, t.designer.cost).map(([title, rows]) => h('div', { class: 'mil-dd-group' },
        h('div', { class: 'mil-dd-group-title' }, title),
        rows.map(([label, text]) => h('div', { class: 'hoi-line' }, h('span', { class: 'hoi-mod' }, designerIcon(label), label), h('span', { class: 'hoi-num' }, text)))))),
      t.designer.cost ? h('div', { class: 'mil-pdg-cost', title: 'From the cheapest to the dearest design of each equipment the country has' },
        h('span', { class: 'hoi-mod' }, designerIcon('Estimated Production Cost'), 'Estimated Production Cost:'), h('span', { class: 'hoi-num' }, productionCostText(t.designer.cost))) : null) : null);
}

function designerText(t) {
  const part = (title, units) => (units.length ? h('div', { class: 'mil-part' },
    h('div', { class: 'mil-part-title' }, title), h('div', { class: 'mil-part-list' }, unitLines(units).map((l) => h('span', null, l)))) : null);
  return h('div', { class: 'mil-dd-text' }, part('Battalions', t.battalions), part('Support', t.support),
    part('Regimental Support', t.regimental), designerBlock(t.designer));
}

export function armyPanel(ctx, tag) {
  const open = new Set();   // template names unfolded - kept across refreshes
  let view = loadView();
  let last = null;          // [body, res] of the last drawing, redrawn when icons arrive or the view changes

  async function fetchIcons(a) {
    const units = [...new Set(a.templates.flatMap((t) => [t.icon?.unit, ...Object.values(t.grid ?? {}).flat()]))]
      .filter((u) => u && !icons.units.has(u));
    const nums = [...new Set(a.templates.map((t) => t.icon?.template).filter((n) => n != null && !icons.templates.has(String(n))))];
    if (!units.length && !nums.length) return;
    units.forEach((u) => icons.units.set(u, null));   // asked once even when the game has no icon
    nums.forEach((n) => icons.templates.set(String(n), null));
    try {
      // commas encoded: the IPC bridge allows only [A-Za-z0-9_-.=&%] in a query
      const q = `units=${encodeURIComponent(units.join(','))}&templates=${encodeURIComponent(nums.join(','))}`;
      const res = (await ctx.api.get(`/api/military/icons?${q}`)).data;
      Object.entries(res.units).forEach(([k, v]) => icons.units.set(k, v));
      Object.entries(res.templates).forEach(([k, v]) => icons.templates.set(k, v));
      if (last) draw(...last);
    } catch (err) {   // names stay in place of icons
      ctx.api.log?.('warn', `Army icons unavailable: ${err.message}`);
    }
  }

  function templateRow(t, names) {
    const isOpen = open.has(t.name);
    const toggle = () => { if (isOpen) open.delete(t.name); else open.add(t.name); draw(...last); };
    const setView = (v) => (e) => {
      e.stopPropagation();
      view = v;
      try { localStorage.setItem(VIEW_KEY, v); } catch { /* preference only */ }
      draw(...last);
    };
    return h('div', { class: `mil-tpl ${t.count ? '' : 'mil-unused'} ${isOpen ? 'mil-tpl-open' : ''}`.trim() },
      h('button', { class: 'mil-tpl-head', 'aria-expanded': String(isOpen), onclick: toggle },
        templateIcon(t),
        h('span', { class: 'mil-tpl-name' }, t.name),
        h('span', { class: 'mil-count', title: 'Divisions with this template' }, t.count),
        h('span', { class: 'mil-tpl-caret' }, isOpen ? '▾' : '▸')),
      isOpen ? h('div', { class: 'mil-tpl-body' },
        h('div', { class: 'mil-view' }, [['graphic', 'Graphic'], ['text', 'Text']].map(([v, label]) =>
          h('button', { class: `mil-view-btn ${view === v ? 'mil-view-on' : ''}`, 'aria-pressed': String(view === v), onclick: setView(v) }, label))),
        view === 'graphic' ? designerGraphic(t, names) : designerText(t)) : null);
  }

  function draw(body, res) {
    last = [body, res];
    const a = res.data?.army;
    if (!a) {
      body.replaceChildren(notice('warn', `Army unavailable: ${res.note}`));
      return;
    }
    fetchIcons(a);
    const names = a.unit_names ?? {};
    const used = a.templates.filter((t) => t.count);
    const unused = a.templates.filter((t) => !t.count);
    body.replaceChildren(
      h('div', { class: 'mil-bigs' },
        bigNumber('Divisions', a.divisions, 'Divisions in the field'),
        bigNumber('Free manpower', manpowerText(a.manpower_free), `${a.manpower_free?.toLocaleString() ?? '—'} men available in the states the country controls`),
        bigNumber('Manpower in the field', shortCount(a.manpower_field), `${a.manpower_field?.toLocaleString() ?? '—'} men in the divisions`),
        bigNumber('In training', shortCount(a.manpower_training), `${a.manpower_training?.toLocaleString() ?? '—'} men in divisions being trained`),
        bigNumber('Templates in use', used.length, `${a.templates.length} templates in all`)),
      h('div', { class: 'mil-tpls' }, used.map((t) => templateRow(t, names))),
      unused.length ? h('details', { class: 'mil-more', open: open.has(' unused') || null,
        ontoggle: (e) => { if (e.target.open) open.add(' unused'); else open.delete(' unused'); } },
      h('summary', null, `Templates not in use (${unused.length})`),
      h('div', { class: 'mil-tpls' }, unused.map((t) => templateRow(t, names)))) : null);
  }

  return livePanel(ctx, { title: 'Army', url: url(tag), liveParts, render: draw });
}

function planeRow(p, labels, count) {
  const stats = p.stats ? h('div', { class: 'mil-stats' }, Object.entries(p.stats).filter(([, v]) => v)
    .map(([k, v]) => h('div', { class: 'hoi-line' }, h('span', null, labels[k] ?? k), h('span', { class: 'hoi-num' }, statText(k, v))))) : null;
  return h('details', { class: 'mil-plane' },
    h('summary', null, h('span', { class: 'mil-plane-name' }, p.design || '?'), h('span', { class: 'mil-count' }, count)),
    stats ?? h('p', { class: 'muted' }, 'No design stats'));
}

/** "1936.05.18" / "before 1936.05.01" / "unknown" - when a design was first seen (the game keeps no creation date). */
export function designDate(d) {
  if (!d.seen) return 'unknown';
  return d.seen_before ? `before ${d.seen}` : d.seen;
}

/** {current, decommissioned}: designs split by the game's outdated flag; base airframes (no own name) after named ones;
 * each design gets "replacedBy" (the designs made from it) and "olderCount" (its outdated ancestors). */
export function splitDesigns(designs) {
  const byId = new Map(designs.map((d) => [d.id, d]));
  const children = new Map();
  for (const d of designs) if (d.parent != null) (children.get(d.parent) ?? children.set(d.parent, []).get(d.parent)).push(d);
  const same = (a, b) => (a.family ?? a.name) === (b.family ?? b.name) && !!(a.family ?? a.name);   // one plane's versions
  const older = (d) => {
    let n = 0;
    for (let p = byId.get(d.parent); p && same(p, d) && p.outdated && n < 50; p = byId.get(p.parent)) n += 1;
    return n;
  };
  const rows = designs.map((d) => ({ ...d, base: d.name === d.type_name, olderCount: older(d),
    replacedBy: (children.get(d.id) ?? []).filter((c) => same(c, d)).map((c) => c.name) }));
  const order = (a, b) => a.base - b.base;
  return { current: rows.filter((d) => !d.outdated).sort(order), decommissioned: rows.filter((d) => d.outdated).sort(order) };
}

export function airPanel(ctx, tag) {
  let planeView = loadView(PLANE_VIEW_KEY);
  let designTab = 'current';
  const openDesigns = new Set();
  let last = null;

  function designRow(d, labels) {
    const key = String(d.id);
    const isOpen = openDesigns.has(key);
    const toggle = () => { if (isOpen) openDesigns.delete(key); else openDesigns.add(key); draw(...last); };
    const note = d.outdated ? (d.replacedBy.length ? 'replaced by a newer version' : 'outdated')
      : (d.olderCount ? `${d.olderCount} older version${d.olderCount > 1 ? 's' : ''} in Decommissioned` : null);
    return h('div', { class: `mil-design ${d.outdated ? 'mil-design-old' : ''} ${isOpen ? 'mil-design-open' : ''}`.trim() },
      h('button', { class: 'mil-design-head', 'aria-expanded': String(isOpen), onclick: toggle },
        h('span', { class: 'mil-design-names' }, h('span', { class: 'mil-design-name' }, d.name),
          d.base ? null : h('span', { class: 'mil-design-type' }, d.type_name)),
        h('span', { class: 'mil-design-cost', title: 'Production cost (IC)' }, (d.stats.build_cost_ic ?? 0).toFixed(1).replace(/\.0$/, '')),
        h('span', { class: 'mil-design-date', title: 'Game day the debugger first saw this design - the game keeps no creation date' },
          designDate(d)),
        h('span', { class: 'mil-tpl-caret' }, isOpen ? '▾' : '▸')),
      note ? h('div', { class: 'mil-design-note' }, note) : null,
      isOpen ? h('div', { class: 'mil-design-body' },
        h('div', { class: 'mil-view mil-design-view' }, [['graphic', 'Graphic'], ['text', 'Text']].map(([v, label]) =>
          h('button', { class: `mil-view-btn ${planeView === v ? 'mil-view-on' : ''}`, 'aria-pressed': String(planeView === v),
            onclick: () => { planeView = v; saveView(PLANE_VIEW_KEY, v); draw(...last); } }, label))),
        planeView === 'graphic' ? planeGraphic(d) : planeText(d, labels)) : null);
  }

  /** The design drawn like the game's plane designer: weapon slots, the airframe's blueprint, engine and special slots
   * (the slots the airframe lacks locked), the stats in three columns. */
  function planeGraphic(d) {
    const [top, bottom] = slotRows(d.slots ?? []);
    const row = (slots, size) => h('div', { class: 'mil-pdg-row' },
      slots.map((s) => moduleSlot(s)), Array.from({ length: Math.max(0, size - slots.length) }, () => lockedSlot()));
    const bp = icons.blueprints.get(d.type);
    const bg = icons.designer.background;
    return h('div', { class: 'mil-pdg' },
      h('div', { class: 'mil-pdg-left' },
        h('div', { class: 'mil-pdg-title' }, h('span', { class: 'mil-pdg-name' }, d.name), h('span', { class: 'mil-pdg-type' }, d.type_name)),
        row(top, PLANE_SLOTS.top),
        h('div', { class: 'mil-pdg-blueprint', style: bg ? { backgroundImage: `url("${bg}")` } : null },
          h('div', { class: 'mil-pdg-caption' }, d.type_name),
          bp ? h('img', { class: 'mil-pdg-plane', src: bp, alt: '', draggable: 'false' }) : null),
        row(bottom, PLANE_SLOTS.bottom)),
      h('div', { class: 'mil-pdg-stats' },
        h('div', { class: 'mil-dd-stats' }, planeStatLines(d.stats).map(([title, rows]) => h('div', { class: 'mil-dd-group' },
          h('div', { class: 'mil-dd-group-title' }, title),
          rows.map(([label, text]) => h('div', { class: 'hoi-line' }, h('span', { class: 'hoi-mod' }, designerIcon(label), label), h('span', { class: 'hoi-num' }, text)))))),
        h('div', { class: 'mil-pdg-cost' }, h('span', null, 'Production Cost:'), h('span', { class: 'hoi-num' }, cut(d.stats.build_cost_ic ?? 0, 2))),
        h('p', { class: 'muted mil-designer-note' }, `Not read from the game yet: ${PLANE_UNREAD.join(', ')}.`)));
  }

  function planeText(d, labels) {
    return h('div', null,
      d.slots?.length ? h('div', { class: 'mil-part mil-pd-text' }, h('div', { class: 'mil-part-title' }, 'Modules'),
        h('div', { class: 'mil-part-list' }, d.slots.map((s) => h('span', null, `${slotLabel(s.slot)}: ${s.module_name ?? '—'}`)))) : null,
      h('div', { class: 'mil-stats mil-design-stats' }, Object.entries(d.stats).filter(([, v]) => v)
        .map(([k, v]) => h('div', { class: 'hoi-line' }, h('span', null, labels[k] ?? k), h('span', { class: 'hoi-num' }, statText(k, v))))));
  }

  function lockedSlot() {
    const uri = icons.designer.locked;
    return h('div', { class: 'mil-pd-slot mil-pd-locked', title: 'Not available on this airframe' },
      uri ? h('img', { class: 'mil-pd-img', src: uri, alt: 'locked', draggable: 'false' }) : h('span', { class: 'mil-pd-label' }, '🔒'));
  }

  function moduleSlot(s) {
    const title = `${slotLabel(s.slot)}: ${s.module_name ?? 'empty'}`;
    if (!s.module) return h('div', { class: 'mil-pd-slot mil-pd-empty', title }, h('span', { class: 'mil-pd-label' }, slotLabel(s.slot)));
    const uri = icons.modules.get(s.module);
    return h('div', { class: 'mil-pd-slot', title },
      uri ? h('img', { class: 'mil-pd-img', src: uri, alt: s.module_name ?? s.module, draggable: 'false' })
        : h('span', { class: 'mil-pd-label' }, s.module_name ?? s.module));
  }

  async function fetchModuleIcons(designs) {
    const missing = [...new Set(designs.flatMap((d) => (d.slots ?? []).map((s) => s.module)))].filter((m) => m && !icons.modules.has(m));
    const types = [...new Set(designs.map((d) => d.type))].filter((t) => t && !icons.blueprints.has(t));
    if (!missing.length && !types.length) return;
    missing.forEach((m) => icons.modules.set(m, null));   // asked once even when the game has no icon
    types.forEach((t) => icons.blueprints.set(t, null));
    try {
      const q = `modules=${encodeURIComponent(missing.join(','))}&blueprints=${encodeURIComponent(types.join(','))}`;
      const res = (await ctx.api.get(`/api/military/icons?${q}`)).data;
      Object.entries(res.modules ?? {}).forEach(([k, v]) => icons.modules.set(k, v));
      Object.entries(res.blueprints ?? {}).forEach(([k, v]) => icons.blueprints.set(k, v));
      if (res.designer?.background) Object.assign(icons.designer, res.designer);
      if (last) draw(...last);
    } catch (err) {
      ctx.api.log?.('warn', `Plane module icons unavailable: ${err.message}`);
    }
  }

  function designsBlock(a) {
    const { current, decommissioned } = splitDesigns(a.designs ?? []);
    const tab = designTab === 'decommissioned' && decommissioned.length ? 'decommissioned' : 'current';
    const list = tab === 'current' ? current : decommissioned;
    return h('div', { class: 'mil-designs' },
      h('div', { class: 'mil-designs-head' }, h('span', { class: 'mil-part-title' }, 'Designs'),
        h('div', { class: 'mil-view' }, [['current', `Current (${current.length})`], ['decommissioned', `Decommissioned (${decommissioned.length})`]]
          .map(([v, label]) => h('button', { class: `mil-view-btn ${tab === v ? 'mil-view-on' : ''}`, 'aria-pressed': String(tab === v),
            disabled: (v === 'decommissioned' && !decommissioned.length) || null,
            onclick: () => { designTab = v; draw(...last); } }, label)))),
      list.length ? h('div', { class: 'mil-design-list' }, list.map((d) => designRow(d, a.stat_labels)))
        : h('p', { class: 'muted' }, 'No plane designs.'),
      h('p', { class: 'muted mil-designer-note' }, 'Dates: the game day the debugger first saw a design ("before" - it existed '
        + 'when the recording of this campaign began). The game itself keeps no creation date.'));
  }

  function draw(body, res) {
    last = [body, res];
    {
      const a = res.data?.air;
      if (!a) {
        body.replaceChildren(notice('warn', `Air force unavailable: ${res.note}`));
        return;
      }
      fetchModuleIcons(a.designs ?? []);
      const roles = {};
      for (const w of a.wings) (roles[w.role_name] ??= []).push(w);
      const reserve = a.reserve.reduce((n, r) => n + r.amount, 0);
      body.replaceChildren(
        h('div', { class: 'mil-bigs' },
          bigNumber('Planes deployed', Math.round(a.planes), 'Total airplane count (in air wings)'),
          bigNumber('Planes in stockpile', Math.round(reserve), 'Planes in the equipment stockpile, not in a wing')),
        a.wings.length ? h('div', { class: 'mil-roles' }, Object.entries(roles).map(([role, ws]) => h('div', { class: 'mil-role' },
          h('div', { class: 'mil-role-head' }, h('span', null, role), h('span', { class: 'mil-count' }, Math.round(ws.reduce((n, w) => n + w.planes, 0)))),
          ws.map((w) => planeRow(w, a.stat_labels, Math.round(w.planes))))))
          : h('p', { class: 'muted' }, 'No air wings deployed.'),
        a.reserve.length ? h('details', { class: 'mil-more' }, h('summary', null, `In the stockpile (${a.reserve.length} designs)`),
          h('div', { class: 'mil-role' }, a.reserve.map((r) => planeRow(r, a.stat_labels, Math.round(r.amount))))) : null,
        designsBlock(a));
    }
  }

  return livePanel(ctx, { title: 'Air Force', url: url(tag), liveParts, render: draw });
}

export function navyPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Navy', url: url(tag), liveParts,
    render(body, res) {
      const n = res.data?.navy;
      if (!n) {
        body.replaceChildren(notice('warn', `Navy unavailable: ${res.note}`));
        return;
      }
      body.replaceChildren(
        h('div', { class: 'mil-bigs' },
          bigNumber('Ships', n.ships, 'Ships in all fleets'),
          bigNumber('Fleets', n.fleets, 'Fleet count'),
          bigNumber('Task forces', n.task_forces, 'Task force count')),
        n.types.length ? h('div', { class: 'mil-roles' }, n.types.map((t) => h('div', { class: 'mil-role' },
          h('div', { class: 'mil-role-head' }, h('span', null, t.name), h('span', { class: 'mil-count' }, t.count)),
          t.classes.map((c) => h('div', { class: 'hoi-line mil-class' }, h('span', null, c.name), h('span', { class: 'hoi-num' }, c.count))))))
          : h('p', { class: 'muted' }, 'No ships.'));
    },
  });
}
