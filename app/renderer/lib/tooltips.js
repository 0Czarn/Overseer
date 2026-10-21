// Tooltips kept in the window (2026-10-20, user's report apl_display_bug.jpg: the Military Staff tooltip was cut off
// at the bottom of the window). The game-style tooltips (.spirit-tip of spirits, laws, advisors, MIOs, leader, party
// pie) open below their tile; when shown they are placed fixed: below, else above, else as high as fits, and moved
// left to stay inside the window (also out of tiles that clip their content).
const HOSTS = '.spirit, .pie-wrap';
const GAP = 6;
const MARGIN = 4;

/** {left, top} of a tooltip of width x height next to the tile rectangle `r` in a window of vw x vh. */
export function tipPosition(r, width, height, vw, vh) {
  let top = r.bottom + GAP;
  if (top + height > vh - MARGIN) top = r.top - GAP - height >= MARGIN ? r.top - GAP - height : Math.max(MARGIN, vh - MARGIN - height);
  const left = Math.max(MARGIN, Math.min(r.left, vw - MARGIN - width));
  return { left: Math.round(left), top: Math.round(top) };
}

function place(e) {
  const host = e.target.closest?.(HOSTS);
  const tip = host && [...host.children].find((c) => c.classList.contains('spirit-tip'));
  if (!tip || getComputedStyle(tip).display === 'none') return;
  tip.style.position = 'fixed';
  tip.style.bottom = 'auto';
  const { left, top } = tipPosition(host.getBoundingClientRect(), tip.offsetWidth, tip.offsetHeight, window.innerWidth, window.innerHeight);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

/** Places every game-style tooltip of `root` when it opens (mouse or keyboard). */
export function keepTooltipsInWindow(root = document) {
  // after the browser applied :hover / :focus (the tooltip is displayed and can be measured)
  const later = (e) => requestAnimationFrame(() => place(e));
  root.addEventListener('mouseover', later);
  root.addEventListener('focusin', later);
}
