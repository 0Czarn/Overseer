// Time machine (2026-10-23, user's request: "a click on a division opens a new tab like a time machine showing what one
// wants"): a recorded campaign at any recorded moment - the game state of a country that day (every value the Game
// summary records, GET .../moment), every division then (GET .../divisions: filter, sort, pick) and one division's
// history (its card at that moment, organisation / strength / manpower over time, where it stood, its battles).
import { card, h, notice, viewHeader } from '../lib/dom.js';
import { compact, lineChart } from '../lib/linechart.js';
import { numberLocale } from '../lib/options.js';
import { dayLabel, divisionCard, expLevel, loadDivision } from './division-card.js';
import { METRIC_SECTIONS, metricFormat } from './summary.js';
import { TIME_MACHINE_KEY } from './summary-map.js';

const COLUMNS = [['name', 'Division'], ['tag', 'Country'], ['template', 'Template'], ['leader', 'Commander'], ['where', 'Location'],
  ['org', 'Org'], ['str', 'Strength'], ['exp', 'Experience'], ['mp', 'Manpower'], ['sup', 'Supply']];
const PAGE = 200;

/** The value a division list is sorted by (`key`: a COLUMNS key). */
export function sortValue(d, key) {
  const s = d.s ?? [];
  switch (key) {
    case 'org': return s[0] ?? -1;
    case 'str': return s[1] ?? -1;
    case 'exp': return s[2] ?? -1;
    case 'mp': return s[3] ?? -1;
    case 'sup': return s[5] ?? -1;
    default: return (d[key] ?? '').toString();
  }
}

/** The divisions matching the filters ({tag, template, text}), sorted by `sort` ({key, desc}). */
export function filterDivisions(list, { tag = '', template = '', text = '' } = {}, sort = { key: 'name', desc: false }) {
  const q = text.trim().toLowerCase();
  const out = list.filter((d) => (!tag || d.tag === tag) && (!template || d.template === template)
    && (!q || `${d.name ?? ''} ${d.template ?? ''} ${d.where ?? ''} ${d.army ?? ''} ${d.leader ?? ''}`.toLowerCase().includes(q)));
  const dir = sort.desc ? -1 : 1;
  return out.sort((a, b) => {
    const x = sortValue(a, sort.key);
    const y = sortValue(b, sort.key);
    return dir * (typeof x === 'number' ? x - y : x.localeCompare(y, undefined, { numeric: true }));
  });
}

/** The time read for a moment: a whole day means its last reading (a day's first one may be at any hour). */
export function readTime(t) {
  return Number.isInteger(t) ? t + 23.5 / 24 : t;
}

function loadTarget() {
  try { return JSON.parse(localStorage.getItem(TIME_MACHINE_KEY)) ?? {}; } catch { return {}; }
}

function saveTarget(v) {
  try { localStorage.setItem(TIME_MACHINE_KEY, JSON.stringify(v)); } catch { /* preference only */ }
}

export default {
  id: 'time-machine',
  title: 'Time machine',
  short: 'TM',
  async render(root, ctx) {
    const target = { game: null, t: null, division: null, tag: null, filters: {}, sort: { key: 'name', desc: false }, ...loadTarget() };
    const remember = () => saveTarget(target);
    const pick = h('div', { class: 'tm-pick' });
    const stateBody = h('div');
    const listBody = h('div');
    const divBody = h('div');
    root.append(viewHeader('Time machine', 'A recorded campaign at any recorded moment: the game state, every division, one division\'s history.'),
      card('Campaign and moment', pick), card('Game state', stateBody, { cls: 'tm-state' }),
      card('Divisions', listBody, { cls: 'tm-list' }), card('Division', divBody, { cls: 'tm-division' }));

    let games = [];
    try {
      games = (await ctx.api.get('/api/summary/games')).data.games;
    } catch (err) {
      pick.replaceChildren(notice('warn', `Recorded campaigns unavailable: ${err.message}`));
      return null;
    }
    if (!games.length) {
      pick.replaceChildren(notice('info', 'No campaign recorded yet - the Game summary records one while you play.'));
      return null;
    }
    if (!games.some((g) => g.id === target.game)) target.game = games[0].id;
    let days = [];
    let moment = null;
    let divisions = [];
    let shown = PAGE;
    let readTimer = 0;
    let seq = 0;

    const nameOf = (tag) => moment?.names?.[tag] ?? tag;
    const fmt = (v, digits = 0) => (v == null ? '—' : v.toLocaleString(numberLocale(), { maximumFractionDigits: digits }));

    async function openGame() {
      try {
        days = (await ctx.api.get(`/api/summary/games/${encodeURIComponent(target.game)}/map`)).data.t ?? [];
      } catch {
        days = [];
      }
      if (!days.length) {   // a campaign without the map: its days from the game state
        const g = games.find((x) => x.id === target.game);
        days = g?.last_t != null ? [g.last_t] : [];
      }
      if (target.t == null || target.t < days[0] || target.t > days[days.length - 1] + 1) target.t = days[days.length - 1] ?? 0;
      renderPick();
      await readMoment();
    }

    function renderPick() {
      const index = Math.max(0, days.findLastIndex((d) => d <= Math.floor(target.t)));
      const label = h('strong', { class: 'tm-date' }, dayLabel(target.t));
      const slider = h('input', { type: 'range', class: 'tm-slider', min: 0, max: Math.max(0, days.length - 1), value: index,
        'aria-label': 'Moment', oninput: (e) => {
          target.t = days[Number(e.target.value)];
          label.textContent = dayLabel(target.t);
          clearTimeout(readTimer);
          readTimer = setTimeout(() => { remember(); readMoment(); }, 250);
        } });
      const step = (d) => () => {
        const i = Math.max(0, Math.min(days.length - 1, days.findLastIndex((x) => x <= Math.floor(target.t)) + d));
        target.t = days[i];
        remember();
        renderPick();
        readMoment();
      };
      pick.replaceChildren(
        h('div', { class: 'tm-row' },
          h('label', null, 'Campaign ', h('select', { onchange: (e) => { target.game = e.target.value; target.t = null; target.division = null; remember(); openGame(); } },
            games.map((g) => h('option', { value: g.id, selected: g.id === target.game || null },
              `${g.player ?? '?'} · ${g.first ?? '?'} – ${g.last ?? '?'} (${g.days} days)`)))),
          h('button', { class: 'btn btn-small', onclick: step(-1), title: 'The day before' }, '◀'), label,
          h('button', { class: 'btn btn-small', onclick: step(1), title: 'The next day' }, '▶')),
        slider);
    }

    async function readMoment() {
      const mine = ++seq;
      const q = `t=${readTime(target.t)}`;
      const base = `/api/summary/games/${encodeURIComponent(target.game)}`;
      try {
        const [m, d] = await Promise.all([ctx.api.get(`${base}/moment?${q}`), ctx.api.get(`${base}/divisions?${q}`).catch(() => null)]);
        if (mine !== seq) return;
        moment = m.data;
        divisions = d?.data?.divisions ?? [];
      } catch (err) {
        if (mine !== seq) return;
        stateBody.replaceChildren(notice('warn', `Game state unavailable: ${err.message}`));
        return;
      }
      if (!target.tag || !moment.countries[target.tag]) target.tag = Object.keys(moment.players ?? {})[0] ?? Object.keys(moment.countries)[0];
      renderState();
      renderList();
      renderDivision();
    }

    function renderState() {
      const tags = Object.keys(moment.countries).sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
      const players = Object.keys(moment.players ?? {});
      const values = moment.countries[target.tag] ?? {};
      const player = moment.players?.[target.tag];
      stateBody.replaceChildren(
        h('div', { class: 'tm-row' },
          h('label', null, 'Country ', h('select', { onchange: (e) => { target.tag = e.target.value; target.filters.tag = ''; remember(); renderState(); renderList(); } },
            players.length ? h('optgroup', { label: 'Players' }, players.map((t) => h('option', { value: t, selected: t === target.tag || null }, `${nameOf(t)} (${t})`))) : null,
            h('optgroup', { label: 'Countries' }, tags.filter((t) => !players.includes(t)).map((t) =>
              h('option', { value: t, selected: t === target.tag || null }, `${nameOf(t)} (${t})`))))),
          h('span', { class: 'muted' }, `Recorded day ${dayLabel(moment.day)}`),
          moment.factions?.[target.tag] ? h('span', null, `Faction: ${moment.factions[target.tag]}`) : null,
          player ? h('span', null, `Player: ${player.n}`) : null),
        h('div', { class: 'tm-metrics' }, METRIC_SECTIONS.map(([section, list]) => h('div', { class: 'tm-section' },
          h('div', { class: 'dc-title' }, section),
          list.map(([k, title]) => h('div', { class: 'hoi-line' }, h('span', { class: 'hoi-mod' }, title),
            h('span', { class: 'hoi-num' }, values[k] == null ? '—' : metricFormat(k)(values[k]))))))));
    }

    function renderList() {
      const f = { tag: target.filters.tag ?? target.tag ?? '', template: target.filters.template ?? '', text: target.filters.text ?? '' };
      if (!divisions.length) {
        listBody.replaceChildren(notice('info', 'No division recorded on its own at this moment - divisions are recorded one by one from 2026-10-23.'));
        return;
      }
      const rows = filterDivisions(divisions, f, target.sort);
      const tags = [...new Set(divisions.map((d) => d.tag))].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
      const templates = [...new Set(divisions.filter((d) => !f.tag || d.tag === f.tag).map((d) => d.template).filter(Boolean))].sort();
      const set = (k) => (e) => { target.filters[k] = e.target.value; if (k === 'tag') target.filters.template = ''; shown = PAGE; remember(); renderList(); };
      const sortBy = (k) => () => { target.sort = { key: k, desc: target.sort.key === k ? !target.sort.desc : ['org', 'str', 'exp', 'mp', 'sup'].includes(k) }; remember(); renderList(); };
      const search = h('input', { type: 'search', placeholder: 'Name, template, location, commander', value: f.text,
        oninput: (e) => { target.filters.text = e.target.value; clearTimeout(readTimer); readTimer = setTimeout(() => { remember(); renderList(); search.focus(); }, 250); } });
      listBody.replaceChildren(...[
        h('div', { class: 'tm-row' },
          h('select', { onchange: set('tag'), 'aria-label': 'Country' }, h('option', { value: '' }, 'All countries'),
            tags.map((t) => h('option', { value: t, selected: t === f.tag || null }, `${nameOf(t)} (${t})`))),
          h('select', { onchange: set('template'), 'aria-label': 'Template' }, h('option', { value: '' }, 'All templates'),
            templates.map((t) => h('option', { value: t, selected: t === f.template || null }, t))),
          search, h('span', { class: 'muted' }, `${rows.length} of ${divisions.length} divisions`)),
        h('div', { class: 'tm-table-wrap' }, h('table', { class: 'tm-table' },
          h('thead', null, h('tr', null, COLUMNS.map(([k, label]) => h('th', { onclick: sortBy(k), class: 'tm-sort' },
            label, target.sort.key === k ? (target.sort.desc ? ' ▾' : ' ▴') : '')))),
          h('tbody', null, rows.slice(0, shown).map((d) => {
            const s = d.s ?? [];
            return h('tr', { class: d.id === target.division ? 'tm-on' : '', onclick: () => { target.division = d.id; remember(); renderList(); renderDivision(); } },
              h('td', null, d.name ?? `Division ${d.id}`), h('td', null, d.tag), h('td', null, d.template ?? '—'),
              h('td', { title: d.army ?? '' }, d.leader ?? (d.army ? d.army : '—')),
              h('td', null, d.where ?? `Province ${d.pid}`), h('td', { class: 'num' }, fmt(s[0], 1)), h('td', { class: 'num' }, fmt(s[1], 1)),
              h('td', { class: 'num' }, s[2] == null ? '—' : fmt(s[2])), h('td', { class: 'num' }, fmt(s[3])),
              h('td', { class: 'num' }, s[5] == null ? '—' : `${s[5]}%`));
          })))),
        rows.length > shown ? h('button', { class: 'btn btn-small', onclick: () => { shown += PAGE; renderList(); } }, `Show ${Math.min(PAGE, rows.length - shown)} more`) : null].filter(Boolean));
    }

    async function renderDivision() {
      if (target.division == null) {
        divBody.replaceChildren(h('p', { class: 'muted' }, 'Pick a division in the list (or click one on the Game summary map).'));
        return;
      }
      const id = target.division;
      const place = (pid) => divisions.find((d) => d.pid === pid)?.where ?? `Province ${pid}`;
      divBody.replaceChildren(h('div', { class: 'tm-div' }, divisionCard(ctx, target.game, id, readTime(target.t), { place }), h('div', { class: 'tm-div-history' }, h('p', { class: 'muted' }, 'Loading its history…'))));
      let data;
      try {
        data = await loadDivision(ctx, target.game, id);
      } catch (err) {
        divBody.querySelector('.tm-div-history')?.replaceChildren(notice('warn', err.message));
        return;
      }
      if (target.division !== id) return;
      const stats = data.history.filter((x) => x[1] === 's' && x[2]);
      const series = (i, label, color) => ({ label, color, points: stats.map(([t, , s]) => [t, s[i]]) });
      const moves = data.history.filter((x) => x[1] === 'p' && x[2]);
      const where = [];   // the places it stood, each stay once
      for (const [t, , [pid, to]] of moves) {
        if (where.length && where[where.length - 1].pid === pid) { if (to) where[where.length - 1].to = to; continue; }
        where.push({ t, pid, to });
      }
      const history = divBody.querySelector('.tm-div-history');
      history?.replaceChildren(...[
        stats.length > 1 ? lineChart({ title: 'Organisation and strength', series: [series(0, 'Organisation', '#3987e5'), series(1, 'Strength', '#d95926')], format: compact })
          : h('p', { class: 'muted' }, 'Organisation and strength over time: one reading so far.'),
        stats.length > 1 ? lineChart({ title: 'Manpower', series: [series(3, 'Manpower', '#199e70')], format: compact }) : null,
        stats.length ? h('p', { class: 'muted' }, `Experience: ${expLevel(stats[stats.length - 1][2][2], stats[stats.length - 1][2][3] || 1).name} at the last reading`) : null,
        h('div', { class: 'dc-title' }, `Where it stood (${where.length})`),
        h('div', { class: 'tm-path' }, where.slice(-60).reverse().map((w) => h('button', { class: `tm-path-row ${w.t <= readTime(target.t) ? '' : 'muted'}`,
          title: 'Go to this moment', onclick: () => { target.t = w.t; remember(); renderPick(); readMoment(); } },
        h('span', { class: 'muted' }, dayLabel(w.t)), h('span', null, place(w.pid)), w.to ? h('span', { class: 'muted' }, `→ ${place(w.to)}`) : h('span')))),
        h('div', { class: 'dc-title' }, `Battles (${data.battles.length} readings)`),
        data.battles.length ? h('div', { class: 'tm-path' }, data.battles.slice(-40).reverse().map(([t, pid, [att, dfn, na, nd, share]]) =>
          h('div', { class: 'tm-path-row' }, h('span', { class: 'muted' }, dayLabel(t)), h('span', null, place(pid)),
            h('span', null, `${att} ${na} vs ${dfn} ${nd} · attacker ${share}%`))))
          : h('p', { class: 'muted' }, 'No battle recorded where it stood or attacked.')].filter(Boolean));
    }

    await openGame();
    return () => clearTimeout(readTimer);
  },
};
