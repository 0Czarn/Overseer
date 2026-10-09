import { h, card, demoBanner, keyValues, meter, notice, scopeBadge, select, sourceBadge, table, toast, viewHeader } from '../lib/dom.js';
import { filterByText, formatAge, formatValue, freshnessInfo, humanize, stockBalance } from '../lib/format.js';
import { countryPicker } from './shared.js';

function saveLine(data) {
  const fresh = freshnessInfo(data.freshness?.category);
  return h('div', { class: `save-banner ${fresh.cls}`, role: 'note' },
    h('div', { class: 'save-banner-line' },
      sourceBadge('save'),
      h('strong', null, data.file.name),
      data.in_game_date ? h('span', null, 'In-game date ', h('b', null, data.in_game_date.text)) : null,
      h('span', { class: 'muted' }, `file written ${new Date(data.file.modified).toLocaleString()} (${formatAge(data.freshness?.age_s)})`)),
    h('div', { class: 'fresh' }, `SNAPSHOT - ${data.freshness?.label ?? fresh.short}`));
}

function saveTable(items, tag) {
  let filter = '';
  const host = h('div');
  const render = () => {
    const rows = filterByText(items, filter, ['archetype', 'archetype_name', 'variant', 'creator']);
    host.replaceChildren(table([
      { key: 'archetype_name', label: 'Equipment', render: (r) => h('span', { title: r.archetype }, r.archetype_name) },
      { key: 'variant', label: 'Variant', render: (r) => r.variant ?? h('span', { class: 'muted' }, 'base') },
      { key: 'creator', label: 'Designer', render: (r) => r.creator ?? '—' },
      { key: 'pool', label: 'Pool', render: (r) => (r.pool === 'convoys' ? 'Convoys' : 'Stockpile') },
      { key: 'amount', label: 'Amount', cls: 'num', render: (r) => formatValue(r.amount, 'integer') },
    ], rows, { keyField: 'id', empty: `No equipment in the stockpile of ${tag}` }));
  };
  render();
  return [h('input', { class: 'input', type: 'search', placeholder: 'Filter equipment…',
    onInput: (e) => { filter = e.target.value; render(); } }), host];
}

const POLL_MS = 3000;
const FINAL = ['confirmed', 'mismatch', 'expired'];

/** Add equipment: documented console command, verified by the next save (the stockpile is not read live). */
function addCard(ctx, tag, items, designs) {
  const archetypes = [...new Set(items.filter((r) => r.pool === 'stockpile').map((r) => r.archetype))].sort();
  let variant = '';
  const pick = select([{ value: '', label: 'Equipment type…' }, ...archetypes.map((a) => ({ value: a, label: a }))], '',
    (v) => { custom.value = v; variant = ''; designSel.value = ''; }, { class: 'input', 'aria-label': 'Equipment type' });
  // Own designs (tank/plane/ship designer): the game accepts the design NAME (tested in game).
  const designSel = select([{ value: '', label: designs.length ? 'or one of your designs…' : 'no own designs in this save' },
    ...designs.map((d) => ({ value: d.name, label: `${d.name} (${d.archetype}${d.obsolete ? ', obsolete' : ''}) - ${d.amount}` }))], '',
  (v) => { variant = v; if (v) { custom.value = ''; pick.value = ''; } }, { class: 'input', 'aria-label': 'Own design' });
  const custom = h('input', { class: 'input', placeholder: 'or type a key, e.g. infantry_equipment_1',
    onInput: () => { variant = ''; designSel.value = ''; } });
  const amount = h('input', { class: 'input', type: 'number', min: '1', step: '1', value: '100', 'aria-label': 'Amount' });
  const result = h('div');
  let timer = null;
  const show = (op) => {
    result.replaceChildren(card(null, [
      keyValues([['Command', h('code', null, op.command)], ['State', op.state], ['Expected', `${op.before} -> ${op.expected}`],
        op.actual !== undefined ? ['In save', `${op.actual} (${op.after_save})`] : null].filter(Boolean)),
      notice(op.state === 'confirmed' ? 'ok' : FINAL.includes(op.state) ? 'warn' : 'info', op.message),
      h('button', { class: 'btn btn-small', onClick: async () => {
        try { await navigator.clipboard.writeText(op.command); toast('Command copied', 'ok'); } catch { toast('Copy failed - type it manually', 'error'); }
      } }, 'Copy command'),
    ]));
    clearTimeout(timer);
    if (!FINAL.includes(op.state)) {
      timer = setTimeout(async () => {
        try { show(await ctx.api.get(`/api/equipment/changes/${op.id}`)); } catch (err) { toast(err.message, 'error'); }
      }, POLL_MS);
    }
  };
  const create = async () => {
    try {
      show(await ctx.api.post(`/api/equipment/${encodeURIComponent(tag)}/changes`,
        variant ? { variant, amount: Number(amount.value) } : { archetype: custom.value.trim(), amount: Number(amount.value) }));
    } catch (err) { toast(err.message, 'error'); }
  };
  const el = card('Add equipment (verified)', [
    notice('info', ['Changes the ', scopeBadge('shared'), '. Only ADDING is possible: the game command ', h('code', null, 'add_equipment'),
      ' does not remove equipment (a negative amount added 1000 in our test). The command acts on the player country. '
      + 'Enter it in the console with the game PAUSED, then save - the app compares the new save with this one.']),
    h('div', { class: 'toolbar' }, pick, designSel, custom, amount, h('button', { class: 'btn btn-small btn-primary', onClick: create }, 'Prepare command')),
    result,
  ]);
  return { el, stop: () => clearTimeout(timer) };
}

function demoTable(res, tag) {
  const editable = res.data.editable;
  return table([
    { key: 'type', label: 'Type', render: (r) => humanize(r.type) },
    { key: 'variant', label: 'Variant' },
    { key: 'stockpile', label: 'Stockpile', cls: 'num', render: (r) => formatValue(r.stockpile, 'integer') },
    { key: 'required', label: 'Required', cls: 'num', render: (r) => formatValue(r.required, 'integer') },
    { key: 'balance', label: 'Balance', render: (r) => {
      const { ratio, delta } = stockBalance(r.stockpile, r.required);
      return h('div', { class: 'balance' }, meter(ratio, delta < 0 ? 'meter-bad' : 'meter-good'),
        h('span', { class: delta < 0 ? 'bad-text' : 'good-text' }, `${delta >= 0 ? '+' : ''}${formatValue(delta, 'integer')}`));
    } },
    { key: 'actions', label: '', cls: 'actions', render: () => h('div', { class: 'btn-row' },
      h('button', { class: 'btn btn-small', disabled: !editable, 'aria-label': 'Remove' }, '−'),
      h('button', { class: 'btn btn-small', disabled: !editable, 'aria-label': 'Add' }, '+')) },
  ], res.data.items, { keyField: 'variant', empty: `No equipment data for ${tag}` });
}

export default {
  id: 'equipment',
  title: 'Equipment Manager',
  short: 'EQ',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const [res, picker] = await Promise.all([
      ctx.api.get(`/api/equipment/${encodeURIComponent(tag)}`), countryPicker(ctx)]);
    const fromSave = res.source === 'save';
    const adder = fromSave ? addCard(ctx, tag, res.data.items, res.data.designs ?? []) : null;

    root.append(...[
      viewHeader('Equipment Manager', 'Stockpiles and variants of the selected country.',
        picker, sourceBadge(res.source, res.note)),
      fromSave ? saveLine(res.data) : demoBanner(res.note),
      fromSave ? null : notice('info', 'Adding or removing equipment stays disabled until a safe method has been '
        + 'implemented and tested.'),
      card(fromSave ? `Stockpile of ${tag}` : 'Stockpile', fromSave ? saveTable(res.data.items, tag) : demoTable(res, tag)),
      adder?.el,
    ].filter(Boolean));
    return () => adder?.stop();
  },
};
