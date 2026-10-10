// UI pieces for data read from save files. Every save-derived panel shows: source (SAVE),
// file, in-game date, when the file was written, and how that relates to the running game.
import { h, keyValues, notice, select, sourceBadge, table } from '../lib/dom.js';
import { formatAge, formatBytes, freshnessInfo } from '../lib/format.js';
import { tagChip } from './shared.js';

const VALIDATION_TEXT = {
  pending: ['muted', 'Checking whole-file structure…'],
  complete: ['good-text', 'Whole file structurally valid'],
  ambiguous: ['warn-text', 'Structure ambiguous'],
  invalid: ['bad-text', 'File damaged or incomplete'],
  error: ['bad-text', 'Validation failed'],
  not_run: ['muted', 'Not checked'],
};

/** Multiplayer / single player of a save header (flag in binary saves; player count in text saves). */
export function sessionType(header) {
  if (!header || header.multiplayer === undefined) return null;
  const count = header.players?.length ?? 0;
  if (header.multiplayer) {
    return h('span', { class: 'session-mp', title: header.multiplayer_basis === 'flag'
      ? 'The save carries the multiplayer flag (inferred field)' : `${count} players listed (text save)` },
    `Multiplayer (${count} player${count === 1 ? '' : 's'})`);
  }
  return h('span', { class: 'session-sp', title: count > 1
    ? `No multiplayer flag, but ${count} players are listed - probably an earlier multiplayer game continued alone`
    : 'One player, no multiplayer flag' }, count > 1 ? `Single player (lists ${count} players)` : 'Single player');
}

export function saveBanner(analysis) {
  const fresh = freshnessInfo(analysis.freshness?.category);
  const header = analysis.header;
  const written = new Date(analysis.file.modified).toLocaleString();
  const [vcls, vtext] = VALIDATION_TEXT[analysis.validation?.status] ?? VALIDATION_TEXT.not_run;
  const versionCheck = analysis.version_check;
  return h('div', { class: `save-banner ${fresh.cls}`, role: 'note' },
    h('div', { class: 'save-banner-line' },
      sourceBadge('save'),
      h('strong', null, analysis.file.name),
      header?.date ? h('span', null, 'In-game date ', h('b', null, header.date.text)) : null,
      sessionType(header),
      h('span', { class: 'muted' }, `written ${written} (${formatAge(analysis.freshness?.age_s)})`)),
    h('div', { class: 'fresh' }, analysis.freshness?.label ?? fresh.short),
    h('div', { class: 'save-banner-line' },
      h('span', { class: vcls, title: analysis.validation?.message ?? '' }, vtext),
      versionCheck?.match === false ? h('span', { class: 'warn-text' }, `Saved with ${versionCheck.save}; running ${versionCheck.running}`) : null,
      analysis.is_latest === false ? h('span', { class: 'warn-text' }, 'Not the newest save') : null));
}

export function saveError(analysis) {
  if (!analysis?.error) return null;
  return notice('warn', `Could not read ${analysis.file?.name ?? 'save'}: ${analysis.error.message} [${analysis.error.code}]`);
}

export function playersTable(header) {
  const players = header?.players ?? [];
  return table([
    { key: 'tag', label: 'Country', render: (p) => tagChip(p.tag, p.tag === header.player_tag ? 'tag-chip-warn' : '') },
    { key: 'name', label: 'Player', render: (p) => p.name ?? h('span', { class: 'muted' }, 'unknown') },
    { key: 'role', label: '', render: (p) => h('span', { class: 'muted' }, [
      p.tag === header.player_tag && p.country_leader !== false ? 'saved this file' : null,
      p.country_leader === false ? 'co-op (not country leader)' : null].filter(Boolean).join(', ')) },
  ], players, { keyField: 'tag', empty: 'No players listed in this save' });
}

export function headerDetails(analysis) {
  const header = analysis.header;
  if (!header) return null;
  return keyValues([
    ['Session', sessionType(header)],
    ['Saving country', header.player_tag ? tagChip(header.player_tag) : null],
    ['Ideology', header.ideology ? [header.ideology, h('span', { class: 'muted' }, ' (inferred field)')] : null],
    ['Difficulty', header.difficulty ? [header.difficulty, h('span', { class: 'muted' }, ' (inferred field)')] : null],
    ['Game version', header.version],
    ['File size', formatBytes(analysis.file.size)],
    ['Format', analysis.format ? `${analysis.format}, value width ${analysis.float_width}` : null],
  ]);
}

export function modsList(header) {
  if (!header?.mods) return null;
  return h('details', null, h('summary', null, `Enabled mods (${header.mods.length})`),
    header.mods.length ? h('div', { class: 'chip-list' }, header.mods.map((m) => h('span', { class: 'chip' }, m)))
      : h('p', { class: 'muted' }, 'None'));
}

export function saveSelect(saves, current, onChange) {
  return select(saves.map((s, i) => ({ value: s.name, label: `${i === 0 ? '★ ' : ''}${s.name} - ${new Date(s.modified).toLocaleString()}` })),
    current, onChange, { class: 'input', 'aria-label': 'Save file' });
}

/** Polls the analysis endpoint until background validation is done. Returns a stop function. */
export function pollAnalysis(ctx, name, onUpdate, intervalMs = 1500) {
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    const query = name ? `?name=${encodeURIComponent(name)}` : '';
    try {
      const res = await ctx.api.get(`/api/saves/analysis${query}`);
      if (stopped) return;
      onUpdate(res);
      if (res.data?.validation?.status === 'pending' || res.data?.error?.code === 'in_progress') setTimeout(tick, intervalMs);
    } catch (err) {
      if (!stopped) onUpdate({ source: 'unavailable', data: null, note: err.message });
    }
  };
  tick();
  return () => { stopped = true; };
}
