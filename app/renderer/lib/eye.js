// The Overseer's eye behind every view: a large faint eye whose iris follows the mouse cursor, and blinks now and
// then. Decoration only (aria-hidden, no pointer events); no blinking with "reduce motion".
const NS = 'http://www.w3.org/2000/svg';
const MAX_SHIFT = 46;   // how far the iris moves from the centre (viewBox units)

function el(tag, attrs, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

/** Iris offset (viewBox units) for a cursor at (dx, dy) pixels from the eye's centre of an eye `size` pixels wide. */
export function irisShift(dx, dy, size) {
  const dist = Math.hypot(dx, dy);
  if (!dist || !size) return { x: 0, y: 0 };
  const reach = MAX_SHIFT * Math.min(1, dist / (size * 0.9));   // closer cursor = smaller turn
  return { x: (dx / dist) * reach, y: (dy / dist) * reach * 0.62 };   // the almond is lower than wide
}

export function mountEye(host) {
  const almond = 'M20 200 C110 70 490 70 580 200 C490 330 110 330 20 200 Z';
  const iris = el('g', { class: 'eye-iris' },
    el('circle', { cx: 300, cy: 200, r: 96, fill: 'url(#eye-iris)' }),
    el('circle', { cx: 300, cy: 200, r: 96, fill: 'none', stroke: '#ff5a4e', 'stroke-width': 3, opacity: 0.6 }),
    el('circle', { cx: 300, cy: 200, r: 72, fill: 'none', stroke: '#ff8a7f', 'stroke-width': 2, opacity: 0.35 }),
    el('circle', { cx: 300, cy: 200, r: 52, fill: 'none', stroke: '#ff8a7f', 'stroke-width': 2, opacity: 0.25 }),
    el('g', { stroke: '#ffb3ab', 'stroke-width': 3, opacity: 0.5 },
      el('line', { x1: 300, y1: 104, x2: 300, y2: 122 }), el('line', { x1: 300, y1: 278, x2: 300, y2: 296 }),
      el('line', { x1: 204, y1: 200, x2: 222, y2: 200 }), el('line', { x1: 378, y1: 200, x2: 396, y2: 200 })),
    el('circle', { cx: 300, cy: 200, r: 34, fill: '#030303' }),
    el('circle', { cx: 287, cy: 187, r: 9, fill: '#f4f1ea', opacity: 0.85 }));
  const lid = el('path', { class: 'eye-lid', d: almond, fill: '#060505' });
  const svg = el('svg', { viewBox: '0 0 600 400', class: 'bg-eye-svg' },
    el('defs', {},
      el('radialGradient', { id: 'eye-iris' },
        el('stop', { offset: '0', 'stop-color': '#ff3b30' }), el('stop', { offset: '0.5', 'stop-color': '#b3101a' }),
        el('stop', { offset: '1', 'stop-color': '#3a0206' })),
      el('clipPath', { id: 'eye-clip' }, el('path', { d: almond }))),
    el('g', { stroke: '#a3121b', 'stroke-width': 7, 'stroke-linecap': 'round', opacity: 0.8 },
      ...[[300, 20, 300, 56], [170, 40, 188, 74], [430, 40, 412, 74], [60, 100, 92, 122], [540, 100, 508, 122],
        [300, 344, 300, 380], [170, 360, 188, 326], [430, 360, 412, 326]]
        .map(([x1, y1, x2, y2]) => el('line', { x1, y1, x2, y2 }))),
    el('path', { d: almond, fill: '#0d0b0b', stroke: '#9aa3ad', 'stroke-width': 8 }),
    el('g', { 'clip-path': 'url(#eye-clip)' }, iris, lid));
  const slogan = document.createElement('div');
  slogan.className = 'bg-eye-slogan';
  slogan.textContent = 'THE OVERSEER IS WATCHING';
  const layer = document.createElement('div');
  layer.className = 'bg-eye';
  layer.setAttribute('aria-hidden', 'true');
  layer.append(svg, slogan);
  host.prepend(layer);

  let frame = 0;
  let pointer = null;
  const update = () => {
    frame = 0;
    if (!pointer) return;
    const r = svg.getBoundingClientRect();
    const scale = 600 / (r.width || 600);
    const s = irisShift((pointer.x - (r.left + r.width / 2)) * scale, (pointer.y - (r.top + r.height * 0.5)) * scale, 600);
    iris.setAttribute('transform', `translate(${s.x.toFixed(1)} ${s.y.toFixed(1)})`);
  };
  window.addEventListener('mousemove', (e) => {
    pointer = { x: e.clientX, y: e.clientY };
    if (!frame) frame = requestAnimationFrame(update);
  }, { passive: true });

  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const blink = () => {
      lid.classList.add('eye-blink');
      setTimeout(() => lid.classList.remove('eye-blink'), 260);
      setTimeout(blink, 7000 + Math.random() * 9000);
    };
    setTimeout(blink, 5000);
  }
}
