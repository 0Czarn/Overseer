// Country Editor: live values of the selected country in a compact, HOI4-like panel.
// Stability / war support show what the game shows (base + every modifier, like the in-game tooltip),
// with the base value editable directly (local memory write, single player only).
import { h, notice, scopeBadge, toast } from '../lib/dom.js';
import { dataKey, refreshControl } from '../lib/refresh.js';
import { statIcon } from '../lib/icons.js';
import { FIELD_LABELS, changeSection, directEnabled } from './live-ui.js';

const STRIP = ['political_power', 'command_power', 'fuel', 'army_experience', 'navy_experience', 'air_experience'];
const GAUGES = { stability: 'Stability', war_support: 'War Support' };
const KIND_LABEL = { party: 'Politics', idea: 'National spirit / law', leader: 'Country leader', advisor: 'Advisor', dynamic: 'Dynamic modifier',
  unknown: 'Not identified by the app: the game’s own modifier sum (game memory) minus the modifiers the app knows' };

const pct = (v, sign = false) => (Number.isFinite(v)
  ? `${sign && v > 0 ? '+' : ''}${(v * 100).toFixed(1).replace(/\.0$/, '')}%` : '—');
const clamp01 = (v) => Math.min(1, Math.max(0, v));

function stripValue(field, entry) {
  if (entry?.status !== 'live') return '—';
  const v = entry.value;
  if (field === 'fuel') return Math.round(v).toLocaleString();
  return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(field === 'political_power' ? 2 : 1);
}

const DIRECT_PREF = 'hoi4dbg.directWrite';

/** LOCAL memory write of one field of `tag`, read back by the backend. Returns true on success. */
async function writeField(ctx, tag, field, value, before) {
  if (!directEnabled()) {
    toast('Turn on "Edit live values" first', 'error');
    return false;
  }
  try {
    const res = await ctx.api.post('/api/live/write', { field, tag, value, confirm_local: true,
      expected_before: Number.isFinite(before) ? before : undefined });
    toast(`${FIELD_LABELS[field]} ${res.tag}: ${res.before} -> ${res.after} (local write)`, 'ok');
    ctx.api.log('warning', `Local memory write ${res.tag} ${field}: ${res.before} -> ${res.after}`);
    return true;
  } catch (err) {
    toast(err.message, 'error');
    return false;
  }
}

/** Editable chip of the top strip (PP, CP, fuel, XP). Built once; update() keeps the input untouched. */
function chip(ctx, tag, field) {
  const value = h('span', { class: 'hoi-chip-value' }, '—');
  const input = h('input', { class: 'hoi-chip-input', type: 'number', step: 'any', 'aria-label': `New ${FIELD_LABELS[field]}` });
  let current = null;
  const set = async () => {
    const v = Number(input.value);
    if (input.value === '' || !Number.isFinite(v)) {
      toast('Enter a number', 'error');
      return;
    }
    if (await writeField(ctx, tag, field, v, current)) input.value = '';
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') set(); });
  const el = h('div', { class: 'hoi-chip' },
    h('span', { class: 'hoi-chip-label' }, statIcon(field), FIELD_LABELS[field]), value,
    h('div', { class: 'hoi-chip-edit' }, input, h('button', { class: 'hoi-chip-btn', type: 'button', onClick: set, title: 'Set now (local memory write)' }, 'Set')));
  return {
    el,
    update(entry) {
      current = entry?.status === 'live' ? entry.value : null;
      value.textContent = stripValue(field, entry);
      el.title = entry?.status === 'live' ? '' : entry?.message ?? '';
      input.placeholder = current === null ? '' : String(+current.toFixed(field === 'fuel' ? 0 : 2));
    },
  };
}

// Difference between what the game shows and base + known modifiers, per country and field. It is kept as an
// extra modifier ("UNKNOWN"), so later base changes are still followed live. Stored in this browser only.
const UNKNOWN_PREF = 'hoi4dbg.unknownModifier';

function loadUnknown(tag, field) {
  try { return JSON.parse(localStorage.getItem(UNKNOWN_PREF) || '{}')[`${tag}:${field}`] ?? null; } catch { return null; }
}

function saveUnknown(tag, field, entry) {
  try {
    const all = JSON.parse(localStorage.getItem(UNKNOWN_PREF) || '{}');
    if (entry) all[`${tag}:${field}`] = entry; else delete all[`${tag}:${field}`];
    localStorage.setItem(UNKNOWN_PREF, JSON.stringify(all));
  } catch { /* preference only */ }
}

/** One gauge (stability or war support). Built once; update() only changes text, so the input keeps focus. */
function gauge(ctx, tag, field) {
  const big = h('div', { class: 'hoi-gauge-value' }, '—');
  const fill = h('div', { class: 'hoi-bar-fill' });
  const baseCell = h('span', { class: 'hoi-num' }, '—');
  const baseSrc = h('span', { class: 'hoi-src' });
  const lines = h('div', { class: 'hoi-lines' });
  const totalCell = h('span', { class: 'hoi-num' }, '—');
  const clampNote = h('div', { class: 'hoi-note' });
  const input = h('input', { class: 'input input-small hoi-input', type: 'number', step: '1', min: '0', max: '100',
    'aria-label': `New base ${GAUGES[field]} in percent` });
  const unknownLine = h('div', { class: 'hoi-line hoi-line-unknown' });
  let matchRow = null;
  const gameInput = h('input', { class: 'input input-small hoi-input', type: 'number', step: '0.1', min: '0', max: '100',
    'aria-label': `${GAUGES[field]} shown in game, percent` });
  let base = null;
  let breakdown = null;
  let filled = false;
  let unknown = loadUnknown(tag, field);   // { value, at }

  const match = () => {
    const shown = Number(gameInput.value) / 100;
    if (gameInput.value === '' || !Number.isFinite(shown) || shown < 0 || shown > 1) {
      toast('Enter the value the game shows (0-100 %)', 'error');
      return;
    }
    if (!Number.isFinite(base) || breakdown?.modifiers === undefined) {
      toast('Base value and modifiers must be loaded first', 'error');
      return;
    }
    const diff = +(shown - (base + breakdown.modifiers)).toFixed(4);
    unknown = Math.abs(diff) < 0.0005 ? null : { value: diff, at: new Date().toISOString() };
    saveUnknown(tag, field, unknown);
    gameInput.value = '';
    toast(unknown ? `UNKNOWN ${pct(diff, true)} added to ${GAUGES[field]}` : 'Already matches the game - nothing unknown', 'ok');
    render();
  };
  gameInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') match(); });

  const set = async () => {
    const value = Number(input.value) / 100;
    if (input.value === '' || !Number.isFinite(value) || value < 0 || value > 1) {
      toast('Base value must be 0-100 %', 'error');
      return;
    }
    await writeField(ctx, tag, field, value, base);
  };

  const el = h('div', { class: `hoi-gauge hoi-${field}` },
    h('div', { class: 'hoi-gauge-head' }, h('span', { class: 'hoi-title' }, GAUGES[field]), big),
    h('div', { class: 'hoi-bar' }, fill),
    h('div', { class: 'hoi-tooltip' },
      h('div', { class: 'hoi-line hoi-line-base' }, h('span', null, 'Base value ', baseSrc), baseCell),
      lines,
      unknownLine,
      h('div', { class: 'hoi-line hoi-line-total' }, h('span', null, 'Total'), totalCell),
      clampNote),
    matchRow = h('div', { class: 'hoi-match', title: 'Type what the game shows: the difference to the known modifiers is kept as "UNKNOWN"' },
      h('span', null, 'In game'), gameInput, h('span', { class: 'muted' }, '%'),
      h('button', { class: 'btn btn-small', onClick: match }, 'Match')),
    h('div', { class: 'hoi-edit' }, h('span', null, 'Set base'), input, h('span', { class: 'muted' }, '%'),
      h('button', { class: 'btn btn-small btn-primary', onClick: set }, 'Set')));

  const render = () => {
    // game memory gives the game's own sum: the UNKNOWN part comes with it, the manual match is not needed
    const fromGame = breakdown?.modifiers_source === 'live';
    const manual = fromGame ? null : unknown;
    const mods = breakdown ? breakdown.modifiers + (manual?.value ?? 0) : null;
    matchRow.hidden = fromGame;
    unknownLine.hidden = !manual;
    if (manual) {
      unknownLine.replaceChildren(
        h('span', { title: `Not identified by the app; matched with the game ${new Date(unknown.at).toLocaleString()}` },
          'UNKNOWN ', h('button', { class: 'hoi-x', type: 'button', title: 'Remove', onClick: () => {
            unknown = null;
            saveUnknown(tag, field, null);
            render();
          } }, '✕')),
        h('span', { class: `hoi-num ${unknown.value > 0 ? 'hoi-pos' : 'hoi-neg'}` }, pct(unknown.value, true)));
    }
    const total = Number.isFinite(base) && mods !== null ? clamp01(base + mods) : null;
    big.textContent = pct(total ?? base);
    big.title = total === null ? 'Modifiers not loaded - base value only' : '';
    fill.style.width = `${clamp01(total ?? base ?? 0) * 100}%`;
    baseCell.textContent = pct(base);
    totalCell.textContent = pct(total);
    clampNote.textContent = total !== null && (base + mods > 1 || base + mods < 0)
      ? `Capped at ${pct(total)} (uncapped ${pct(base + mods)})` : '';
    if (!filled && Number.isFinite(base)) {
      input.value = String(+(base * 100).toFixed(1));
      filled = true;
    }
  };

  return {
    el,
    setBase(value, source) {
      base = value;
      baseSrc.textContent = source === 'live' ? '(live)' : source ? `(${source})` : '';
      render();
    },
    setBreakdown(b) {
      breakdown = b;
      lines.replaceChildren(...(b?.parts?.length ? b.parts.map((p) => h('div', { class: `hoi-line${p.kind === 'unknown' ? ' hoi-line-unknown' : ''}`, title: KIND_LABEL[p.kind] ?? p.kind },
        h('span', null, p.name), h('span', { class: `hoi-num ${p.value > 0 ? 'hoi-pos' : 'hoi-neg'}` }, pct(p.value, true))))
        : [h('div', { class: 'hoi-line muted' }, b ? 'No modifiers' : 'Modifiers not loaded')]));
      render();
    },
  };
}

/** Returns { el, stop }. */
export function countryLivePanel(ctx, tag, { isPlayer = false } = {}) {
  const status = h('span', { class: 'hoi-status' }, 'connecting…');
  const chips = Object.fromEntries(STRIP.map((f) => [f, chip(ctx, tag, f)]));
  const strip = h('div', { class: 'hoi-strip' }, Object.values(chips).map((c) => c.el));
  const editToggle = h('label', { class: 'hoi-toggle', title: 'LOCAL memory writes, single player only (refused in multiplayer)' },
    h('input', { type: 'checkbox', checked: directEnabled(), onChange: (e) => {
      try { localStorage.setItem(DIRECT_PREF, e.target.checked ? '1' : '0'); } catch { /* preference only */ }
      panel.classList.toggle('hoi-editing', e.target.checked);
    } }), h('span', null, 'Edit live values'));
  const gauges = { stability: gauge(ctx, tag, 'stability'), war_support: gauge(ctx, tag, 'war_support') };
  const sourceLine = h('div', { class: 'hoi-source' });
  let values = {};
  let stopped = false;
  let busy = false;
  let lastBreakdown = null;
  let change = null;
  const changeHost = h('div');

  const loadBreakdown = async () => {
    if (!sourceLine.textContent) sourceLine.textContent = 'Reading modifiers from the newest save…';
    try {
      const res = await ctx.api.get(`/api/countries/${encodeURIComponent(tag)}/stability`);
      if (stopped) return;
      if (!res.data?.stability) {
        sourceLine.replaceChildren(notice('warn', `Modifiers unavailable: ${res.note}`));
        Object.values(gauges).forEach((g) => g.setBreakdown(null));
        return;
      }
      const d = res.data;
      const key = dataKey(d);
      if (key === lastBreakdown) return;   // unchanged: keep open tooltips as they are
      lastBreakdown = key;
      Object.entries(gauges).forEach(([f, g]) => {
        g.setBreakdown(d[f]);
        if (values[f]?.status !== 'live') g.setBase(d[f].base, 'save');
      });
      sourceLine.replaceChildren(
        h('span', null, d.ideas_source === 'live'
          ? `Spirits, laws${d.advisors_source === 'live' ? ', advisors' : ''}${d.doctrines_source === 'live' ? ', doctrines' : ''}${d.penalties_source === 'live' ? ', bombing, casualties' : ''}${d.wars_source === 'live' ? ', wars' : ''} LIVE; other modifiers from ` : 'Modifiers from ',
          d.file.name, d.in_game_date ? ` (${d.in_game_date.text})` : '',
          d.freshness?.category === 'current_session' ? '' : ' - an older session: save again if the leader changed. '),
        h('span', { class: 'muted' }, ` Not read yet: ${d.not_read.join(', ')}. `),
        d.save_mismatch ? notice('warn', d.save_mismatch) : '');
    } catch (err) {
      if (!stopped) sourceLine.replaceChildren(notice('warn', `Modifiers unavailable: ${err.message}`));
    }
  };

  const render = (error) => {
    STRIP.forEach((f) => chips[f].update(values[f]));
    Object.entries(gauges).forEach(([f, g]) => { if (values[f]?.status === 'live') g.setBase(values[f].value, 'live'); });
    status.textContent = error ? error : `game memory · read ${new Date().toLocaleTimeString()}`;
    status.className = `hoi-status ${error ? 'hoi-status-off' : 'hoi-status-on'}`;
    const live = values.political_power?.status === 'live';
    if (isPlayer && (change === null || change.enabled !== live)) {
      change?.stop();
      change = { ...changeSection(ctx, live), enabled: live };
      changeHost.replaceChildren(change.el);
    }
  };

  const tick = async () => {
    try {
      const res = await ctx.api.get(`/api/live/values?tag=${encodeURIComponent(tag)}`);
      values = res.data ?? {};
      if (!stopped) render(Object.values(values).some((v) => v?.status === 'live') ? null : 'game memory not readable');
    } catch (err) {
      if (!stopped) render(err.message);
    }
  };

  const run = async (force) => {   // Live: every LIVE_MS; On refresh: ↻ button
    if (busy || stopped) return;
    busy = true;
    control.button.classList.add('hoi-refresh-busy');
    if (force) lastBreakdown = null;
    try {
      await Promise.all([tick(), loadBreakdown()]);
    } finally {
      busy = false;
      control.button.classList.remove('hoi-refresh-busy');
    }
  };
  const control = refreshControl('Live game memory', 'Live game memory', run);

  const panel = h('section', { class: `hoi-panel ${directEnabled() ? 'hoi-editing' : ''}` },
    h('div', { class: 'hoi-head' }, h('span', { class: 'hoi-head-title' }, 'Live game memory'),
      h('span', { class: 'hoi-head-right' }, editToggle, scopeBadge('local'), status, control.el)),
    strip,
    h('div', { class: 'hoi-gauges' }, gauges.stability.el, gauges.war_support.el),
    sourceLine,
    isPlayer ? h('details', { class: 'hoi-advanced' }, h('summary', null, 'Advanced: verified change through the game console'),
      changeHost) : null);
  const el = panel;
  run(true);
  return { el, stop: () => { stopped = true; control.stop(); change?.stop(); } };
}
