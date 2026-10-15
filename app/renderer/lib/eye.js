// The Overseer's eyes: the large faint eye behind every view and the small one of the logo. Their irises follow the
// mouse cursor and they blink now and then. Decoration only (aria-hidden, no pointer events); no blinking with
// "reduce motion". Following and blinking can be turned off in Options (lib/options.js).
const NS = 'http://www.w3.org/2000/svg';
const MAX_SHIFT = 46;   // how far the big iris moves from the centre (viewBox units)
const settings = { track: true, blink: true };
const eyes = [];        // {svg, iris, lid, width (viewBox), max, visible()}
let pointer = null;
let frame = 0;

/** Follow the cursor / blink on or off (Options). */
export function setEyeOptions({ track = true, blink = true } = {}) {
  settings.track = track;
  settings.blink = blink;
  if (!track) for (const e of eyes) e.iris.setAttribute('transform', 'translate(0 0)');
}

function el(tag, attrs, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

/** Iris offset (viewBox units) for a cursor at (dx, dy) from the eye's centre (viewBox units) of an eye `size` wide. */
export function irisShift(dx, dy, size, max = MAX_SHIFT) {
  const dist = Math.hypot(dx, dy);
  if (!dist || !size) return { x: 0, y: 0 };
  const reach = max * Math.min(1, dist / (size * 0.9));   // closer cursor = smaller turn
  return { x: (dx / dist) * reach, y: (dy / dist) * reach * 0.62 };   // the almond is lower than wide
}

function update() {
  frame = 0;
  if (!pointer || !settings.track) return;
  for (const e of eyes) {
    if (!e.visible()) continue;
    const r = e.svg.getBoundingClientRect();
    if (!r.width) continue;
    const scale = e.width / r.width;
    const s = irisShift((pointer.x - (r.left + r.width / 2)) * scale, (pointer.y - (r.top + r.height / 2)) * scale, e.width, e.max);
    e.iris.setAttribute('transform', `translate(${s.x.toFixed(1)} ${s.y.toFixed(1)})`);
  }
}

function track(eye) {
  eyes.push(eye);
  if (eyes.length > 1) return;
  window.addEventListener('mousemove', (e) => {
    pointer = { x: e.clientX, y: e.clientY };
    if (!frame) frame = requestAnimationFrame(update);
  }, { passive: true });
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const blink = () => {
    if (settings.blink) {
      for (const e of eyes) if (e.visible()) e.lid.classList.add('eye-blink');
      setTimeout(() => { for (const e of eyes) e.lid.classList.remove('eye-blink'); }, 260);
    }
    setTimeout(blink, 7000 + Math.random() * 9000);
  };
  setTimeout(blink, 5000);
}

/** An eye drawn around (cx, cy): almond `almond`, iris of radius r; ids made unique by `key`. */
function eyeSvg({ key, viewBox, cx, cy, r, almond, rays, frame: border, cls }) {
  const iris = el('g', { class: 'eye-iris' },
    el('circle', { cx, cy, r, fill: `url(#${key}-iris)` }),
    el('circle', { cx, cy, r, fill: 'none', stroke: '#ff5a4e', 'stroke-width': r / 32, opacity: 0.6 }),
    el('circle', { cx, cy, r: r * 0.75, fill: 'none', stroke: '#ff8a7f', 'stroke-width': r / 48, opacity: 0.35 }),
    el('circle', { cx, cy, r: r * 0.54, fill: 'none', stroke: '#ff8a7f', 'stroke-width': r / 48, opacity: 0.25 }),
    el('g', { stroke: '#ffb3ab', 'stroke-width': r / 32, opacity: 0.5 },
      el('line', { x1: cx, y1: cy - r, x2: cx, y2: cy - r * 0.81 }), el('line', { x1: cx, y1: cy + r * 0.81, x2: cx, y2: cy + r }),
      el('line', { x1: cx - r, y1: cy, x2: cx - r * 0.81, y2: cy }), el('line', { x1: cx + r * 0.81, y1: cy, x2: cx + r, y2: cy })),
    el('circle', { cx, cy, r: r * 0.35, fill: '#030303' }),
    el('circle', { cx: cx - r * 0.14, cy: cy - r * 0.14, r: r * 0.1, fill: '#f4f1ea', opacity: 0.85 }));
  const lid = el('path', { class: 'eye-lid', d: almond, fill: '#060505' });
  lid.style.transformOrigin = `${cx}px ${cy}px`;   // CSSOM: a style attribute would be blocked by the CSP
  const svg = el('svg', { viewBox, class: cls },
    el('defs', {},
      el('radialGradient', { id: `${key}-iris` },
        el('stop', { offset: '0', 'stop-color': '#ff3b30' }), el('stop', { offset: '0.5', 'stop-color': '#b3101a' }),
        el('stop', { offset: '1', 'stop-color': '#3a0206' })),
      el('clipPath', { id: `${key}-clip` }, el('path', { d: almond }))),
    ...(border ?? []),
    el('g', { stroke: '#a3121b', 'stroke-width': rays.width, 'stroke-linecap': 'round', opacity: 0.85 },
      ...rays.lines.map(([x1, y1, x2, y2]) => el('line', { x1, y1, x2, y2 }))),
    el('path', { d: almond, fill: '#0d0b0b', stroke: '#9aa3ad', 'stroke-width': rays.width * 1.15 }),
    el('g', { 'clip-path': `url(#${key}-clip)` }, iris, lid));
  return { svg, iris, lid };
}

/** The big eye behind the views, with the slogan, in `host` (the .main element). */
export function mountEye(host) {
  const { svg, iris, lid } = eyeSvg({ key: 'bg-eye', viewBox: '0 0 600 400', cx: 300, cy: 200, r: 96, cls: 'bg-eye-svg',
    almond: 'M20 200 C110 70 490 70 580 200 C490 330 110 330 20 200 Z',
    rays: { width: 7, lines: [[300, 20, 300, 56], [170, 40, 188, 74], [430, 40, 412, 74], [60, 100, 92, 122], [540, 100, 508, 122],
      [300, 344, 300, 380], [170, 360, 188, 326], [430, 360, 412, 326]] } });
  const slogan = document.createElement('div');
  slogan.className = 'bg-eye-slogan';
  slogan.textContent = 'THE OVERSEER IS WATCHING';
  const layer = document.createElement('div');
  layer.className = 'bg-eye';
  layer.setAttribute('aria-hidden', 'true');
  layer.append(svg, slogan);
  host.prepend(layer);
  track({ svg, iris, lid, width: 600, max: MAX_SHIFT, visible: () => !layer.hidden });
}

/** The logo eye (as app/renderer/assets/overseer.svg) in `host`, following the cursor too. */
export function mountLogoEye(host) {
  const plate = [
    el('rect', { x: 6, y: 6, width: 244, height: 244, rx: 40, fill: '#140607', stroke: '#b3121a', 'stroke-width': 8 })];
  const { svg, iris, lid } = eyeSvg({ key: 'logo-eye', viewBox: '0 0 256 256', cx: 128, cy: 128, r: 50, cls: 'brand-logo-svg',
    almond: 'M20 128 C60 62 196 62 236 128 C196 194 60 194 20 128 Z', frame: plate,
    rays: { width: 9, lines: [[128, 26, 128, 50], [72, 40, 84, 62], [184, 40, 172, 62], [128, 206, 128, 230],
      [72, 216, 84, 194], [184, 216, 172, 194]] } });
  svg.setAttribute('aria-hidden', 'true');
  host.replaceChildren(svg);
  track({ svg, iris, lid, width: 256, max: 30, visible: () => true });
}
