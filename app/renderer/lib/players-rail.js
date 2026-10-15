// The players of the session in a column left of the tabs: account name and country of each player read from game
// memory (/api/live/players, the game's player list). Shown in multiplayer, always or never (Options).
import { h } from './dom.js';
import { tr } from './i18n.js';
import { loadOptions, refreshMs } from './options.js';

const POLL_MS = 5000;

/** Whether the column shows for this session ('mp' = more than one player or a multiplayer game). */
export function railVisible(mode, session) {
  if (mode === 'never' || !session?.players?.length) return false;
  return mode === 'always' || session.mode === 'MULTIPLAYER' || session.players.length > 1;
}

export function startPlayersRail(api, rail) {
  let names = null;   // tag -> country name
  let last = null;
  const draw = () => {
    const show = railVisible(loadOptions().playersRail, last);
    rail.hidden = !show;
    document.body.classList.toggle('with-players', show);
    if (!show) return;
    rail.replaceChildren(
      h('div', { class: 'pr-head', title: last.mode === 'MULTIPLAYER' ? 'Multiplayer session' : 'Single player' },
        h('span', null, tr('Players')), h('span', { class: 'pr-count' }, String(last.players.length))),
      h('div', { class: 'pr-list' }, last.players.map((p) => h('div', { class: `pr-player ${p.local ? 'pr-local' : ''}`,
        title: `${p.name ?? '?'} - ${p.tag ?? '?'}${names?.[p.tag] ? ` (${names[p.tag]})` : ''}${p.local ? ' - you' : ''}` },
      h('span', { class: 'pr-tag' }, p.tag ?? '?'),
      h('span', { class: 'pr-name' }, p.name ?? '?'),
      names?.[p.tag] ? h('span', { class: 'pr-country' }, names[p.tag]) : null))));
  };
  const tick = async () => {
    try {
      last = (await api.get('/api/live/players')).data;
      if (!names && last.players.length) {
        names = Object.fromEntries((await api.get('/api/countries')).data.map((c) => [c.tag, c.name]));
      }
    } catch {
      last = null;   // no game, menu, loading
    }
    draw();
    setTimeout(tick, refreshMs(POLL_MS));
  };
  tick();
  return { redraw: draw };
}
