// Players actions: what the player and the watched countries did in the game, day by day - focus, research, laws and
// spirits, advisors, leader, wars, war goals, division templates, equipment designs, construction, trade deals. The
// backend's IC recorder compares a daily snapshot from game memory with the day before (backend hoi4dbg/actions.py);
// the game itself keeps no such log, so only days played while the app runs are known.
import { card, h, notice, viewHeader } from '../lib/dom.js';
import { refreshMs } from '../lib/options.js';

const REFRESH_MS = 5000;
const PREFS_KEY = 'hoi4dbg.actions';

// kind -> [label, CSS hue class]
export const KINDS = {
  focus: ['Focus', 'pa-k-focus'], research: ['Research', 'pa-k-research'], researched: ['Technology', 'pa-k-research'],
  ideas: ['Law / spirit', 'pa-k-ideas'], advisors: ['Advisor', 'pa-k-people'], leader: ['Leader', 'pa-k-people'],
  wars: ['War', 'pa-k-war'], justifications: ['War goal', 'pa-k-war'], templates: ['Division template', 'pa-k-army'],
  designs: ['Equipment design', 'pa-k-army'], construction: ['Construction', 'pa-k-build'], trade: ['Trade', 'pa-k-build'],
};

/** Events filtered and grouped by game day, newest day first: [[date, [events]]]. */
export function groupByDay(events, { hidden = [], tag = '', search = '' } = {}) {
  const q = search.trim().toLowerCase();
  const days = new Map();
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i];
    if (hidden.includes(e.kind) || (tag && e.tag !== tag)) continue;
    if (q && !`${e.name} ${e.tag} ${KINDS[e.kind]?.[0] ?? e.kind} ${e.action}`.toLowerCase().includes(q)) continue;
    if (!days.has(e.date)) days.set(e.date, []);
    days.get(e.date).push(e);
  }
  return [...days.entries()];
}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {}; } catch { return {}; }
}

export default {
  id: 'actions',
  title: 'Players actions',
  short: 'PA',
  async render(root, ctx) {
    const prefs = { hidden: [], tag: '', ...loadPrefs() };
    const save = () => { try { localStorage.setItem(PREFS_KEY, JSON.stringify({ hidden: prefs.hidden, tag: prefs.tag })); } catch { /* preference only */ } };
    let data = null;
    let game = null;
    let search = '';
    let adding = '';
    let stopped = false;
    let timer = null;
    const controls = h('div', { class: 'pa-controls' });
    const list = h('div', { class: 'pa-list' });
    root.append(viewHeader('Players actions', 'What the player and the watched countries did, day by day - read from game memory while the app runs.'),
      controls, card('Events', list, { cls: 'act-main' }));

    async function setWatched(tags) {
      try {
        await ctx.api.post('/api/actions/watch', { tags });
      } catch (err) {
        list.prepend(notice('warn', `Watched countries not saved: ${err.message}`));
        return;
      }
      load();
    }

    function countryName(tag) {
      return data?.countries?.[tag] ? `${tag} - ${data.countries[tag]}` : tag;
    }

    function renderControls() {
      const player = data.player;
      const watched = data.watched ?? [];
      const add = () => {
        const tag = adding.trim().toUpperCase().slice(0, 4);
        if (/^[A-Z0-9]{2,4}$/.test(tag) && tag !== player && !watched.includes(tag)) { adding = ''; setWatched([...watched, tag]); }
      };
      const tags = [...new Set([player, ...watched, ...data.events.map((e) => e.tag)].filter(Boolean))];
      controls.replaceChildren(
        h('div', { class: 'pa-row' },
          h('label', { class: 'pa-field' }, h('span', { class: 'pa-label' }, 'Campaign'),
            h('select', { onchange: (e) => { game = e.target.value; load(); } },
              data.games.map((g) => h('option', { value: g.id, selected: g.id === data.game || null },
                `${g.player ?? '?'} · ${g.first ?? '-'} → ${g.last ?? '-'} · started ${(g.created ?? '').slice(0, 16)}${g.active ? ' · recording' : ''}`)))),
          h('div', { class: 'pa-field pa-watch' }, h('span', { class: 'pa-label' }, 'Watched'),
            player ? h('span', { class: 'pa-chip pa-chip-player', title: 'The player is always watched' }, countryName(player)) : null,
            watched.filter((t) => t !== player).map((t) => h('span', { class: 'pa-chip' }, countryName(t),
              h('button', { class: 'pa-chip-x', title: `Stop watching ${t}`, onclick: () => setWatched(watched.filter((x) => x !== t)) }, '×'))),
            h('input', { type: 'text', class: 'pa-add', placeholder: 'Tag, e.g. GER', maxlength: 4, value: adding, list: 'pa-tags',
              oninput: (e) => { adding = e.target.value; }, onkeydown: (e) => { if (e.key === 'Enter') add(); } }),
            h('datalist', { id: 'pa-tags' }, Object.entries(data.countries ?? {}).slice(0, 500).map(([t, n]) => h('option', { value: t }, n))),
            h('button', { class: 'btn btn-small', onclick: add }, 'Watch'))),
        h('div', { class: 'pa-row' },
          h('div', { class: 'pa-kinds' }, Object.entries(KINDS).map(([k, [label, hue]]) => {
            const on = !prefs.hidden.includes(k);
            return h('button', { class: `pa-kind ${hue} ${on ? 'pa-kind-on' : ''}`, 'aria-pressed': String(on),
              onclick: () => { prefs.hidden = on ? [...prefs.hidden, k] : prefs.hidden.filter((x) => x !== k); save(); renderList(); renderControls(); } }, label);
          })),
          h('select', { class: 'pa-tag', title: 'Show one country', onchange: (e) => { prefs.tag = e.target.value; save(); renderList(); } },
            h('option', { value: '' }, 'All countries'), tags.map((t) => h('option', { value: t, selected: t === prefs.tag || null }, countryName(t)))),
          h('input', { type: 'search', class: 'pa-search', placeholder: 'Search', value: search,
            oninput: (e) => { search = e.target.value; renderList(); } })));
    }

    function renderList() {
      if (!data.game) {
        list.replaceChildren(notice('info', 'No campaign recorded yet - keep the app open while you play.'));
        return;
      }
      const days = groupByDay(data.events, { hidden: prefs.hidden, tag: prefs.tag, search });
      const intro = notice('info', 'The first game day after the app starts or a save is loaded is the baseline: what happened '
        + 'while the app was closed is not known. Production lines are not logged yet.');
      if (!days.length) {
        list.replaceChildren(intro, h('p', { class: 'muted' }, data.events.length ? 'No action matches the filters.'
          : 'No action recorded yet - play a few days with the app open.'));
        return;
      }
      list.replaceChildren(...[intro, ...days.map(([date, events]) => h('section', { class: 'pa-day' },
        h('div', { class: 'pa-date' }, date, h('span', { class: 'muted' }, ` · ${events.length}`)),
        events.map((e) => h('div', { class: 'pa-event' },
          h('span', { class: 'pa-tagbadge', title: countryName(e.tag) }, e.tag),
          h('span', { class: `pa-kind-badge ${KINDS[e.kind]?.[1] ?? ''}` }, KINDS[e.kind]?.[0] ?? e.kind),
          h('span', { class: 'pa-action' }, e.action),
          h('span', { class: 'pa-name' }, e.name))))),
      data.events.length >= data.limit ? h('p', { class: 'muted' }, `Only the newest ${data.limit} actions are shown.`) : null]
        .filter(Boolean));   // replaceChildren would print a null
    }

    async function load() {
      clearTimeout(timer);
      try {
        const res = await ctx.api.get(`/api/actions${game ? `?game=${encodeURIComponent(game)}` : ''}`);
        if (stopped) return;
        data = res.data;
        game = data.game;
        const a = document.activeElement;   // do not reset a list being picked or a tag being typed
        if (!(controls.contains(a) && (a.tagName === 'SELECT' || a.tagName === 'INPUT'))) renderControls();
        renderList();
      } catch (err) {
        if (!stopped) list.replaceChildren(notice('warn', `Players actions unavailable: ${err.message}`));
      }
      if (!stopped && data?.games?.find((g) => g.id === data.game)?.active) timer = setTimeout(load, refreshMs(REFRESH_MS));
    }

    await load();
    return () => { stopped = true; clearTimeout(timer); };
  },
};
