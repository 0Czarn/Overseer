// Collapsible tiles (2026-10-20, user's request: every tile of the app can be folded). Every card (.card with a
// .card-head) and game-style tile (.hoi-panel with a .hoi-head) gets a ▾ / ▸ button in its head, also tiles added
// later (a MutationObserver); the folded ones are remembered per tab and tile title. A folded tile keeps only its head;
// Live tiles do not read the game while folded (refresh.js) and read it again when unfolded ("tile-expanded" event).
// Each tab's header gets "Collapse all" / "Expand all".
import { h } from './dom.js';

const STORAGE_KEY = 'hoi4dbg.collapsed';
const TILE = '.card, .hoi-panel';

function load() {
  try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? []); } catch { return new Set(); }
}
function save(set) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...set])); } catch { /* preference only */ }
}

/** The head of a tile (its own, not one of a tile inside it), or null for a tile without a title. */
export function tileHead(tile) {
  return [...tile.children].find((c) => c.classList.contains('card-head') || c.classList.contains('hoi-head')) ?? null;
}

/** A stable name of a tile title: numbers and country tags left out ("Tree german_focus - 210 focuses" and
 * "Live stockpile of SOV" stay the same tile when their numbers or the country change). */
export function tileName(title) {
  return (title ?? '').replace(/\b[A-Z][A-Z0-9]{2}\b/g, '').replace(/[\d.,%]+/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

export function tileKey(view, tile) {
  const head = tileHead(tile);
  const title = head?.querySelector('h2, .hoi-head-title')?.textContent ?? head?.textContent ?? '';
  return `${view}|${tile.dataset.tile ?? tileName(title)}`;
}

export const isCollapsed = (el) => Boolean(el?.closest?.('.tile-collapsed'));

function setCollapsed(tile, on, view, remember = true) {
  tile.classList.toggle('tile-collapsed', on);
  const btn = tileHead(tile)?.querySelector('.tile-toggle');
  if (btn) {
    btn.textContent = on ? '▸' : '▾';
    btn.title = on ? 'Expand this tile' : 'Collapse this tile';
    btn.setAttribute('aria-expanded', String(!on));
  }
  if (remember) {
    const set = load();
    if (on) set.add(tileKey(view, tile)); else set.delete(tileKey(view, tile));
    save(set);
  }
  if (!on) tile.dispatchEvent(new Event('tile-expanded'));
}

/** Adds the fold button to every tile under `root` that has none yet, folding the remembered ones. */
export function enhanceTiles(root, view) {
  const folded = load();
  for (const tile of root.querySelectorAll(TILE)) {
    const head = tileHead(tile);
    if (!head || head.querySelector('.tile-toggle')) continue;
    const btn = h('button', { type: 'button', class: 'tile-toggle', 'aria-expanded': 'true', title: 'Collapse this tile' }, '▾');
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      setCollapsed(tile, !tile.classList.contains('tile-collapsed'), view);
    });
    // next to the tile's own controls (Live / On refresh), so a wrapping head keeps them together at the right
    (head.querySelector(':scope > .hoi-head-right') ?? head).append(btn);
    if (folded.has(tileKey(view, tile))) setCollapsed(tile, true, view, false);
  }
  const header = root.querySelector('.view-header .view-extras');
  if (header && !header.querySelector('.tile-all')) {
    const all = (on) => () => root.querySelectorAll(TILE).forEach((t) => { if (tileHead(t)) setCollapsed(t, on, view); });
    header.prepend(h('span', { class: 'tile-all' },
      h('button', { type: 'button', class: 'btn btn-small btn-ghost', onclick: all(true), title: 'Collapse every tile of this tab' }, 'Collapse all'),
      h('button', { type: 'button', class: 'btn btn-small btn-ghost', onclick: all(false), title: 'Expand every tile of this tab' }, 'Expand all')));
  }
}

/** Keeps the tiles of the view host collapsible while the views render and add tiles. */
export function watchTiles(host, currentView) {
  let pending = false;
  const run = () => { pending = false; enhanceTiles(host, currentView()); };
  new MutationObserver(() => {
    if (!pending) { pending = true; queueMicrotask(run); }
  }).observe(host, { childList: true, subtree: true });
  run();
}
