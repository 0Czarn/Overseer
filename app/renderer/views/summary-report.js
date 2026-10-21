// Game summary - campaign report (2026-10-21, user's request): one HTML file to send to the other players - the
// charts of the main values for the lines shown in the tab (countries, groups or players), the latest values, the
// players ranking, the play sessions, the notes and the campaign map of the day shown. Self-contained: charts as SVG,
// the map as a PNG inside, styles inline.
import { compact, dayText, lineChart } from '../lib/linechart.js';
import { numberLocale } from '../lib/options.js';
import { minutesText, wallText } from './summary-extra.js';

// [metric, title, cumulative chart too]
export const REPORT_METRICS = [['icall', 'IC a day (military + naval + construction)', true], ['mil', 'Military IC a day', true],
  ['fall', 'Factories', false], ['divs', 'Divisions', false], ['mpall', 'Manpower', false], ['sctl', 'States controlled', false],
  ['vp', 'Victory points controlled', false], ['tech', 'Technologies researched', false], ['lall', 'IC of equipment lost', true],
  ['lenemy', 'IC of enemy equipment destroyed', true], ['kd', 'Destroyed / lost', false], ['stab', 'Stability %', false],
  ['ws', 'War support %', false]];

/** Text safe inside HTML. */
export function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** File name of the report: "overseer-GER_1936-01-01_....html". */
export function reportName(gid) {
  return `overseer-${String(gid).replace(/[^A-Za-z0-9_.-]/g, '_')}.html`;
}

const STYLE = `body{background:#0f1115;color:#e6e2d8;font:14px "Segoe UI",system-ui,sans-serif;margin:0;padding:24px;max-width:1100px;margin:auto}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid #333;padding-bottom:4px}
.muted{color:#978e84}table{border-collapse:collapse;width:100%;margin:6px 0 12px}th,td{padding:4px 8px;border-bottom:1px solid #2a2a2a;text-align:left}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:12px}
.lc{background:#16181d;border:1px solid #2a2d33;border-radius:8px;padding:8px}.lc-title{font-weight:600;margin-bottom:4px}
.lc-svg{width:100%;height:auto}.lc-grid{stroke:#2a2d33}.lc-base{stroke:#555}.lc-axis{fill:#978e84;font-size:11px}.lc-tick{stroke:#555}
.lc-line{fill:none;stroke-width:2}.lc-legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;margin-bottom:4px}
.lc-swatch{display:inline-block;width:14px;border-top:3px solid;margin-right:4px;vertical-align:middle}.lc-swatch-dash{border-top-style:dashed}
.lc-cross,.lc-hit,.lc-dot,.lc-tip{display:none}.lc-note-line{stroke:#e0b341;stroke-width:1.5;stroke-dasharray:4 3}.lc-note-flag{fill:#e0b341}
.up{color:#4cc38a}.down{color:#ef6461}img.map{width:100%;border-radius:8px;border:1px solid #2a2d33}`;

/** The report's HTML. `parts`: {title, subtitle, series: {metric: game view}, keys, colorOf, ranking, sessions, notes,
 * map: {png, date} | null, mode}. */
export function reportHtml(parts) {
  const fmt = (v, d = 1) => (v == null ? '—' : Number(v).toLocaleString(numberLocale(), { maximumFractionDigits: d }));
  const markers = (parts.notes ?? []).map((n) => ({ t: n.t, label: n.text }));
  const charts = [];
  const latest = [];
  for (const [metric, title, cumulated] of REPORT_METRICS) {
    const view = parts.series[metric];
    if (!view) continue;
    const shown = view.series.filter((s) => parts.keys.includes(s.key) && s.values.some((v) => v != null));
    if (!shown.length) continue;
    const sets = (cum) => shown.map((s) => {
      let sum = null;
      const values = cum ? s.values.map((v, i) => {
        if (v != null) sum = (sum ?? 0) + v * (i ? view.t[i] - view.t[i - 1] : 1);
        return sum;
      }) : s.values;
      return { label: s.key, color: parts.colorOf(s.key), points: values.map((v, i) => [view.t[i], v]).filter((p) => p[1] != null) };
    });
    const format = ['stab', 'ws'].includes(metric) ? (v) => `${v.toFixed(0)}%` : metric === 'kd' ? (v) => v.toFixed(2) : compact;
    charts.push(lineChart({ title, series: sets(false), format, markers }).outerHTML);
    if (cumulated) charts.push(lineChart({ title: `${title} - total`, series: sets(true), markers }).outerHTML);
    latest.push([title, Object.fromEntries(shown.map((s) => [s.key, [...s.values].reverse().find((v) => v != null)]))]);
  }
  const keys = parts.keys;
  const table = latest.length ? `<table><thead><tr><th></th>${keys.map((k) => `<th class="num">${esc(k)}</th>`).join('')}</tr></thead><tbody>${
    latest.map(([title, vals]) => `<tr><td>${esc(title)}</td>${keys.map((k) => `<td class="num">${fmt(vals[k], 2)}</td>`).join('')}</tr>`).join('')
  }</tbody></table>` : '<p class="muted">No values recorded.</p>';
  const ranking = parts.ranking?.categories?.some((c) => c.rows.length > 1) ? `<h2>Players ranking (${esc(parts.ranking.date)})</h2><div class="grid">${
    parts.ranking.categories.map((c) => `<div><strong>${esc(c.label)}</strong><table><tbody>${c.rows.map((r) => {
      const move = r.rank != null && r.rank_before != null && r.rank !== r.rank_before
        ? `<span class="${r.rank < r.rank_before ? 'up' : 'down'}">${r.rank < r.rank_before ? '▲' : '▼'}${Math.abs(r.rank - r.rank_before)}</span>` : '';
      return `<tr><td class="num">${r.rank ?? '—'}</td><td>${esc(r.name)} <span class="muted">${esc(r.tag ?? '')}</span></td><td class="num">${fmt(r.value, c.key === 'kd' ? 2 : 0)}</td><td>${move}</td></tr>`;
    }).join('')}</tbody></table></div>`).join('')}</div>` : '';
  const sessions = parts.sessions?.sessions?.length ? `<h2>Play sessions</h2><table><thead><tr><th>Started</th><th>Game dates</th><th class="num">Real time</th>
<th class="num">Game days</th><th class="num">Stopped</th><th>Players</th></tr></thead><tbody>${[...parts.sessions.sessions].reverse().map((s) =>
    `<tr><td>${esc(wallText(s.start, new Date(0)))}</td><td>${esc(s.first)} → ${esc(s.last)}</td><td class="num">${esc(minutesText(s.minutes))}</td>
<td class="num">${fmt(s.days, 0)}</td><td class="num">${esc(minutesText(s.stopped_minutes))}</td><td>${esc(s.players.map((p) => `${p.name} (${p.tag})`).join(', '))}</td></tr>`).join('')
  }</tbody></table>` : '';
  const notes = parts.notes?.length ? `<h2>Notes</h2><table><tbody>${parts.notes.map((n) =>
    `<tr><td>${esc(dayText(n.t))}</td><td>${esc(n.text)}</td></tr>`).join('')}</tbody></table>` : '';
  const map = parts.map ? `<h2>Map on ${esc(parts.map.date)}</h2><img class="map" alt="Campaign map" src="${parts.map.png}">` : '';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(parts.title)}</title><style>${STYLE}</style></head><body>
<h1>${esc(parts.title)}</h1><p class="muted">${esc(parts.subtitle)}</p>
<h2>Latest values (${esc(parts.mode)})</h2>${table}${ranking}<h2>Charts</h2><div class="grid">${charts.join('')}</div>${map}${notes}${sessions}
<p class="muted">Made with The OVERSEER - values recorded once a game day from game memory.</p></body></html>`;
}

/** Saves the HTML as a file through the browser's download (the app's window asks where). */
export function download(name, html) {
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
