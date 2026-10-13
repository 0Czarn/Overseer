// Army / Air / Navy tiles: what the selected country has in the field, like the game's military overview -
// divisions per template with their composition and manpower in the field; planes per role and design with the
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

function templateCard(t) {
  const part = (title, units) => (units.length ? h('div', { class: 'mil-part' },
    h('div', { class: 'mil-part-title' }, title), h('div', { class: 'mil-part-list' }, unitLines(units).map((l) => h('span', null, l)))) : null);
  return h('div', { class: `mil-template ${t.count ? '' : 'mil-unused'}` },
    h('div', { class: 'mil-template-head' }, h('span', { class: 'mil-template-name' }, t.name),
      h('span', { class: 'mil-count', title: 'Divisions with this template' }, t.count)),
    part('Battalions', t.battalions), part('Support', t.support), part('Regimental Support', t.regimental));
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
          bigNumber('Manpower in the field', shortCount(a.manpower_field), `${a.manpower_field?.toLocaleString() ?? '—'} men in the divisions`),
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
