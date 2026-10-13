// Army / Air / Navy tiles: what the selected country has in the field, like the game's military overview -
// divisions per template with their composition and stats like the division designer, free manpower, manpower in
// the field and in training; planes per role and design with the
// design stats and planes in the stockpile; fleets, task forces and ships per type and class (game memory).
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
  ['Cost', [
    ['manpower', 'Manpower', (v) => cut(v, 0)], ['training_time', 'Training Time', (v) => `${cut(v, 0)} days`]]],
];

/** [[group title, [[label, text]]]] of a template's designer stats (missing values left out). */
export function designerLines(stats) {
  return DESIGNER_GROUPS.map(([title, rows]) => [title, rows.filter(([k]) => stats[k] != null).map(([k, label, f]) => [label, f(stats[k])])]);
}

function designerBlock(d) {
  if (!d) return null;
  const notes = [];
  if (d.estimate.length) notes.push(`Estimate: several current designs of ${d.estimate.join(', ')} - the first is used.`);
  if (d.missing_equipment.length) notes.push(`No design of ${d.missing_equipment.join(', ')} - counted as 0.`);
  const designs = Object.values(d.designs);
  return h('details', { class: 'mil-designer' },
    h('summary', null, 'Division designer stats', d.estimate.length ? h('span', { class: 'muted' }, ' (estimate)') : null),
    h('div', { class: 'mil-designer-grid' }, designerLines(d.stats).map(([title, rows]) => h('div', { class: 'mil-designer-group' },
      h('div', { class: 'mil-part-title' }, title),
      rows.map(([label, text]) => h('div', { class: 'hoi-line' }, h('span', null, label), h('span', { class: 'hoi-num' }, text)))))),
    designs.length ? h('p', { class: 'muted mil-designer-note' }, `Equipment: ${designs.join(', ')}`) : null,
    notes.map((n) => h('p', { class: 'muted mil-designer-note' }, n)),
    h('p', { class: 'muted mil-designer-note', title: 'Reliability is still an estimate; doctrine milestones are not counted' },
      'From the game files, the newest designs, researched technologies and unlocked doctrines.'));
}

function templateCard(t) {
  const part = (title, units) => (units.length ? h('div', { class: 'mil-part' },
    h('div', { class: 'mil-part-title' }, title), h('div', { class: 'mil-part-list' }, unitLines(units).map((l) => h('span', null, l)))) : null);
  return h('div', { class: `mil-template ${t.count ? '' : 'mil-unused'}` },
    h('div', { class: 'mil-template-head' }, h('span', { class: 'mil-template-name' }, t.name),
      h('span', { class: 'mil-count', title: 'Divisions with this template' }, t.count)),
    part('Battalions', t.battalions), part('Support', t.support), part('Regimental Support', t.regimental),
    designerBlock(t.designer));
}

export function armyPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Army', url: url(tag), liveParts,
    render(body, res) {
      const a = res.data?.army;
      if (!a) {
        body.replaceChildren(notice('warn', `Army unavailable: ${res.note}`));
        return;
      }
      const used = a.templates.filter((t) => t.count);
      const unused = a.templates.filter((t) => !t.count);
      body.replaceChildren(
        h('div', { class: 'mil-bigs' },
          bigNumber('Divisions', a.divisions, 'Divisions in the field'),
          bigNumber('Free manpower', manpowerText(a.manpower_free), `${a.manpower_free?.toLocaleString() ?? '—'} men available in the states the country controls`),
          bigNumber('Manpower in the field', shortCount(a.manpower_field), `${a.manpower_field?.toLocaleString() ?? '—'} men in the divisions`),
          bigNumber('In training', shortCount(a.manpower_training), `${a.manpower_training?.toLocaleString() ?? '—'} men in divisions being trained`),
          bigNumber('Templates in use', used.length, `${a.templates.length} templates in all`)),
        h('div', { class: 'mil-templates' }, used.map(templateCard)),
        unused.length ? h('details', { class: 'mil-more' }, h('summary', null, `Templates not in use (${unused.length})`),
          h('div', { class: 'mil-templates' }, unused.map(templateCard))) : null);
    },
  });
}

function planeRow(p, labels, count) {
  const stats = p.stats ? h('div', { class: 'mil-stats' }, Object.entries(p.stats).filter(([, v]) => v)
    .map(([k, v]) => h('div', { class: 'hoi-line' }, h('span', null, labels[k] ?? k), h('span', { class: 'hoi-num' }, statText(k, v))))) : null;
  return h('details', { class: 'mil-plane' },
    h('summary', null, h('span', { class: 'mil-plane-name' }, p.design || '?'), h('span', { class: 'mil-count' }, count)),
    stats ?? h('p', { class: 'muted' }, 'No design stats'));
}

export function airPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Air Force', url: url(tag), liveParts,
    render(body, res) {
      const a = res.data?.air;
      if (!a) {
        body.replaceChildren(notice('warn', `Air force unavailable: ${res.note}`));
        return;
      }
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
          h('div', { class: 'mil-role' }, a.reserve.map((r) => planeRow(r, a.stat_labels, Math.round(r.amount))))) : null);
    },
  });
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
