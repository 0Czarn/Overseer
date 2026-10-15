import { h, card, notice, scopeBadge, toast, viewHeader } from '../lib/dom.js';
import { techDataSection } from './tech-data.js';

/** Fog of war switch (LOCAL memory write, single player only - backend live/service.set_fog_of_war). */
function fogToggle(ctx) {
  const input = h('input', { type: 'checkbox', disabled: true });
  const state = h('span', { class: 'muted', style: { marginLeft: '8px' } }, 'Reading…');
  const show = (d) => {
    input.checked = d.fog === false;
    input.disabled = d.mode !== 'SINGLEPLAYER';
    state.textContent = d.mode !== 'SINGLEPLAYER' ? `Off limits: ${d.mode ? 'multiplayer game' : 'single player not confirmed'}`
      : d.fog ? 'Fog of war on' : 'Fog of war OFF - the whole map is visible';
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
    default:
      return h('button', { class: 'btn btn-small', disabled: true }, 'Planned');
  }
}

function toolCard(tool, ctx) {
  return h('div', { class: `tool tool-${tool.scope}` },
    h('div', { class: 'tool-head' }, h('strong', null, tool.name), scopeBadge(tool.scope),
      tool.status === 'planned' ? h('span', { class: 'badge badge-na' }, 'PLANNED') : null),
    h('p', { class: 'muted' }, tool.description),
    h('div', { class: 'tool-action' }, actionFor(tool, ctx)));
}

export default {
  id: 'tools',
  title: 'Game Tools',
  short: 'GT',
  async render(root, ctx) {
    const [res, tech] = await Promise.all([ctx.api.get('/api/tools'), techDataSection(ctx)]);
    const local = res.data.filter((t) => t.scope === 'local');
    const shared = res.data.filter((t) => t.scope === 'shared');

    root.append(
      viewHeader('Game Tools', 'Local debugging and visibility helpers.'),
      notice('info', [scopeBadge('local'), ' tools affect only this app or your own client. ',
        scopeBadge('shared'), ' tools would change the common game state and are only enabled once they '
        + 'are synchronised through a mechanism the game itself uses.']),
      card('Local tools', h('div', { class: 'tool-grid' }, local.map((t) => toolCard(t, ctx)))),
      card('Shared-state tools', h('div', { class: 'tool-grid' }, shared.map((t) => toolCard(t, ctx))),
        { cls: 'card-shared' }),
      tech,
    );
  },
};
