// Game Tools: local helpers, every change the app can make with its method and whether it is allowed in the running
// game, campaign checkpoints (saves with a note) and the live memory check. 2026-10-23 (Krok G): the "Shared value
// change" placeholder replaced by the real list of changes (backend game_tools.py), no DEMO left on the tab.
import { h, card, notice, scopeBadge, table, toast, viewHeader } from '../lib/dom.js';
import { techDataSection } from './tech-data.js';

/** Fog of war switch (LOCAL memory write, single player or multiplayer when allowed in Options - backend
 *  live/service.set_fog_of_war, `allowed`). */
function fogToggle(ctx) {
  const input = h('input', { type: 'checkbox', disabled: true });
  const state = h('span', { class: 'muted', style: { marginLeft: '8px' } }, 'Reading…');
  const show = (d) => {
    input.checked = d.fog === false;
    input.disabled = !d.allowed;
    state.textContent = !d.allowed
      ? `Off limits: ${d.mode ? 'multiplayer game - allow it in Options > Multiplayer' : 'single player not confirmed'}`
      : `${d.fog ? 'Fog of war on' : 'Fog of war OFF - the whole map is visible'}${d.mode === 'MULTIPLAYER' ? ' (multiplayer, this client only)' : ''}`;
  };
  const fail = (err) => { input.disabled = true; state.textContent = `Not available: ${err.message}`; };
  ctx.api.get('/api/live/fog-of-war').then((r) => show(r.data), fail);
  input.addEventListener('change', async () => {
    const off = input.checked;
    input.disabled = true;
    try {
      const r = await ctx.api.post('/api/live/fog-of-war', { fog: !off, confirm_local: true });
      show(r.data);
      toast(off ? 'Fog of war off (this client only)' : 'Fog of war on', 'ok');
    } catch (err) {
      input.checked = !off;
      fail(err);
    }
  });
  return h('label', { class: 'switch' }, input, h('span', null, 'Map without fog'), state);
}

const scrollTo = (id) => () => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

function actionFor(tool, ctx) {
  switch (tool.id) {
    case 'always_on_top':
      return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: ctx.state.alwaysOnTop,
        onChange: (e) => ctx.setAlwaysOnTop(e.target.checked) }), h('span', null, 'Enabled'));
    case 'compact_mode':
      return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: ctx.state.compact,
        onChange: (e) => ctx.setState({ compact: e.target.checked }) }), h('span', null, 'Enabled'));
    case 'redetect':
      return h('button', { class: 'btn btn-small', onClick: async () => {
        const status = await ctx.refreshStatus();
        toast(status?.game?.detected ? 'HOI4 detected' : 'HOI4 not detected', status?.game?.detected ? 'ok' : 'info');
      } }, 'Run');
    case 'open_logs':
      return h('button', { class: 'btn btn-small', onClick: async () => {
        const res = await ctx.bridge.openGameLogsFolder();
        toast(res.ok ? `Opened ${res.path}` : res.error, res.ok ? 'ok' : 'error');
      } }, 'Open');
    case 'fog_of_war':
      return fogToggle(ctx);
    case 'save_inspector':
      return h('button', { class: 'btn btn-small', onClick: () => ctx.navigate('countries') }, 'Open');
    case 'checkpoints':
      return h('button', { class: 'btn btn-small', onClick: scrollTo('gt-checkpoints') }, 'Show');
    case 'live_check':
      return h('button', { class: 'btn btn-small', onClick: scrollTo('gt-live-check') }, 'Show');
    default:
      return null;
  }
}

function toolCard(tool, ctx) {
  return h('div', { class: `tool tool-${tool.scope}` },
    h('div', { class: 'tool-head' }, h('strong', null, tool.name), scopeBadge(tool.scope)),
    h('p', { class: 'muted' }, tool.description),
    h('div', { class: 'tool-action' }, actionFor(tool, ctx)));
}

const STATUS = {
  allowed: ['badge-live', 'Allowed'],
  blocked: ['badge-shared', 'Blocked'],
  untested: ['badge-demo', 'Not tested'],
  unknown: ['badge-na', 'Unknown'],
};
const statusBadge = (s) => h('span', { class: `badge ${STATUS[s]?.[0] ?? 'badge-na'}` }, STATUS[s]?.[1] ?? s);

/** Every change the app can make: where, how, and whether a click would be allowed now (GET /api/tools/changes). */
function changesCard(ctx) {
  const body = h('div', null, h('p', { class: 'muted' }, 'Reading…'));
  const load = async () => {
    try {
      const d = (await ctx.api.get('/api/tools/changes')).data;
      const mode = !d.running ? 'Game not running' : d.mode === 'MULTIPLAYER' ? 'Multiplayer'
        : d.mode === 'SINGLEPLAYER' ? 'Single player' : 'Mode unknown (game.log)';
      body.replaceChildren(
        h('p', null, h('strong', null, mode),
          d.running ? h('span', { class: d.version_supported ? 'muted' : 'warn-text' },
            d.version_supported ? ' - game version verified for memory access' : ' - game version NOT verified: memory changes off') : null,
          d.mode === 'MULTIPLAYER' ? h('span', { class: 'muted' },
            ` - Options: memory writes ${d.multiplayer_writes.enabled ? 'allowed' : 'refused'}, fog switch `
            + `${d.multiplayer_writes.fog ? 'allowed' : 'refused'}`) : null),
        table([
          { key: 'name', label: 'Change' },
          { key: 'tab', label: 'Where', render: (c) => h('button', { class: 'btn btn-small btn-ghost', onClick: () => ctx.navigate(c.view) }, c.tab) },
          { key: 'method', label: 'Method', render: (c) => h('span', null, scopeBadge(c.scope), ' ', c.method_text) },
          { key: 'status', label: 'Now', render: (c) => h('span', null, statusBadge(c.status), ' ', h('span', { class: 'muted' }, c.reason)) },
        ], d.changes),
        h('p', { class: 'hint' }, 'Console commands are the game\'s own: in single player the app prepares them, you type '
          + 'them and the app checks the result. Memory writes and the code patch change this client only - in a '
          + 'multiplayer game that desynchronises the others, so they are refused unless allowed in Options (starting '
          + 'a focus and the code patch: never). Whether console commands sync from every player in multiplayer is '
          + 'tested on two clients in Krok H.'));
    } catch (err) {
      body.replaceChildren(notice('warn', `Not available: ${err.message}`));
    }
  };
  load();
  return card('Changes to the game', body, { cls: 'card-shared',
    extra: h('button', { class: 'btn btn-small', onClick: load }, 'Refresh') });
}

const modified = (s) => new Date(s.mtime * 1000).toLocaleString();

/** The saves with game date, country and the user's note (GET/POST /api/tools/checkpoints). */
function checkpointsCard(ctx) {
  const body = h('div', null, h('p', { class: 'muted' }, 'Reading the saves…'));
  const filter = h('input', { class: 'input input-small', type: 'search', placeholder: 'Filter: name, country, note',
    'aria-label': 'Filter checkpoints' });
  let data = null;
  const noteInput = (s) => {
    const input = h('input', { class: 'input input-small gt-note', type: 'text', value: s.note, maxlength: 2000,
      placeholder: 'Add a note…', 'aria-label': `Note on ${s.name}` });
    const save = async () => {
      if (input.value.trim() === s.note) return;
      try {
        await ctx.api.post('/api/tools/checkpoints', { name: s.name, note: input.value });
        s.note = input.value.trim();
        s.note_changed = false;
        toast(s.note ? `Note saved: ${s.name}` : `Note removed: ${s.name}`, 'ok');
      } catch (err) {
        toast(err.message, 'error');
      }
    };
    input.addEventListener('change', save);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
    return h('span', null, input, s.note_changed ? h('div', { class: 'warn-text', title: 'The save file was written '
      + 'again after the note' }, 'save overwritten since') : null);
  };
  const show = () => {
    if (!data) return;
    const q = filter.value.trim().toLowerCase();
    const rows = data.saves.filter((s) => !q || [s.name, s.player_tag, s.note, s.date].some((v) => v?.toLowerCase().includes(q)));
    body.replaceChildren(
      table([
        { key: 'name', label: 'Save' },
        { key: 'date', label: 'Game date', render: (s) => s.date ?? h('span', { class: 'muted', title: s.error }, 'not readable') },
        { key: 'player_tag', label: 'Country', render: (s) => s.player_tag ?? '—' },
        { key: 'multiplayer', label: 'Game', render: (s) => (s.error ? '—' : s.multiplayer ? `MP (${s.players.length})` : 'SP') },
        { key: 'mtime', label: 'Saved', render: modified },
        { key: 'note', label: 'Note', render: noteInput, cls: 'gt-note-cell' },
      ], rows, { keyField: 'name', empty: q ? 'No save matches the filter' : 'No saves in the folder' }),
      h('p', { class: 'hint' }, `${data.total} saves in ${data.directory}${data.total > data.saves.length
        ? ` (the newest ${data.saves.length} shown)` : ''}. A checkpoint is a save you make in the game (Esc > Save, `
        + 'named as you like) - it appears here after Refresh; the note stays in the app, the save is never changed.'
        + `${data.orphan_notes.length ? ` Notes on ${data.orphan_notes.length} deleted saves are kept.` : ''}`));
  };
  const load = async () => {
    try {
      const r = await ctx.api.get('/api/tools/checkpoints');
      if (r.source === 'unavailable') {
        body.replaceChildren(notice('warn', r.note ?? 'Save folder not found'));
        return;
      }
      data = r.data;
      show();
    } catch (err) {
      body.replaceChildren(notice('warn', `Not available: ${err.message}`));
    }
  };
  filter.addEventListener('input', show);
  load();
  const el = card('Campaign checkpoints', body, {
    extra: h('div', { class: 'gt-head-tools' }, filter, h('button', { class: 'btn btn-small', onClick: load }, 'Refresh')) });
  el.id = 'gt-checkpoints';
  return el;
}

/** Every live memory reader once, on request (GET /api/tools/live-check). */
function liveCheckCard(ctx) {
  const body = h('div', null, h('p', { class: 'muted' }, 'Reads the player\'s country with every memory reader the app '
    + 'uses and shows which work and how long they take. Read-only; use it after a game or mod update.'));
  const run = h('button', { class: 'btn btn-small', onClick: async () => {
    run.disabled = true;
    body.replaceChildren(h('p', { class: 'muted' }, 'Reading game memory…'));
    try {
      const r = await ctx.api.get('/api/tools/live-check');
      const d = r.data;
      if (!d.running) {
        body.replaceChildren(notice('info', d.error ?? r.note ?? 'HOI4 is not running'));
        return;
      }
      const bad = d.checks.filter((c) => !c.ok).length;
      body.replaceChildren(
        h('p', null, h('strong', null, `${d.checks.length - bad} of ${d.checks.length} readers work`),
          h('span', { class: 'muted' }, ` - ${d.version ?? 'unknown version'}, player ${d.tag ?? 'not readable'}`)),
        table([
          { key: 'name', label: 'Reader' },
          { key: 'ok', label: 'Result', render: (c) => h('span', { class: `badge ${c.ok ? 'badge-live' : 'badge-shared'}` },
            c.ok ? 'OK' : 'Failed') },
          { key: 'detail', label: 'Detail', render: (c) => (c.ok ? c.detail : h('span', { class: 'bad-text' }, c.error)) },
          { key: 'ms', label: 'Time', render: (c) => `${c.ms} ms`, cls: 'num' },
        ], d.checks, { keyField: 'id' }));
    } catch (err) {
      body.replaceChildren(notice('warn', `Not available: ${err.message}`));
    } finally {
      run.disabled = false;
    }
  } }, 'Run check');
  const el = card('Live memory check', body, { extra: run });
  el.id = 'gt-live-check';
  return el;
}

export default {
  id: 'tools',
  title: 'Game Tools',
  short: 'GT',
  async render(root, ctx) {
    const [res, tech] = await Promise.all([ctx.api.get('/api/tools'), techDataSection(ctx)]);
    root.append(
      viewHeader('Game Tools', 'Local debugging and visibility helpers.'),
      notice('info', [scopeBadge('local'), ' tools affect only this app or your own client. ',
        scopeBadge('shared'), ' changes alter the common game state - below with the method each one uses and '
        + 'whether it is allowed in the running game.']),
      card('Local tools', h('div', { class: 'tool-grid' }, res.data.map((t) => toolCard(t, ctx)))),
      changesCard(ctx),
      checkpointsCard(ctx),
      liveCheckCard(ctx),
      tech,
    );
  },
};
