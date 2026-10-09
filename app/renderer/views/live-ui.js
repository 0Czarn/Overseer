// Live Political Power read from game memory (read-only) + calibration controls.
// A number is shown only when the backend confirmed the memory location for the running process.
import { h, card, keyValues, notice, scopeBadge, toast } from '../lib/dom.js';
import { PERCENT_FIELDS, classifyLive, formatLiveValue, toValueUnits } from '../lib/live.js';

const FIELD = 'political_power';
const FIELD_LABELS = {
  political_power: 'Political Power', stability: 'Stability (base value)', war_support: 'War Support (base value)',
  command_power: 'Command Power', fuel: 'Fuel', manpower: 'Manpower',
  army_experience: 'Army XP', navy_experience: 'Navy XP', air_experience: 'Air XP',
};
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

const OP_DONE = ['confirmed', 'mismatch', 'expired', 'error', 'cancelled'];
const OP_KIND = { confirmed: 'info', mismatch: 'warn', expired: 'warn', error: 'warn', cancelled: 'muted' };

/** Verified PP change: the app prepares a documented console command, the tester enters it, and the
 *  result is verified by re-reading the calibrated memory location. The app never writes game memory. */
function changeSection(ctx, enabled) {
  // The backend refuses fields without a confirmed location or a verified command unit, with the reason.
  const fieldSel = h('select', { class: 'input input-small', 'aria-label': 'Field' },
    Object.entries(FIELD_LABELS).map(([k, label]) => h('option', { value: k }, label)));
  const mode = h('select', { class: 'input input-small', 'aria-label': 'Change mode' },
    h('option', { value: 'delta' }, 'Add'), h('option', { value: 'target' }, 'Set to'));
  const amount = h('input', { class: 'input input-small', type: 'number', step: 'any', value: '10', 'aria-label': 'Amount' });
  const unit = h('span', { class: 'muted' });
  // Stability / war support are typed in percent like in the game (Set to 80 = 80%); the backend works in 0..1.
  const syncUnit = () => { unit.textContent = PERCENT_FIELDS.has(fieldSel.value) ? '%' : ''; };
  fieldSel.addEventListener('change', syncUnit);
  syncUnit();
  const pct = (field, v) => (PERCENT_FIELDS.has(field) ? formatLiveValue(v, field) : v);
  const result = h('div');
  let pollTimer = null;
  let current = null;

  const show = (op) => {
    current = op;
    const copy = h('button', { class: 'btn btn-small', onClick: async () => {
      try { await navigator.clipboard.writeText(op.command); toast('Command copied', 'ok'); } catch { toast('Copy failed - type it manually', 'error'); }
    } }, 'Copy');
    const lines = [
      h('div', null, 'Command: ', h('code', { class: 'cmd' }, op.command), ' ', OP_DONE.includes(op.state) ? null : copy),
      h('div', { class: 'muted' }, `${FIELD_LABELS[op.field] ?? op.field} ${op.tag}: ${pct(op.field, op.before)} -> expected ${pct(op.field, op.expected)}${op.actual !== undefined ? `, memory ${pct(op.field, op.actual)}` : ''}`),
    ];
    if (OP_DONE.includes(op.state)) {
      result.replaceChildren(notice(OP_KIND[op.state], [h('b', null, op.state.toUpperCase()), ': ', op.message]), ...lines);
    } else {
      result.replaceChildren(notice('info', op.message), ...lines,
        h('button', { class: 'btn btn-small', onClick: async () => show(await ctx.api.post(`/api/live/operations/${op.id}/cancel`)) }, 'Cancel'));
    }
  };
  const poll = async () => {
    if (!current || OP_DONE.includes(current.state)) return;
    try { show(await ctx.api.get(`/api/live/operations/${current.id}`)); } catch (err) { toast(err.message, 'error'); }
    if (!OP_DONE.includes(current.state)) pollTimer = setTimeout(poll, 1000);
  };
  const create = async () => {
    clearTimeout(pollTimer);
    try {
      show(await ctx.api.post('/api/live/operations', { field: fieldSel.value, mode: mode.value,
        amount: toValueUnits(Number(amount.value), fieldSel.value) }));
      ctx.api.log('info', `Live change prepared (${fieldSel.value}): ${current.command} (expected ${current.expected})`);
      pollTimer = setTimeout(poll, 1000);
    } catch (err) {
      result.replaceChildren(notice('warn', err.message));
    }
  };
  const el = h('div', { class: 'live-cal' },
    h('h3', null, 'Change (verified)'),
    notice('info', ['Changes the ', scopeBadge('shared'), '. The game must be PAUSED and the player country must be the one shown. '
      + 'The app prepares a documented console command (', h('code', null, 'pp'), ', ', h('code', null, 'add_stability'), ', ', h('code', null, 'cp'), ' …); you enter it in the game console; '
      + 'the result is verified by re-reading game memory. Game memory is never written.']),
    h('div', { class: 'toolbar live-change' }, fieldSel, mode, amount, unit,
      h('button', { class: 'btn btn-small btn-primary', disabled: !enabled, onClick: create }, 'Prepare command')),
    enabled ? null : h('p', { class: 'muted' }, 'Available once the live value is confirmed (state LIVE).'),
    result);
  return { el, stop: () => clearTimeout(pollTimer) };
}

/** Compact tiles for the other fields: a number only when that field is confirmed (LIVE). */
function otherFields(last) {
  const now = Date.now() / 1000;
  const tiles = Object.keys(FIELD_LABELS).filter((f) => f !== FIELD).map((f) => {
    const entry = last.all?.[f];
    const known = entry && (entry.status === 'live' || entry.code !== 'not_calibrated');
    if (!known) return null;
    const info = classifyLive({ status: last.status, value: entry, fetchedAt: entry.status === 'live' ? now : NaN, now });
    return h('div', { class: `stat-tile live-mini live-${info.state}`, title: info.message },
      h('div', { class: 'stat-label' }, FIELD_LABELS[f]),
      h('div', { class: 'stat-value' }, info.value !== undefined ? formatLiveValue(info.value, f) : '—'),
      h('div', { class: 'stat-source' }, info.label));
  }).filter(Boolean);
  return tiles.length ? h('div', { class: 'tile-grid live-grid' }, tiles) : null;
}

const DIRECT_FIELDS = ['stability', 'war_support', 'political_power', 'command_power', 'fuel',
  'army_experience', 'navy_experience', 'air_experience'];
const DIRECT_PREF = 'hoi4dbg.directWrite';

function directEnabled() {
  try { return localStorage.getItem(DIRECT_PREF) === '1'; } catch { return false; }
}

/** LOCAL direct memory write (opt-in, single player): sets the value immediately, no console. The backend
 *  refuses it with more than one human player (it would desynchronise a multiplayer game). */
function directSection(ctx, tag, getValues) {
  const fieldSel = h('select', { class: 'input input-small', 'aria-label': 'Field' },
    DIRECT_FIELDS.map((k) => h('option', { value: k }, FIELD_LABELS[k])));
  const value = h('input', { class: 'input input-small', type: 'number', step: 'any', 'aria-label': 'New value' });
  const unit = h('span', { class: 'muted' });
  const result = h('div');
  const fill = () => {
    const v = getValues()?.[fieldSel.value];
    unit.textContent = PERCENT_FIELDS.has(fieldSel.value) ? '%' : '';
    if (v?.status === 'live') value.value = String(PERCENT_FIELDS.has(fieldSel.value) ? +(v.value * 100).toFixed(2) : +v.value.toFixed(3));
  };
  fieldSel.addEventListener('change', fill);
  const toggle = h('input', { type: 'checkbox', checked: directEnabled(), onChange: (e) => {
    try { localStorage.setItem(DIRECT_PREF, e.target.checked ? '1' : '0'); } catch { /* preference only */ }
    setBtn.disabled = !e.target.checked;
  } });
  const set = async () => {
    const field = fieldSel.value;
    const before = getValues()?.[field];
    try {
      const res = await ctx.api.post('/api/live/write', {
        field, tag, value: toValueUnits(Number(value.value), field), confirm_local: true,
        expected_before: before?.status === 'live' ? before.value : undefined,
      });
      result.replaceChildren(notice('info', [h('b', null, 'LOCAL WRITE: '),
        `${FIELD_LABELS[field]} ${res.tag}: ${formatLiveValue(res.before, field)} -> ${formatLiveValue(res.after, field)} `
        + '(read back from memory). This client only - not a shared game change.']));
      ctx.api.log('warning', `Local memory write ${res.tag} ${field}: ${res.before} -> ${res.after}`);
    } catch (err) {
      result.replaceChildren(notice('warn', err.message));
    }
  };
  const setBtn = h('button', { class: 'btn btn-small btn-primary', disabled: !directEnabled(), onClick: set }, 'Set now');
  setTimeout(fill, 0);
  return h('div', { class: 'live-cal' },
    h('h3', null, 'Set directly (memory write)'),
    notice('warn', ['Writes the value straight into game memory - ', scopeBadge('local'), ' only. Single player: in a '
      + 'multiplayer game it would exist on your client only (desync), so the app refuses it there. Use "Change (verified)" '
      + 'for changes that go through the game.']),
    h('label', { class: 'switch' }, toggle, h('span', null, 'Enable direct memory writes')),
    h('div', { class: 'toolbar live-change' }, fieldSel, value, unit, setBtn),
    result);
}

/** Returns { el, stop }. `withCalibration` adds the calibration controls, `withChange` the verified change;
 *  `tag` reads that country (game country table) instead of the player country. */
export function liveCard(ctx, { withCalibration = true, withChange = false, withDirect = false, cls, tag } = {}) {
  const badgeHost = h('span');
  const body = h('div', { class: 'card-body-inner' }, h('p', { class: 'muted' }, 'Connecting to live reader…'));
  let stopped = false;
  let timer = null;
  let last = { status: null, value: null, fetchedAt: NaN };
  let change = null;
  const changeHost = h('div');
  const directHost = withDirect ? directSection(ctx, tag, () => last.all) : null;

  const render = (error) => {
    const now = Date.now() / 1000;
    const info = classifyLive({ status: last.status, value: last.value, error, fetchedAt: last.fetchedAt, now });
    const proc = last.status?.process;
    badgeHost.replaceChildren(stateBadge(info));
    body.replaceChildren(...[
      h('div', { class: `stat-tile live-tile live-${info.state}` },
        h('div', { class: 'stat-label' }, `Political Power${last.value?.tag ? ` - ${last.value.tag}` : ''}`),
        h('div', { class: 'stat-value' }, info.value !== undefined ? formatLiveValue(info.value) : '—'),
        h('div', { class: 'stat-source' }, info.message)),
      otherFields(last),
      keyValues([
        ['Status', info.label],
        ['Game process', proc ? `PID ${proc.pid}` : 'not running'],
        ['Game version', proc?.version],
        ['Last update', Number.isFinite(last.fetchedAt) && info.value !== undefined
          ? new Date(last.fetchedAt * 1000).toLocaleTimeString() : null],
      ]),
      withCalibration && last.status ? calibrationSection(ctx, last.status, tick) : null,
      withChange ? changeHost : null, directHost].filter(Boolean)); // replaceChildren would print "null"
    // Keep the change form (and a running operation) across refreshes; rebuild it only when availability changes.
    if (withChange && (change === null || change.enabled !== (info.state === 'live'))) {
      change?.stop();
      change = { ...changeSection(ctx, info.state === 'live'), enabled: info.state === 'live' };
      changeHost.replaceChildren(change.el);
    }
  };

  async function tick() {
    if (stopped) return;
    clearTimeout(timer);
    try {
      const [status, values] = await Promise.all([ctx.api.get('/api/live'), ctx.api.get(`/api/live/values${tag ? `?tag=${encodeURIComponent(tag)}` : ''}`)]);
      const value = values.data?.[FIELD] ?? null;
      last = { status, value, all: values.data ?? {}, fetchedAt: value?.status === 'live' ? Date.now() / 1000 : last.fetchedAt };
      if (!stopped) render(null);
    } catch (err) {
      if (!stopped) render({ code: err.code, message: err.message });
    }
    if (!stopped) timer = setTimeout(tick, POLL_MS);
  }
  tick();
  return {
    el: card(withDirect ? 'Live game memory' : 'Live game memory (read-only)', body, { extra: badgeHost, cls }),
    stop: () => { stopped = true; clearTimeout(timer); change?.stop(); },
  };
}
