// Country Editor: resources per day (game memory while the game runs, else newest save) - produced, to market,
// sold, imported, available, used - with a small pie per resource (where the supply at home comes from / where production goes) and game icons.
import { h, notice } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { slicePath } from './overview.js';
import { MODES, TRADE_KEY, tradeSettings } from '../lib/trade-watch.js';

const SVG = 'http://www.w3.org/2000/svg';
const COLORS = { home: '#6fbf4f', market: '#d7b25a', imported: '#5aa9e6' };

const fmt = (v) => (Math.abs(v) >= 100 || Number.isInteger(v) ? String(Math.round(v)) : v.toFixed(1));

/** Shares of one resource: kept at home, given to the market, imported (sum = 100 %). */
export function shares(r) {
  const home = Math.max(0, r.produced - r.to_market);
  const parts = { home, market: Math.max(0, r.to_market), imported: Math.max(0, r.imported) };
  const total = parts.home + parts.market + parts.imported;
  return { ...parts, total };
}

function miniPie(r) {
  const s = shares(r);
  const chart = document.createElementNS(SVG, 'svg');
  chart.setAttribute('viewBox', '0 0 40 40');
  chart.setAttribute('class', 'res-pie');
  const ring = document.createElementNS(SVG, 'circle');
  Object.entries({ cx: 20, cy: 20, r: 19, class: 'pie-ring' }).forEach(([k, v]) => ring.setAttribute(k, v));
  chart.append(ring);
  let at = 0;
  for (const key of ['home', 'market', 'imported']) {
    if (!s.total || s[key] <= 0) continue;
    const share = s[key] / s.total;
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', slicePath(20, 20, 17, at, at + share));
    path.setAttribute('fill', COLORS[key]);
    path.setAttribute('class', 'pie-slice');
    chart.append(path);
    at += share;
  }
  return chart;
}

function icon(data, r) {
  if (!data.icons || !r.frame) return h('span', { class: 'res-icon res-icon-none' });
  const n = data.icon_frames || 7;
  return h('span', { class: 'res-icon', style: {
    backgroundImage: `url("${data.icons}")`, backgroundSize: `${n * 100}% 100%`,
    backgroundPosition: `${((r.frame - 1) / Math.max(1, n - 1)) * 100}% 0` } });
}

function tooltip(r) {
  const s = shares(r);
  const pct = (v) => (s.total ? `${Math.round((v / s.total) * 100)}%` : '—');
  return h('div', { class: 'spirit-tip res-tip', role: 'tooltip' },
    h('div', { class: 'spirit-tip-name' }, r.name),
    h('div', { class: 'spirit-tip-mods' },
      [['Produced (controlled states)', r.produced], ['Resources to market', -r.to_market], ['  of which sold', r.exported],
        ['Imported', r.imported], ['Available at home', r.available], ['Used by production', -r.used],
        ['Balance', r.balance]].map(([label, v]) => h('div', { class: 'hoi-line' }, h('span', null, label),
        h('span', { class: `hoi-num ${v > 0 ? 'hoi-pos' : v < 0 ? 'hoi-neg' : ''}` }, `${v > 0 ? '+' : ''}${fmt(v)}`)))),
    h('div', { class: 'spirit-tip-mods' },
      h('div', { class: 'hoi-line' }, h('span', null, h('i', { class: 'swatch', style: { background: COLORS.home } }), ' Kept at home'), h('span', null, pct(s.home))),
      h('div', { class: 'hoi-line' }, h('span', null, h('i', { class: 'swatch', style: { background: COLORS.market } }), ' To market'), h('span', null, pct(s.market))),
      h('div', { class: 'hoi-line' }, h('span', null, h('i', { class: 'swatch', style: { background: COLORS.imported } }), ' Imported'), h('span', null, pct(s.imported)))),
    r.buyers.length ? h('div', { class: 'spirit-tip-desc' }, `Sold to: ${r.buyers.map((b) => `${b.country} ${fmt(b.amount)}`).join(', ')}`) : null,
    r.sellers.length ? h('div', { class: 'spirit-tip-desc' }, `Bought from: ${r.sellers.map((b) => `${b.country} ${fmt(b.amount)}`).join(', ')}`) : null);
}

function totalsPie(rows, key, title, parts) {
  const sums = parts.map(([k, label, color]) => [label, color, rows.reduce((a, r) => a + Math.max(0, key(r, k)), 0)]);
  const total = sums.reduce((a, [, , v]) => a + v, 0);
  const chart = document.createElementNS(SVG, 'svg');
  chart.setAttribute('viewBox', '0 0 100 100');
  chart.setAttribute('class', 'pie');
  const ring = document.createElementNS(SVG, 'circle');
  Object.entries({ cx: 50, cy: 50, r: 48, class: 'pie-ring' }).forEach(([k, v]) => ring.setAttribute(k, v));
  chart.append(ring);
  let at = 0;
  for (const [, color, v] of sums) {
    if (!total || v <= 0) continue;
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', slicePath(50, 50, 44, at, at + v / total));
    path.setAttribute('fill', color);
    path.setAttribute('class', 'pie-slice');
    chart.append(path);
    at += v / total;
  }
  return h('div', { class: 'res-total' }, h('div', { class: 'res-total-title' }, title), chart,
    h('div', { class: 'pie-legend' }, sums.map(([label, color, v]) => h('div', { class: 'pie-row' },
      h('i', { class: 'swatch', style: { background: color } }),
      h('span', null, `${label} ${total ? Math.round((v / total) * 100) : 0}%`)))));
}

function saveTradeSettings(v) {
  try { localStorage.setItem(TRADE_KEY, JSON.stringify(v)); } catch { /* preference only */ }
}

/** "Buy 8 from Malaya (1 factory)" / "Cancel 16 from Romania" / "OK" for one resource of the advice. */
export function adviceText(row, names = {}) {
  const who = (t) => names[t] ?? t;
  const f = (n) => `${n} ${n === 1 ? 'factory' : 'factories'}`;
  if (row.action === 'buy') {
    const buys = row.buy.map((b) => `${fmt(b.amount)} from ${who(b.seller)} (${f(b.factories)})`).join(', ');
    return `Buy ${buys}${row.missing ? ` - still ${fmt(row.missing)} short` : ''}`;
  }
  if (row.action === 'cancel') return `Cancel ${row.cancel.map((c) => `${fmt(c.amount)} from ${who(c.seller)}`).join(', ')} - not needed`;
  if (row.action === 'short') return `${fmt(row.missing)} short - no seller or factories left`;
  return 'OK';
}

/** Trade advisor section of the resources tile: deals that keep the balance at the target, within the factory limit. */
function tradeAdvisor(ctx, tag) {
  const settings = tradeSettings();
  const out = h('div', { class: 'trade-out' }, h('span', { class: 'muted' }, 'Reading the market…'));
  const mode = h('select', { class: 'input input-small', 'aria-label': 'Balance target' },
    Object.entries(MODES).map(([k, label]) => h('option', { value: k, selected: k === settings.mode }, label)));
  const limit = h('input', { class: 'input input-small trade-limit', type: 'number', min: 10, max: 100, step: 5,
    value: settings.limit, 'aria-label': 'Factory limit for imports, percent of civilian factories' });
  let busy = false;
  async function refresh() {
    if (busy) return;
    busy = true;
    const v = { mode: mode.value, limit: Math.min(100, Math.max(10, Number(limit.value) || 25)) };
    saveTradeSettings(v);
    try {
      const res = await ctx.api.get(`/api/countries/${encodeURIComponent(tag)}/trade-advice?mode=${v.mode}&limit=${v.limit}`);
      const d = res.data;
      if (!d?.resources) {
        out.replaceChildren(notice('warn', `Trade advice unavailable: ${res.note}`));
        return;
      }
      const names = d.country_names ?? {};
      const fz = d.factories;
      out.replaceChildren(
        h('p', { class: 'muted trade-budget' }, `Import limit ${fz.limit} of ${fz.total} civilian factories · on trade now ${fz.trade_now} · `
          + `free ${fz.free} · this plan uses ${fz.planned}`),
        h('div', { class: 'trade-rows' }, d.resources.map((r) => h('div', { class: `trade-row trade-${r.action}` },
          icon(d, r), h('span', { class: 'res-name' }, r.name),
          h('span', { class: `res-num ${r.balance < 0 ? 'hoi-neg' : r.balance > 0 ? 'hoi-pos' : ''}`, title: `Balance now; target ${r.target > 0 ? '+' : ''}${r.target}` },
            `${r.balance > 0 ? '+' : ''}${fmt(r.balance)}`),
          h('span', { class: 'trade-advice', title: r.candidates.length
            ? `Best sellers: ${r.candidates.map((c) => `${names[c.seller] ?? c.seller} ${fmt(c.free)} free${c.reasons.length ? ` (${c.reasons.join(', ')})` : ''}`).join('; ')}`
            : 'No seller with at least one factory of goods on the market' }, adviceText(r, names))))),
        h('p', { class: 'muted trade-unchecked' }, `Not checked yet: ${d.unchecked.join(', ')}.`));
    } catch (err) {
      out.replaceChildren(notice('warn', `Trade advice unavailable: ${err.message}`));
    } finally {
      busy = false;
    }
  }
  mode.addEventListener('change', refresh);
  limit.addEventListener('change', refresh);
  const el = h('div', { class: 'trade-advisor' },
    h('div', { class: 'trade-head' }, h('strong', null, 'Trade advisor'),
      h('span', { class: 'muted' }, 'oil, aluminium, rubber, tungsten, steel, chromium - you make the deals in the game'),
      h('label', { class: 'trade-setting' }, 'Balance ', mode),
      h('label', { class: 'trade-setting' }, 'Factory limit ', limit, '%')),
    out);
  return { el, refresh };
}

/** Resources tile (refreshable). Returns { el, refresh, stop }. */
export function resourcesPanel(ctx, tag) {
  const advisor = tradeAdvisor(ctx, tag);
  return livePanel(ctx, {
    title: 'Resources (per day)', url: `/api/countries/${encodeURIComponent(tag)}/resources`, unavailable: 'Resources',
    liveParts: (res) => (res.data?.resources_source === 'live' ? ['resources, trade deals'] : []),
    render(body, res) {
      const d = res.data;
      if (!d?.resources) {
        body.replaceChildren(notice('warn', `Resources unavailable: ${res.note}`));
        return;
      }
      const head = h('div', { class: 'res-row res-head' }, h('span', null, ''), h('span', null, 'Resource'),
        ...['Produced', 'To market', 'Imported', 'Available', 'Used', 'Balance'].map((t) => h('span', { class: 'res-num' }, t)),
        h('span', null, ''));
      const rows = d.resources.map((r) => h('div', { class: 'res-row spirit', tabindex: 0 },
        icon(d, r), h('span', { class: 'res-name' }, r.name),
        h('span', { class: 'res-num' }, fmt(r.produced)),
        h('span', { class: 'res-num res-market' }, r.to_market ? `${fmt(r.to_market)}${r.exported ? ` (${fmt(r.exported)} sold)` : ''}` : '0'),
        h('span', { class: 'res-num res-import' }, fmt(r.imported)),
        h('span', { class: 'res-num' }, fmt(r.available)),
        h('span', { class: 'res-num' }, fmt(r.used)),
        h('span', { class: `res-num ${r.balance < 0 ? 'hoi-neg' : r.balance > 0 ? 'hoi-pos' : ''}` }, `${r.balance > 0 ? '+' : ''}${fmt(r.balance)}`),
        miniPie(r), tooltip(r)));
      body.replaceChildren(h('div', { class: 'res-body' },
        h('div', { class: 'res-table' }, head, rows),
        h('div', { class: 'res-totals' },
          totalsPie(d.resources, (r, k) => (k === 'home' ? r.produced - r.to_market : r.to_market), 'Production',
            [['home', 'Kept at home', COLORS.home], ['market', 'To market', COLORS.market]]),
          totalsPie(d.resources, (r, k) => (k === 'home' ? r.available - r.imported : r.imported), 'Available supply',
            [['home', 'Own production', COLORS.home], ['imported', 'Imported', COLORS.imported]]))),
      advisor.el);
      advisor.refresh();   // the market moved with the resources
    },
  });
}
