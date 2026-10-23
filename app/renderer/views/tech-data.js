// Technical data of a country (Game Tools, folded at the bottom): the raw values of the newest save with the save
// field each one comes from, and the diagnostic political power change test (console command + verification by a
// newer save). Moved from the Country Editor (2026-10-15) - they are for checking the readers, not for playing.
import { h, card, notice, scopeBadge, sourceBadge, toast } from '../lib/dom.js';
import { formatAge, formatValue, freshnessInfo } from '../lib/format.js';
import { ppCommand, verifyChange } from '../lib/verify.js';
import { countryPicker } from './shared.js';

const STATUS_NOTE = { read: null, absent: 'not in save', unmapped: 'not mapped yet' };

function snapshotBanner(data) {
  const fresh = freshnessInfo(data.freshness?.category);
  return h('div', { class: `save-banner ${fresh.cls}`, role: 'note' },
    h('div', { class: 'save-banner-line' },
      sourceBadge('save'),
      h('strong', null, data.file.name),
      data.in_game_date ? h('span', null, 'In-game date ', h('b', null, data.in_game_date.text)) : null,
      h('span', { class: 'muted' }, `file written ${new Date(data.file.modified).toLocaleString()} (${formatAge(data.freshness?.age_s)})`),
      h('span', { class: 'muted' }, `read ${new Date(data.read_at).toLocaleTimeString()}`)),
    h('div', { class: 'fresh' }, `SNAPSHOT - ${data.freshness?.label ?? fresh.short}`),
    data.is_latest === false ? h('div', { class: 'warn-text' }, 'Not the newest save') : null);
}

function valueTile(field, entry) {
  const status = entry?.status ?? 'unmapped';
  return h('div', { class: `stat-tile ${status === 'read' ? '' : 'stat-missing'}`, title: entry?.note ?? '' },
    h('div', { class: 'stat-label' }, field.label),
    h('div', { class: 'stat-value' }, status === 'read' ? formatValue(entry.value, field.unit) : '—'),
    h('div', { class: 'stat-source muted' }, status === 'read' ? h('code', null, `${entry.path} = ${entry.raw}`) : STATUS_NOTE[status] ?? status));
}

/** Diagnostic PP change: console command + independent verification through a newer save. */
function ppTestCard(ctx, tag, data) {
  const isPlayer = data.player_tag === tag;
  const key = `ppBaseline:${tag}`;
  const result = h('div');
  const baselineLine = h('div', { class: 'muted' });
  const deltaInput = h('input', { class: 'input input-small', type: 'number', value: '10', step: '1', 'aria-label': 'PP change' });
  const commandCode = h('code', { class: 'cmd' });
  const pp = data.values.political_power;

  const snapshot = (d) => ({ value: d.values.political_power?.value, file: d.file.name, mtime: d.file.mtime,
    date: d.in_game_date?.text });
  const renderBaseline = () => {
    const b = ctx.state[key];
    baselineLine.textContent = b ? `Baseline: PP ${b.value} in ${b.file} (in-game ${b.date})` : 'No baseline recorded.';
  };
  const renderCommand = () => { commandCode.textContent = ppCommand(deltaInput.value) ?? '(enter a non-zero amount)'; };
  deltaInput.addEventListener('input', renderCommand);
  renderCommand();
  renderBaseline();

  const verify = async () => {
    const res = await ctx.api.get(`/api/countries/${encodeURIComponent(tag)}/save-values`);
    if (res.source !== 'save') {
      result.replaceChildren(notice('warn', res.note ?? 'Newest save is not readable.'));
      return;
    }
    const outcome = verifyChange(ctx.state[key], snapshot(res.data), deltaInput.value);
    const kind = { pass: 'info', fail: 'warn', inconclusive: 'warn', waiting: 'muted' }[outcome.status];
    result.replaceChildren(notice(kind, `${outcome.status.toUpperCase()}: ${outcome.message}`));
    if (outcome.status !== 'waiting') ctx.api.log(outcome.status === 'pass' ? 'info' : 'warning', `PP change test ${tag}: ${outcome.message}`);
  };

  return card('Political Power - change test (diagnostic)', [
    notice('info', ['Changes the ', scopeBadge('shared'), ' of the game. The debugger does not apply the change itself: it '
      + 'prepares a documented console command and then verifies the result independently by reading a newer save.']),
    isPlayer ? null : notice('warn', `Console commands affect the player's country (${data.player_tag ?? 'unknown'} in this save), not ${tag}. `
      + 'Select the player country to run this test.'),
    h('ol', { class: 'steps' },
      h('li', null, 'Pause the game. Click ', h('b', null, 'Record baseline'), ` (uses PP ${pp?.value ?? '—'} from ${data.file.name}).`),
      h('li', null, 'In the game console type: ', commandCode, ' ', h('button', { class: 'btn btn-small', onClick: async () => {
        const cmd = ppCommand(deltaInput.value);
        if (!cmd) return;
        try { await navigator.clipboard.writeText(cmd); toast('Command copied', 'ok'); } catch { toast('Copy failed - type it manually', 'error'); }
      } }, 'Copy')),
      h('li', null, 'Then type ', h('code', { class: 'cmd' }, 'savegame'), ' (game started with -force_text_save).'),
      h('li', null, 'Click ', h('b', null, 'Verify'), '.')),
    h('div', { class: 'toolbar' },
      h('label', { class: 'field-inline' }, h('span', null, 'Amount'), deltaInput),
      h('button', { class: 'btn btn-small', disabled: !isPlayer || pp?.status !== 'read', onClick: () => {
        ctx.state[key] = snapshot(data);
        renderBaseline();
        result.replaceChildren();
        ctx.api.log('info', `PP change test ${tag}: baseline ${pp.value} from ${data.file.name}`);
      } }, 'Record baseline'),
      h('button', { class: 'btn btn-small btn-primary', disabled: !isPlayer, onClick: verify }, 'Verify')),
    baselineLine, result,
  ], { cls: 'card-shared' });
}

/** A folded tile: its body is built (and its data read) the first time it is opened. */
function foldTile(title, build) {
  const body = h('div', { class: 'tech-body' });
  let built = false;
  return h('details', { class: 'tech-tile', ontoggle: async (e) => {
    if (!e.target.open || built) return;
    built = true;
    body.replaceChildren(h('p', { class: 'muted' }, 'Reading…'));
    try {
      body.replaceChildren(...[await build()].flat().filter(Boolean));   // replaceChildren would print a null
    } catch (err) {
      built = false;
      body.replaceChildren(notice('warn', `Not available: ${err.message}`));
    }
  } }, h('summary', null, title), body);
}

/** The "Technical data" card of Game Tools for the selected country. */
export async function techDataSection(ctx) {
  const tag = ctx.state.selectedCountry;
  const picker = await countryPicker(ctx);
  let saved = null;
  const load = async () => {
    saved ??= await Promise.all([ctx.api.get(`/api/countries/${encodeURIComponent(tag)}`),
      ctx.api.get(`/api/countries/${encodeURIComponent(tag)}/save-values`)]);
    return saved;
  };
  return card('Technical data', [
    h('p', { class: 'muted' }, `Raw values and diagnostics of ${tag} - for checking what the app reads.`),
    foldTile(`Save values - ${tag}`, async () => {
      const [meta, res] = await load();
      const fields = meta.data.fields;
      if (res.source === 'save') {
        return [snapshotBanner(res.data), h('div', { class: 'tile-grid' }, fields.map((f) => valueTile(f, res.data.values[f.key])))];
      }
      return notice('warn', `Save values unavailable: ${res.note ?? 'no save'}${res.data?.file ? ` (${res.data.file})` : ''}`);
    }),
    foldTile('Political Power - change test (diagnostic)', async () => {
      const [, res] = await load();
      return res.source === 'save' ? ppTestCard(ctx, tag, res.data)
        : notice('warn', `Needs a readable save: ${res.note ?? 'no save'}`);
    }),
  ], { extra: picker, cls: 'tech-data' });
}
