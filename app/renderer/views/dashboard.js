import { h, card, keyValues, notice, sourceBadge, table, viewHeader } from '../lib/dom.js';
import { formatDuration, humanize } from '../lib/format.js';

function processCard(game) {
  const proc = game.process;
  if (!proc) {
    return card('Game process', [
      notice('muted', 'Hearts of Iron IV is not running (or could not be detected).'),
      (game.warnings ?? []).map((w) => notice('warn', w)),
    ], { extra: sourceBadge(game.warnings?.length ? 'unavailable' : 'live') });
  }
  return card('Game process', [keyValues([
    ['Status', h('span', { class: 'status-ok' }, 'Running')],
    ['PID', proc.pid],
    ['Executable', h('code', null, proc.path ?? proc.name)],
    ['Started', proc.started ? new Date(proc.started).toLocaleString() : null],
    ['Uptime', formatDuration(proc.uptime_s)],
  ]), (game.warnings ?? []).map((w) => notice('warn', w))], { extra: sourceBadge('live') });
}

function versionCard(game) {
  const install = game.install;
  if (!install) {
    return card('Game version', notice('muted', 'Installation not detected.'), { extra: sourceBadge('unavailable') });
  }
  const rev = install.revision ?? {};
  let buildMatch = null;
  if (rev.install_hash && rev.running_hash && rev.from_current_run) {
    buildMatch = rev.install_hash === rev.running_hash
      ? h('span', { class: 'status-ok' }, 'Running build = installed build')
      : h('span', { class: 'bad-text' }, 'Running build differs from installed build');
  }
  return card('Game version', keyValues([
    ['Version', h('strong', null, install.version?.display ?? '—')],
    ['Raw version', install.version?.raw],
    ['Build suffix', install.version?.build_suffix ? h('code', null, install.version.build_suffix) : null],
    ['Build hash', rev.hash_short ? h('code', null, rev.hash_short) : null],
    ['Build date', rev.timestamp],
    ['Build check', buildMatch],
    ['Steam build id', install.steam?.build_id],
    ['Detected via', [install.source, install.version?.source ? ` + ${install.version.source}` : '']],
  ]), { extra: sourceBadge('live') });
}

function sessionCard(game) {
  const session = game.session;
  const userdata = game.userdata;
  return card('Session hints', [
    session ? keyValues([
      ['Last launch', session.launch_type ? humanize(session.launch_type.toLowerCase()) : null],
      ['Start date', session.start_date],
      ['Last logged game date', session.last_game_date],
      ['Last log line', session.last_log_time],
    ]) : notice('muted', 'No session information yet.'),
    userdata?.last_save ? keyValues([['Last save (continue_game.json)', userdata.last_save.title]]) : null,
    h('p', { class: 'hint' }, 'Taken from game.log, which the game writes only on some events. '
      + 'It can lag behind the live game and is not a substitute for live reading.'),
  ], { extra: sourceBadge(session ? 'live' : 'unavailable') });
}

function pathsCard(game) {
  return card('Paths', keyValues([
    ['Install', game.install?.path ? h('code', null, game.install.path) : null],
    ['User data', game.userdata?.path ? h('code', null, game.userdata.path) : null],
    ['Logs', game.userdata?.logs_dir ? h('code', null, game.userdata.logs_dir) : null],
  ]));
}

function capabilitiesCard(caps) {
  const rows = Object.entries(caps).map(([key, cap]) => ({ key, ...cap }));
  return card('Data sources', [
    table([
      { key: 'key', label: 'Area', render: (r) => humanize(r.key) },
      { key: 'source', label: 'Source', render: (r) => sourceBadge(r.source, r.note) },
      { key: 'write', label: 'Editing', render: (r) => (r.write ? 'Enabled' : 'Disabled') },
      { key: 'note', label: 'Note', cls: 'muted' },
    ], rows, { keyField: 'key' }),
  ], { cls: 'span-2' });
}

export default {
  id: 'dashboard',
  title: 'Dashboard',
  short: 'DB',
  async render(root, ctx) {
    const [status, warnings] = await Promise.all([
      ctx.api.get('/api/status'),
      ctx.api.get('/api/logs/app?limit=6&level=warning'),
    ]);
    const { game, capabilities, app } = status;

    root.append(
      viewHeader('Dashboard', `Backend ${app.version} - Python ${app.python}`),
      h('div', { class: 'grid' },
        processCard(game),
        versionCard(game),
        sessionCard(game),
        pathsCard(game),
        capabilitiesCard(capabilities),
        card('Recent warnings', warnings.data.length
          ? h('ul', { class: 'log-mini' }, warnings.data.map((e) =>
            h('li', { class: `lvl-${e.level}` }, h('time', null, e.time.slice(11)), ' ', e.message)))
          : notice('muted', 'No warnings or errors.'), { cls: 'span-2' }),
      ),
    );
    // Re-render when detection changes (game started/stopped).
    const detected = game.detected;
    return ctx.onStatus((next) => {
      if (next.game.detected !== detected) ctx.rerender();
    });
  },
};
