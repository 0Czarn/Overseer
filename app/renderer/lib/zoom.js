// Zoom for the large tree views (research tree, national focus tree): mouse wheel zooms at the cursor, the
// toolbar has − / + / Fit and shows the level. Dragging still moves the view (dragToScroll). The level is
// remembered per view (browser storage of this app).
import { h } from './dom.js';

export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 2;
const STEP = 1.15;
const KEY = 'hoi4dbg.zoom.';

/** Zoom level kept within the limits, rounded to 0.01. */
export function clampZoom(z, min = ZOOM_MIN, max = ZOOM_MAX) {
  return Math.round(Math.min(max, Math.max(min, z)) * 100) / 100;
}

/** Scroll position that keeps the content point under the cursor (mx, my in the view) in place. */
export function anchoredScroll(scroll, cursor, from, to) {
  return (scroll + cursor) / from * to - cursor;
}

/** Level that shows the whole content (width x height) in a view of viewW x viewH. */
export function fitZoom(width, height, viewW, viewH, min = ZOOM_MIN, max = ZOOM_MAX) {
  if (!width || !height || !viewW || !viewH) return 1;
  return clampZoom(Math.min(viewW / width, viewH / height), min, max);
}

export function readZoom(id, min = ZOOM_MIN, max = ZOOM_MAX) {
  try {
    const v = Number(localStorage.getItem(KEY + id));
    return v ? clampZoom(v, min, max) : 1;
  } catch {
    return 1;
  }
}

function writeZoom(id, z) {
  try { localStorage.setItem(KEY + id, String(z)); } catch { /* preference only */ }
}

/**
 * Makes `content` (absolute-size element of width x height) zoomable inside the scroll element `view`.
 * Returns { toolbar, sizer, level() } - put `sizer` inside `view` instead of `content`. Options: own zoom limits
 * {min, max} (the full-size game map) and onZoom(level) after every change.
 */
export function zoomable(id, view, content, width, height, { min = ZOOM_MIN, max = ZOOM_MAX, onZoom } = {}) {
  let z = readZoom(id, min, max);
  const sizer = h('div', { class: 'zoom-sizer' }, content);
  const label = h('span', { class: 'zoom-level', 'aria-live': 'polite' });
  const apply = () => {
    content.style.transform = `scale(${z})`;
    content.style.transformOrigin = '0 0';
    sizer.style.width = `${width * z}px`;
    sizer.style.height = `${height * z}px`;
    label.textContent = `${Math.round(z * 100)}%`;
  };
  const set = (next, cx = view.clientWidth / 2, cy = view.clientHeight / 2) => {
    next = clampZoom(next, min, max);
    if (next === z) return;
    const left = anchoredScroll(view.scrollLeft, cx, z, next);
    const top = anchoredScroll(view.scrollTop, cy, z, next);
    z = next;
    writeZoom(id, z);
    apply();
    view.scrollLeft = left;
    view.scrollTop = top;
    onZoom?.(z);
  };
  view.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = view.getBoundingClientRect();
    set(e.deltaY < 0 ? z * STEP : z / STEP, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  const btn = (text, title, fn) => h('button', { type: 'button', class: 'btn btn-small zoom-btn', title, 'aria-label': title,
    onClick: fn }, text);
  const toolbar = h('div', { class: 'zoom-bar' },
    btn('−', 'Zoom out', () => set(z / STEP)), label, btn('+', 'Zoom in', () => set(z * STEP)),
    btn('Fit', 'Show the whole tree', () => {
      set(fitZoom(width, height, view.clientWidth, view.clientHeight, min, max), 0, 0);
      view.scrollLeft = 0;
      view.scrollTop = 0;
    }),
    btn('100%', 'Actual size', () => set(1)),
    h('span', { class: 'muted zoom-hint' }, 'Mouse wheel: zoom · drag: move'));
  apply();
  return { toolbar, sizer, level: () => z };
}
