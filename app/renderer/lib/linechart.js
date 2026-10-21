// Line chart over game days (SVG): recessive grid and axes, 2px lines, a legend, crosshair + tooltip with every
// series' value on the hovered day (in every chart of the same hoverSync).
// Series: { label, color, dash, points: [[day, value], ...] } (days ascending). Markers: [{ t, label }] - the user's
// notes as dashed vertical lines, their text in the tooltip near them; onPick(day): a click on the plot (a note on that day).
import { h } from './dom.js';
import { numberLocale } from './options.js';

const SVG = 'http://www.w3.org/2000/svg';
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];   // the game has no leap years
const W = 860;
const H = 260;
const PAD = { left: 56, right: 14, top: 10, bottom: 26 };

function svg(tag, attrs = {}) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

/** "1941.11.02" of a day number (year * 365 + day of the year). */
export function dayText(t) {
  let year = Math.floor(t / 365);
  let day = t - year * 365;
  let month = 0;
  while (day >= MONTH_DAYS[month]) day -= MONTH_DAYS[month++];
  return `${year}.${String(month + 1).padStart(2, '0')}.${String(day + 1).padStart(2, '0')}`;
}

/** "12.3K" / "2.72M" / "950" */
export function compact(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return `${+(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${+(v / 1e3).toFixed(1)}K`;
  return `${+v.toFixed(a < 10 ? 1 : 0)}`;
}

/** About five round ticks from 0 to max. */
export function niceTicks(max) {
  if (!(max > 0)) return [0, 1];
  const raw = max / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(+v.toFixed(10));
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
  return out;
}

/** Day ticks on month starts, spaced so about six fit. */
export function dayTicks(t0, t1) {
  const span = Math.max(1, t1 - t0);
  const months = [1, 2, 3, 6, 12, 24].find((m) => span / (m * 30.4) <= 7) ?? 48;
  const out = [];
  let year = Math.floor(t0 / 365);
  let month = 0;
  for (;;) {
    const t = year * 365 + MONTH_DAYS.slice(0, month).reduce((a, b) => a + b, 0);
    if (t > t1) break;
    if (t >= t0 && (year * 12 + month) % months === 0) out.push(t);
    month += 1;
    if (month === 12) { month = 0; year += 1; }
  }
  return out;
}

function valueAt(points, t) {
  // the value holds until the next sample (days skipped at high speed)
  let lo = 0;
  let hi = points.length - 1;
  if (!points.length || t < points[0][0]) return null;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (points[mid][0] <= t) lo = mid; else hi = mid - 1;
  }
  return points[lo][1];
}

/** Shared hover of several charts: the day under the mouse in one shows in all (pass the same object as `sync`). */
export function hoverSync() {
  return { charts: [] };
}

export function lineChart({ title, series, format = compact, sync = null, markers = [], onPick = null }) {
  const all = series.flatMap((s) => s.points);
  if (!all.length) return h('div', { class: 'lc' }, h('div', { class: 'lc-title' }, title), h('p', { class: 'muted' }, 'No data yet.'));
  const t0 = Math.min(...all.map((p) => p[0]));
  const t1 = Math.max(...all.map((p) => p[0]));
  const yTicks = niceTicks(Math.max(...all.map((p) => p[1])));
  const yMax = yTicks[yTicks.length - 1];
  const x = (t) => PAD.left + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD.left - PAD.right);
  const y = (v) => H - PAD.bottom - (v / yMax) * (H - PAD.top - PAD.bottom);

  const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'lc-svg', role: 'img', 'aria-label': title });
  for (const v of yTicks) {
    root.append(svg('line', { x1: PAD.left, x2: W - PAD.right, y1: y(v), y2: y(v), class: 'lc-grid' }));
    const label = svg('text', { x: PAD.left - 6, y: y(v) + 4, class: 'lc-axis', 'text-anchor': 'end' });
    label.textContent = format(v);
    root.append(label);
  }
  for (const t of dayTicks(t0, t1)) {
    const anchor = x(t) > W - PAD.right - 24 ? 'end' : x(t) < PAD.left + 24 ? 'start' : 'middle';   // keep edge labels inside
    const label = svg('text', { x: x(t), y: H - 8, class: 'lc-axis', 'text-anchor': anchor });
    label.textContent = dayText(t).slice(0, 7);
    root.append(svg('line', { x1: x(t), x2: x(t), y1: H - PAD.bottom, y2: H - PAD.bottom + 4, class: 'lc-tick' }), label);
  }
  root.append(svg('line', { x1: PAD.left, x2: W - PAD.right, y1: y(0), y2: y(0), class: 'lc-base' }));
  for (const s of series) {
    if (!s.points.length) continue;
    const d = s.points.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
    root.append(svg('path', { d, class: 'lc-line', stroke: s.color, ...(s.dash ? { 'stroke-dasharray': '6 4' } : {}) }));
    if (s.points.length === 1) root.append(svg('circle', { cx: x(s.points[0][0]), cy: y(s.points[0][1]), r: 4, fill: s.color, class: 'lc-dot' }));
  }
  for (const m of markers) {
    if (m.t < t0 || m.t > t1) continue;
    const g = svg('g', { class: 'lc-note' });
    g.append(svg('line', { x1: x(m.t), x2: x(m.t), y1: PAD.top, y2: H - PAD.bottom, class: 'lc-note-line' }),
      svg('path', { d: `M${x(m.t)},${PAD.top}l7,4l-7,4z`, class: 'lc-note-flag' }));
    root.append(g);
  }
  const cross = svg('line', { y1: PAD.top, y2: H - PAD.bottom, class: 'lc-cross', visibility: 'hidden' });
  const dots = series.map((s) => svg('circle', { r: 4, fill: s.color, class: 'lc-dot', visibility: 'hidden' }));
  const hit = svg('rect', { x: PAD.left, y: PAD.top, width: W - PAD.left - PAD.right, height: H - PAD.top - PAD.bottom, class: 'lc-hit' });
  root.append(cross, ...dots, hit);

  const tip = h('div', { class: 'lc-tip', hidden: true });
  const box = h('div', { class: 'lc-plot' }, root, tip);
  const showAt = (day) => {   // crosshair, dots and the values of every series on `day`
    const t = Math.min(t1, Math.max(t0, day));
    const r = root.getBoundingClientRect();
    cross.setAttribute('x1', x(t)); cross.setAttribute('x2', x(t)); cross.setAttribute('visibility', 'visible');
    const rows = series.map((s, i) => {
      const v = valueAt(s.points, t);
      if (v == null) { dots[i].setAttribute('visibility', 'hidden'); return null; }
      dots[i].setAttribute('cx', x(t)); dots[i].setAttribute('cy', y(v)); dots[i].setAttribute('visibility', 'visible');
      return { s, v };
    }).filter(Boolean).sort((a, b) => b.v - a.v);
    const near = Math.max(1, (t1 - t0) / 80);   // notes within about a pixel column or two of the cursor
    const notes = markers.filter((m) => Math.abs(m.t - t) <= near);
    tip.replaceChildren(h('div', { class: 'lc-tip-date' }, dayText(t)),
      ...notes.map((m) => h('div', { class: 'lc-tip-note' }, `✎ ${dayText(m.t)}: ${m.label}`)),
      ...rows.map(({ s, v }) => h('div', { class: 'lc-tip-row' },
        h('span', { class: `lc-swatch ${s.dash ? 'lc-swatch-dash' : ''}`, style: { borderColor: s.color } }),
        h('span', { class: 'lc-tip-label' }, s.label), h('span', { class: 'lc-tip-value' }, format === compact
          ? v.toLocaleString(numberLocale(), { maximumFractionDigits: 1 }) : format(v)))));
    tip.hidden = false;
    const left = (x(t) / W) * r.width;
    tip.style.left = left + 12 + tip.offsetWidth > r.width ? `${Math.max(0, left - tip.offsetWidth - 12)}px` : `${left + 12}px`;
  };
  const hide = () => {
    tip.hidden = true;
    cross.setAttribute('visibility', 'hidden');
    dots.forEach((d) => d.setAttribute('visibility', 'hidden'));
  };
  sync?.charts.push({ showAt, hide });
  const dayAt = (ev) => {
    const r = root.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    return Math.min(t1, Math.max(t0, Math.round(t0 + ((px - PAD.left) / (W - PAD.left - PAD.right)) * (t1 - t0))));
  };
  hit.addEventListener('mousemove', (ev) => {
    const t = dayAt(ev);
    if (sync) sync.charts.forEach((c) => c.showAt(t)); else showAt(t);
  });
  if (onPick) {
    hit.classList.add('lc-hit-pick');
    hit.addEventListener('click', (ev) => onPick(dayAt(ev)));
  }
  hit.addEventListener('mouseleave', () => (sync ? sync.charts.forEach((c) => c.hide()) : hide()));
  // a series without any value stays in the legend, marked, so a chosen country never silently disappears
  const legend = series.length > 1 ? h('div', { class: 'lc-legend' }, series.map((s) => h('span', {
    class: `lc-legend-item ${s.points.length ? '' : 'lc-legend-empty'}`, title: s.points.length ? null : 'No value recorded' },
    h('span', { class: `lc-swatch ${s.dash ? 'lc-swatch-dash' : ''}`, style: { borderColor: s.color } }), s.label,
    s.points.length ? null : h('span', { class: 'lc-legend-note' }, 'no data')))) : null;
  return h('div', { class: 'lc' }, h('div', { class: 'lc-title' }, title), legend, box);
}
