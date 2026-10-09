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

const fmtInt = (v) => formatValue(Math.round(v ?? 0), 'integer');

/** One row per equipment archetype (need / held / stockpile / shortfall) - click to show or hide its variants. */
function groupTable(groups, tag, ctx) {
  let filter = '';
  const open = new Set(JSON.parse(sessionStorage.getItem('hoi4dbg.eqOpen') ?? '[]'));
  const host = h('div');
  const toggle = (a) => {
    if (open.has(a)) open.delete(a); else open.add(a);
    try { sessionStorage.setItem('hoi4dbg.eqOpen', JSON.stringify([...open])); } catch { /* convenience only */ }
    render();
  };
  const head = h('thead', null, h('tr', null, ['Equipment', 'Needed', 'In divisions', 'Stockpile', 'Deficit'].map(
    (t, i) => h('th', { class: i ? 'num' : '' }, t))));
  function render() {
    const f = filter.toLowerCase();
    const rows = [];
    for (const g of groups) {
      const variants = g.variants.filter((v) => !f || `${v.archetype} ${v.archetype_name} ${v.variant ?? ''}`.toLowerCase().includes(f));
      if (f && !variants.length && !`${g.name} ${g.archetype}`.toLowerCase().includes(f)) continue;
      const isOpen = open.has(g.archetype);
      const canOpen = g.variants.length > 0;
      rows.push(h('tr', { class: `eq-group${g.shortfall > 0 ? ' eq-deficit' : ''}`, onClick: canOpen ? () => toggle(g.archetype) : null },
        h('td', null, h('span', { class: 'eq-caret' }, canOpen ? (isOpen ? '▼' : '▶') : ''), h('b', { title: g.archetype }, g.name),
          canOpen ? h('span', { class: 'muted' }, ` (${g.variants.length})`) : null),
        h('td', { class: 'num' }, g.need ? fmtInt(g.need) : '—'),
        h('td', { class: 'num' }, g.need ? fmtInt(g.held) : '—'),
        h('td', { class: 'num' }, fmtInt(g.stockpile)),
        h('td', { class: `num ${g.shortfall > 0 ? 'bad-text' : 'good-text'}` }, g.shortfall > 0 ? `−${fmtInt(g.shortfall)}` : (g.need ? 'OK' : ''))));
      if (isOpen) {
        for (const v of (f ? variants : g.variants)) {
          rows.push(h('tr', { class: 'eq-variant' },
            h('td', null, h('span', { class: 'eq-indent' }), v.variant ?? h('span', { class: 'muted' }, `${v.archetype_name} (base)`),
              h('span', { class: 'muted' }, ` · ${v.archetype}${v.creator ? ` · ${v.creator}` : ''}${v.obsolete ? ' · obsolete' : ''}`)),
            h('td', null), h('td', null), h('td', { class: 'num' }, fmtInt(v.amount)), h('td', null)));
        }
      }
    }
    host.replaceChildren(h('div', { class: 'table-wrap' }, h('table', { class: 'table eq-table' }, head,
      h('tbody', null, rows.length ? rows : h('tr', null, h('td', { colspan: '5', class: 'muted' }, `No equipment for ${tag}`))))));
  }
  render();
  return [h('p', { class: 'hint' }, 'Deficit = equipment missing in fielded divisions minus the stockpile (estimate: '
    + 'divisions in training and production lines are not counted). Click a row to show its variants.'),
  h('input', { class: 'input', type: 'search', placeholder: 'Filter equipment or variant…',
    onInput: (e) => { filter = e.target.value; render(); } }), host];
}

const DIRECT_PREF = 'hoi4dbg.directWrite'; // shared with the Country Editor
const directEnabled = () => { try { return localStorage.getItem(DIRECT_PREF) === '1'; } catch { return false; } };

/** Stockpile read from game memory every few seconds; with direct writes enabled each variant can be set
 *  (LOCAL memory write, single player only - the backend refuses it in multiplayer). */
function liveStockpileCard(ctx, tag) {
  const host = h('div', null, h('p', { class: 'muted' }, 'Reading game memory…'));
  const badge = h('span');
  const result = h('div');
  const open = new Set(JSON.parse(sessionStorage.getItem('hoi4dbg.eqLiveOpen') ?? '[]'));
  let entries = [];
  let timer = null;
  let stopped = false;
  let editing = false;
  const toggleBox = h('input', { type: 'checkbox', checked: directEnabled(), onChange: (e) => {
    try { localStorage.setItem(DIRECT_PREF, e.target.checked ? '1' : '0'); } catch { /* preference only */ }
    render();
  } });
  const setAmount = async (entry, input) => {
    try {
      const res = await ctx.api.post('/api/live/stockpile', { tag, id: entry.id, amount: Number(input.value),
        expected_before: entry.amount, confirm_local: true });
      result.replaceChildren(notice('info', [h('b', null, 'LOCAL WRITE: '), `${res.name || entry.type_name || res.id} `
        + `${fmtInt(res.before)} -> ${fmtInt(res.after)} (read back from memory). This client only.`]));
      ctx.api.log('warning', `Local stockpile write ${res.tag} ${res.id}: ${res.before} -> ${res.after}`);
      editing = false;
      tick();
    } catch (err) { result.replaceChildren(notice('warn', err.message)); }
  };
  function render() {
    const groups = new Map();
    for (const e of entries) {
      const key = e.archetype ?? e.type ?? `#${e.id}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    }
    const allowed = directEnabled();
    const rows = [];
    for (const [key, list] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const total = list.reduce((n, e) => n + e.amount, 0);
      const isOpen = open.has(key);
      rows.push(h('tr', { class: 'eq-group', onClick: () => {
        if (isOpen) open.delete(key); else open.add(key);
        try { sessionStorage.setItem('hoi4dbg.eqLiveOpen', JSON.stringify([...open])); } catch { /* convenience */ }
        render();
      } }, h('td', null, h('span', { class: 'eq-caret' }, isOpen ? '▼' : '▶'), h('b', null, list[0].type_name && list.length === 1
        ? list[0].type_name : key.replace(/_/g, ' ')), h('span', { class: 'muted' }, ` (${list.length})`)),
      h('td', { class: 'num' }, fmtInt(total)), h('td', null)));
      if (!isOpen) continue;
      for (const e of list) {
        const input = h('input', { class: 'input input-small', type: 'number', min: '0', step: '1', value: String(Math.round(e.amount)),
          'aria-label': 'New amount', onFocus: () => { editing = true; }, onBlur: () => { editing = false; } });
        rows.push(h('tr', { class: 'eq-variant' },
          h('td', null, h('span', { class: 'eq-indent' }), e.name || h('span', { class: 'muted' }, `${e.type_name ?? e.type ?? e.id} (base)`),
            h('span', { class: 'muted' }, ` · ${e.type ?? ''} · id ${e.id}`)),
          h('td', { class: 'num' }, fmtInt(e.amount)),
          h('td', null, allowed ? h('span', { class: 'btn-row' }, input,
            h('button', { class: 'btn btn-small btn-primary', onClick: () => setAmount(e, input) }, 'Set')) : null)));
      }
    }
    host.replaceChildren(
      h('label', { class: 'switch' }, toggleBox, h('span', null, 'Enable direct memory writes (LOCAL, single player only)')),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table eq-table' },
        h('thead', null, h('tr', null, h('th', null, 'Equipment'), h('th', { class: 'num' }, 'Live amount'), h('th', null, allowed ? 'Set to' : ''))),
        h('tbody', null, rows.length ? rows : h('tr', null, h('td', { colspan: '3', class: 'muted' }, 'Empty stockpile'))))),
      result);
  }
  async function tick() {
    if (stopped) return;
    clearTimeout(timer);
    if (!editing) {
      try {
        entries = (await ctx.api.get(`/api/live/stockpile?tag=${encodeURIComponent(tag)}`)).data.entries;
        badge.replaceChildren(h('span', { class: 'badge badge-live' }, 'LIVE'));
        render();
      } catch (err) {
        badge.replaceChildren(h('span', { class: 'badge badge-na' }, 'NO LIVE DATA'));
        host.replaceChildren(notice('muted', `Live stockpile unavailable: ${err.message}`));
      }
    }
    timer = setTimeout(tick, 3000);
  }
  tick();
  return {
    el: card(`Live stockpile of ${tag} (game memory)`, [
      notice('warn', ['Setting an amount writes game memory directly - ', scopeBadge('local'), ' only. Single player: in '
        + 'multiplayer it would exist on your client only, so the app refuses it there. Only variants that already have a '
        + 'stockpile entry can be set (add a new one once with "Add equipment" below).']),
      host], { extra: badge }),
    stop: () => { stopped = true; clearTimeout(timer); },
  };
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
    const liveStock = fromSave ? liveStockpileCard(ctx, tag) : null;

    root.append(...[
      viewHeader('Equipment Manager', 'Stockpiles and variants of the selected country.',
        picker, sourceBadge(res.source, res.note)),
      fromSave ? saveLine(res.data) : demoBanner(res.note),
      fromSave ? null : notice('info', 'Adding or removing equipment stays disabled until a safe method has been '
        + 'implemented and tested.'),
      card(fromSave ? `Equipment of ${tag}` : 'Stockpile', fromSave ? groupTable(res.data.groups ?? [], tag, ctx) : demoTable(res, tag)),
      liveStock?.el,
      adder?.el,
    ].filter(Boolean));
    return () => { adder?.stop(); liveStock?.stop(); };
  },
};
