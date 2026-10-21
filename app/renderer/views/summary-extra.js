// Game summary - campaign analysis (2026-10-21, user's request): the user's notes on the timeline (shown on every chart,
// a click on a chart picks the day), the human players ranked by category now and a month of game time before, and
// the play sessions (real time, game days an hour, time stopped, who joined or left) - ic_history.py.
import { card, h, notice } from '../lib/dom.js';
import { dayText } from '../lib/linechart.js';
import { numberLocale } from '../lib/options.js';

const gameUrl = (id) => `/api/summary/games/${encodeURIComponent(id)}`;
const fmt = (v, d = 0) => (v == null ? '—' : v.toLocaleString(numberLocale(), { maximumFractionDigits: d }));

/** "2 h 05 min" / "45 min" of minutes. */
export function minutesText(m) {
  if (m == null) return '—';
  const total = Math.round(m);
  return total >= 60 ? `${Math.floor(total / 60)} h ${String(total % 60).padStart(2, '0')} min` : `${total} min`;
}

/** "14:05" (or "2026-10-21 14:05" when not today) of a unix time. */
export function wallText(sec, now = new Date()) {
  if (sec == null) return '—';
  const d = new Date(sec * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return d.toDateString() === now.toDateString() ? time : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`;
}

/** ▲ / ▼ / = of a rank against the rank before (a lower number is better). */
export function rankMove(rank, before) {
  if (rank == null || before == null) return { text: '', cls: '' };
  if (rank < before) return { text: `▲${before - rank}`, cls: 'gs-up' };
  if (rank > before) return { text: `▼${rank - before}`, cls: 'gs-down' };
  return { text: '=', cls: 'muted' };
}

/** Notes: el, notes (current list), update(gid, lastDay), pick(day) - onChange() redraws the charts. */
export function notesSection(ctx, onChange) {
  let gid = null;
  let last = null;
  let notes = [];
  let draftDay = null;
  let editing = null;   // id of the note being edited
  let error = null;
  const body = h('div', { class: 'gs-notes' });
  const el = card('Notes', body, { cls: 'gs-notes-card' });

  async function save(payload) {
    try {
      notes = (await ctx.api.post(`${gameUrl(gid)}/notes`, payload)).data;
      error = null;
      editing = null;
    } catch (err) {
      error = err.message;
    }
    render();
    onChange();
  }

  function render() {
    if (!gid) { body.replaceChildren(h('p', { class: 'muted' }, 'Choose a campaign above.')); return; }
    const day = draftDay ?? last;
    const text = h('input', { type: 'text', class: 'gs-note-text', maxlength: 2000, placeholder: 'What happened (e.g. "Italy left the Axis")',
      onkeydown: (e) => { if (e.key === 'Enter') add(); } });
    const add = () => { if (text.value.trim() && day != null) save({ t: day, text: text.value }); };
    body.replaceChildren(...[
      error ? notice('warn', `Note not saved: ${error}`) : null,
      h('div', { class: 'gs-note-new' },
        h('span', { class: 'gs-note-day', title: 'Click a chart to pick another day' }, day == null ? '—' : dayText(day)),
        text, h('button', { class: 'btn btn-small', onclick: add }, 'Add note')),
      h('p', { class: 'hint' }, 'Click a chart above to pick the day. Notes show on every chart as dashed lines.'),
      notes.length ? h('ul', { class: 'gs-note-list' }, notes.map((n) => {
        if (editing === n.id) {
          const input = h('input', { type: 'text', class: 'gs-note-text', value: n.text, maxlength: 2000,
            onkeydown: (e) => { if (e.key === 'Enter') save({ id: n.id, t: n.t, text: input.value }); if (e.key === 'Escape') { editing = null; render(); } } });
          queueMicrotask(() => input.focus());
          return h('li', null, h('span', { class: 'gs-note-date' }, n.date), input,
            h('button', { class: 'btn btn-small', onclick: () => save({ id: n.id, t: n.t, text: input.value }) }, 'Save'),
            h('button', { class: 'btn btn-small btn-ghost', onclick: () => { editing = null; render(); } }, 'Cancel'));
        }
        return h('li', null, h('span', { class: 'gs-note-date' }, n.date), h('span', { class: 'gs-note-body' }, n.text),
          h('button', { class: 'btn btn-small btn-ghost', title: 'Edit', onclick: () => { editing = n.id; render(); } }, 'Edit'),
          h('button', { class: 'btn btn-small btn-ghost', title: 'Delete this note',
            onclick: () => { if (window.confirm(`Delete the note of ${n.date}?`)) save({ id: n.id, t: n.t, text: '' }); } }, 'Delete'));
      })) : h('p', { class: 'muted' }, 'No notes yet.'),
    ].filter(Boolean));
    if (draftDay != null) queueMicrotask(() => text.focus());
  }

  return {
    el,
    get notes() { return notes; },
    async update(id, lastDay) {
      if (id !== gid) { draftDay = null; editing = null; }
      gid = id;
      last = lastDay;
      if (!gid) { notes = []; render(); return; }
      try {
        const next = (await ctx.api.get(`${gameUrl(gid)}/notes`)).data;
        const changed = JSON.stringify(next) !== JSON.stringify(notes);
        notes = next;
        if (changed || !body.childElementCount) {
          if (!body.contains(document.activeElement)) render();
          if (changed) onChange();
        }
      } catch (err) {
        body.replaceChildren(notice('warn', `Notes unavailable: ${err.message}`));
      }
    },
    pick(day) {
      draftDay = day;
      render();
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    },
  };
}

/** Ranking of the human players: el, update(gid, subjects). */
export function rankingSection(ctx) {
  const body = h('div', { class: 'gs-ranking' });
  const el = card('Players ranking', body, { cls: 'gs-ranking-card' });
  return {
    el,
    async update(gid, subjects) {
      if (!gid) { el.hidden = true; return; }
      let data;
      try {
        data = (await ctx.api.get(`${gameUrl(gid)}/ranking?subjects=${subjects ? 1 : 0}`)).data;
      } catch (err) {
        body.replaceChildren(notice('warn', `Ranking unavailable: ${err.message}`));
        return;
      }
      const players = new Set(data.categories.flatMap((c) => c.rows.map((r) => r.name)));
      el.hidden = players.size < 2;   // a ranking needs two players (multiplayer, or several recorded)
      if (el.hidden) return;
      body.replaceChildren(
        h('p', { class: 'hint' }, `On ${data.date}${data.since ? `, ▲▼ = places won or lost since ${data.since}` : ''}`
          + `${subjects ? ' - with each player\'s subjects' : ''}. Values recorded from 2026-10-21 are missing on older days.`),
        h('div', { class: 'gs-rank-grid' }, data.categories.map((c) => h('div', { class: 'gs-rank-cat' },
          h('div', { class: 'gs-rank-title' }, c.label),
          h('table', { class: 'table gs-rank-table' }, h('tbody', null, c.rows.map((r) => {
            const move = rankMove(r.rank, r.rank_before);
            return h('tr', null, h('td', { class: 'num gs-rank-place' }, r.rank ?? '—'),
              h('td', null, r.name, r.tag ? h('span', { class: 'muted' }, ` ${r.tag}`) : null),
              h('td', { class: 'num' }, fmt(r.value, c.key === 'kd' ? 2 : 0)),
              h('td', { class: `num ${move.cls}` }, move.text));
          })))))));
    },
  };
}

/** Play sessions: el, update(gid). */
export function sessionsSection(ctx) {
  const body = h('div', { class: 'gs-sessions' });
  const el = card('Play sessions', body, { cls: 'gs-sessions-card' });
  return {
    el,
    async update(gid) {
      if (!gid) { body.replaceChildren(h('p', { class: 'muted' }, 'Choose a campaign above.')); return; }
      let data;
      try {
        data = (await ctx.api.get(`${gameUrl(gid)}/sessions`)).data;
      } catch (err) {
        body.replaceChildren(notice('warn', `Sessions unavailable: ${err.message}`));
        return;
      }
      if (!data.sessions.length) {
        body.replaceChildren(notice('info', 'No session recorded yet - the real time of each game day is recorded from 2026-10-21.'));
        return;
      }
      const people = (list) => list.map((p) => `${p.name}${p.tag ? ` (${p.tag})` : ''}`).join(', ') || '—';
      const changes = (s) => [...s.joined.map((j) => `+${j.name} ${j.date}`), ...s.left.map((j) => `−${j.name} ${j.date}`)].join(', ') || '—';
      body.replaceChildren(
        h('table', { class: 'table gs-sess-table' },
          h('thead', null, h('tr', null, ...['Started', 'Ended', 'Game dates', 'Real time', 'Game days', 'Days / hour', 'Stopped',
            'Players', 'Joined / left'].map((t, i) => h('th', { class: [3, 4, 5, 6].includes(i) ? 'num' : null }, t)))),
          h('tbody', null, [...data.sessions].reverse().map((s) => h('tr', null,
            h('td', null, wallText(s.start)), h('td', null, wallText(s.end)), h('td', null, `${s.first} → ${s.last}`),
            h('td', { class: 'num' }, minutesText(s.minutes)), h('td', { class: 'num' }, fmt(s.days)),
            h('td', { class: 'num' }, fmt(s.days_per_hour, 1)),
            h('td', { class: 'num', title: 'The game hour stood still over 3 s: paused, or waiting for a player' }, minutesText(s.stopped_minutes)),
            h('td', null, people(s.players)), h('td', null, changes(s)))))),
        data.players.length ? h('table', { class: 'table gs-sess-table' },
          h('thead', null, h('tr', null, h('th', null, 'Player'), h('th', { class: 'num' }, 'Sessions'), h('th', { class: 'num' }, 'Time played'),
            h('th', null, 'Countries'))),
          h('tbody', null, data.players.map((p) => h('tr', null, h('td', null, p.name), h('td', { class: 'num' }, p.sessions),
            h('td', { class: 'num' }, minutesText(p.minutes)), h('td', null, p.countries.join(', ')))))) : null,
        h('p', { class: 'hint' }, `A new session starts after 15 minutes without a game day or when a save is loaded. ${data.recorded} of `
          + `${data.days} recorded days have their real time (recorded from 2026-10-21).`));
    },
  };
}
