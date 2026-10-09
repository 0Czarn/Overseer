// Live Political Power read from game memory (read-only) + calibration controls.
// A number is shown only when the backend confirmed the memory location for the running process.
import { h, card, keyValues, notice, toast } from '../lib/dom.js';
import { classifyLive, formatLiveValue } from '../lib/live.js';

const FIELD = 'political_power';
const POLL_MS = 2000;
const BADGE_CLS = { live: 'badge-live', stale: 'badge-demo', unverified: 'badge-demo' };

function stateBadge(info) {
  return h('span', { class: `badge ${BADGE_CLS[info.state] ?? 'badge-na'}`, title: info.message }, info.label);
}

function calibrationSection(ctx, status, refresh) {
  const cal = status?.calibrations?.[FIELD];
  const job = status?.job?.field === FIELD ? status.job : null;
  const invalidated = status?.invalidated?.[FIELD];
  const act = async (body) => {
    try {
      await ctx.api.post('/api/live/calibration', { field: FIELD, ...body });
    } catch (err) {
      toast(err.message, 'error');
    }
    refresh();
  };
  const running = job?.state === 'running';
  return h('div', { class: 'live-cal' },
    h('h3', null, 'Calibration (read-only memory scan)'),
    invalidated && !cal ? notice('warn', invalidated.message) : null,
    running ? notice('info', `Scanning game memory… ${Math.round((job.progress ?? 0) * 100)}%`) : null,
    job?.state === 'error' ? notice('warn', `Scan failed: ${job.error}`) : null,
    cal ? keyValues([
      ['State', h('b', null, cal.state)],
      ['Result', cal.message],
      ['Evidence', h('ol', { class: 'steps' }, cal.steps.map((s) => h('li', null, `${s.value} - ${s.source}`)))],
      cal.width_note ? ['Note', cal.width_note] : null,
    ]) : h('p', { class: 'muted' }, 'Not calibrated for this game process.'),
    h('ol', { class: 'steps muted' },
      h('li', null, 'Single player, game PAUSED for the whole calibration, started with -force_text_save.'),
      h('li', null, 'Console: ', h('code', { class: 'cmd' }, 'savegame'), ', then ', h('b', null, 'Start'), '.'),
      h('li', null, 'Console: ', h('code', { class: 'cmd' }, 'pp 5'), ', then ', h('b', null, 'Refine (command)'),
        '. Repeat with another amount until the state is ', h('b', null, 'confirmed'), '.')),
    h('div', { class: 'toolbar' },
      h('button', { class: 'btn btn-small btn-primary', disabled: running, onClick: () => act({ action: 'start' }) }, 'Start'),
      h('button', { class: 'btn btn-small', disabled: running || !cal, onClick: () => act({ action: 'refine', source: 'command' }) }, 'Refine (command)'),
      h('button', { class: 'btn btn-small', disabled: running || !cal, onClick: () => act({ action: 'refine', source: 'save' }) }, 'Refine (save)'),
      h('button', { class: 'btn btn-small', disabled: running || !cal, onClick: () => act({ action: 'reset' }) }, 'Reset')));
}

/** Returns { el, stop }. `withCalibration` adds the calibration controls. */
export function liveCard(ctx, { withCalibration = true, cls } = {}) {
  const badgeHost = h('span');
  const body = h('div', { class: 'card-body-inner' }, h('p', { class: 'muted' }, 'Connecting to live reader…'));
  let stopped = false;
  let timer = null;
  let last = { status: null, value: null, fetchedAt: NaN };

  const render = (error) => {
    const now = Date.now() / 1000;
    const info = classifyLive({ status: last.status, value: last.value, error, fetchedAt: last.fetchedAt, now });
    const proc = last.status?.process;
    badgeHost.replaceChildren(stateBadge(info));
    body.replaceChildren(
      h('div', { class: `stat-tile live-tile live-${info.state}` },
        h('div', { class: 'stat-label' }, `Political Power${last.value?.tag ? ` - ${last.value.tag}` : ''}`),
        h('div', { class: 'stat-value' }, info.value !== undefined ? formatLiveValue(info.value) : '—'),
        h('div', { class: 'stat-source' }, info.message)),
      keyValues([
        ['Status', info.label],
        ['Game process', proc ? `PID ${proc.pid}` : 'not running'],
        ['Game version', proc?.version],
        ['Last update', Number.isFinite(last.fetchedAt) && info.value !== undefined
          ? new Date(last.fetchedAt * 1000).toLocaleTimeString() : null],
      ]),
      withCalibration && last.status ? calibrationSection(ctx, last.status, tick) : null);
  };

  async function tick() {
    if (stopped) return;
    clearTimeout(timer);
    try {
      const [status, values] = await Promise.all([ctx.api.get('/api/live'), ctx.api.get('/api/live/values')]);
      const value = values.data?.[FIELD] ?? null;
      last = { status, value, fetchedAt: value?.status === 'live' ? Date.now() / 1000 : last.fetchedAt };
      if (!stopped) render(null);
    } catch (err) {
      if (!stopped) render({ code: err.code, message: err.message });
    }
    if (!stopped) timer = setTimeout(tick, POLL_MS);
  }
  tick();
  return {
    el: card('Live game memory (read-only)', body, { extra: badgeHost, cls }),
    stop: () => { stopped = true; clearTimeout(timer); },
  };
}
