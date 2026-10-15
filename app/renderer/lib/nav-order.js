// The user's order of the main tabs (sidebar): dragged with the mouse or moved with Alt+Up / Alt+Down, kept in
// localStorage. Tabs added in a later version go where the default order has them.

export const NAV_ORDER_KEY = 'hoi4dbg.navOrder';

/** `ids` (the default order) arranged by `saved` (the user's order, may be stale): known saved ids first in their
 * order, every other id inserted after its predecessor in the default order. */
export function orderTabs(ids, saved) {
  const out = (Array.isArray(saved) ? saved : []).filter((id, i, a) => ids.includes(id) && a.indexOf(id) === i);
  ids.forEach((id, i) => {
    if (out.includes(id)) return;
    const prev = ids.slice(0, i).reverse().find((p) => out.includes(p));
    out.splice(prev ? out.indexOf(prev) + 1 : 0, 0, id);
  });
  return out;
}

/** `order` with `id` moved to the place of `target` (before it when moving up, after it when moving down). */
export function moveTab(order, id, target) {
  const from = order.indexOf(id);
  const to = order.indexOf(target);
  if (from < 0 || to < 0 || from === to) return order;
  const out = order.filter((x) => x !== id);
  out.splice(to, 0, id);
  return out;
}

export function loadNavOrder() {
  try { return JSON.parse(localStorage.getItem(NAV_ORDER_KEY)); } catch { return null; }
}

export function saveNavOrder(order) {
  try {
    if (order) localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order));
    else localStorage.removeItem(NAV_ORDER_KEY);
  } catch { /* preference only */ }
}
