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
    { key: 'role', label: '', render: (p) => (p.tag === header.player_tag ? h('span', { class: 'muted' }, 'saved this file') : '') },
  ], players, { keyField: 'tag', empty: 'No players listed in this save' });
}

export function headerDetails(analysis) {
  const header = analysis.header;
  if (!header) return null;
  return keyValues([
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
