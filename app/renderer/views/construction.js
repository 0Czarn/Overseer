// Construction: what the selected country builds and has queued, in the game's queue order, with the progress of
// each line (game memory). The tile has the usual [Live | On refresh] switch.
import { h, notice, viewHeader } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { countryPicker, tagChip } from './shared.js';

/** "87%" - progress of the level being built, cut to whole percent like the game tooltip. */
export function progressPct(progress) {
  if (progress == null) return '';
  return `${Math.floor(progress * 100 + 1e-9)}%`;
}

/** "6309 / 7200" - construction points done of one level, cut like the game tooltip. */
export function pointsText(line) {
  return `${Math.floor(line.produced + 1e-9)} / ${Math.round(line.cost)}`;
}

/** "5 days · 2 Oct, 1941 · 183.75 a day" - when the level being built completes at today's speed. */
export function completeText(line) {
  if (line.days_left == null) return 'Not being built';
  const days = `${line.days_left} day${line.days_left === 1 ? '' : 's'}`;
  const speed = `${Math.round(line.speed * 100) / 100} a day`;
  return [days, line.next_complete?.text, speed].filter(Boolean).join(' · ');
}

/** "34 in queue · 18 repairs · 7 being built · 97 factories working" summary line. */
export function queueSummary(lines) {
  if (!lines.length) return 'Nothing in the construction queue';
  const busy = lines.filter((l) => l.factories > 0);
  const repairs = lines.filter((l) => l.action === 'repair' || l.action === 'build_repair').length;
  const factories = busy.reduce((n, l) => n + l.factories, 0);
  return [`${lines.length} in queue`, repairs ? `${repairs} repair${repairs === 1 ? '' : 's'}` : '',
    `${busy.length} being built`, `${factories} ${factories === 1 ? 'factory' : 'factories'} working`].filter(Boolean).join(' · ');
}

const ACTION_LABEL = { build: 'Construction', repair: 'Repair', build_repair: 'Construction + repair' };

/** "Repair: 2 damaged levels" / "2 levels to build" / "1 level to build, 1 damaged level to repair". */
export function actionText(l) {
  const lv = (n, what) => `${n} ${what} level${n === 1 ? '' : 's'}`;
  if (l.action === 'repair') return `Repair: ${lv(l.repair, 'damaged')}`;
  if (l.action === 'build_repair') return `${lv(l.levels, 'new')} to build, ${lv(l.repair, 'damaged')} to repair`;
  if (l.railway_levels) {   // game tooltip: "Upgrading 2 level railways ... to level 3 · Railways needed for completion: 4"
    const [from, to] = l.railway_levels;
    return `${from ? `upgrading level ${from} railways` : 'new railways'} to level ${to} · ${l.levels} railway${l.levels === 1 ? '' : 's'} needed`;
  }
  return `${l.levels} level${l.levels === 1 ? '' : 's'} to build`;
}

/** "Bryansk" / "Bizerte - Tunis" (railway, named like the game) / "State 288". */
export function placeText(l) {
  if (l.place) return l.place;
  const start = l.state_name ?? (l.state != null ? `State ${l.state}` : '—');
  return l.end_state_name ? `${start} → ${l.end_state_name}` : start;
}

function lineRow(l) {
  const working = l.factories > 0;
  const repair = l.action !== 'build';
  const where = [placeText(l), l.province != null ? `province ${l.province}` : '',
    l.path?.length > 1 ? `${l.path.length} provinces` : ''].filter(Boolean).join(', ');
  return h('div', { class: `construction-line ${working ? '' : 'construction-waiting'} ${repair ? 'construction-repair' : ''}`.trim(),
    title: `${ACTION_LABEL[l.action] ?? ''}: ${l.name} in ${where} · ${actionText(l)} · `
      + `progress of the current level ${progressPct(l.progress)} (${pointsText(l)} construction points) · ${completeText(l)}` },
  h('span', { class: 'construction-no' }, l.position),
  h('span', { class: 'construction-state' }, placeText(l)),
  h('span', { class: 'construction-building' },
    l.icon ? h('img', { class: 'construction-icon', src: l.icon, alt: '' }) : null,
    h('span', { class: 'construction-levels',
      title: repair ? 'Damaged levels to repair' : l.railway_levels ? 'Railways still needed' : 'Levels still to build' },
      l.action === 'repair' ? l.repair : l.levels)),
  h('div', { class: 'construction-main' },
    h('span', { class: 'construction-name' },
      h('span', { class: `construction-action construction-action-${l.action}` }, ACTION_LABEL[l.action] ?? l.action),
      ` ${l.name} · `, h('span', { class: 'muted' }, actionText(l))),
    h('div', { class: 'research-progress' },
      h('div', { class: 'research-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100,
        'aria-valuenow': Math.round((l.progress ?? 0) * 100), 'aria-label': `${l.name} in ${l.state_name}: progress` },
      h('div', { class: 'research-bar-fill', style: { width: `${Math.min(100, (l.progress ?? 0) * 100)}%` } })),
      h('span', { class: 'research-progress-text' }, `${progressPct(l.progress)} · ${pointsText(l)}`)),
    h('span', { class: 'construction-eta muted', title: 'Next level complete at the current construction speed (game tooltip "Next complete")' },
      completeText(l))),
  h('span', { class: `construction-factories ${working ? '' : 'muted'}`, title: 'Civilian factories assigned to this line' },
    `${l.factories}/${l.max_factories}`));
}

/** Construction queue tile (refreshable). Returns { el, refresh, stop }. */
export function constructionPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Construction queue', url: `/api/countries/${encodeURIComponent(tag)}/construction`,
    liveParts: (res) => (res.data?.construction_source === 'live' ? ['construction queue'] : []),
    render(body, res) {
      const lines = res.data?.lines;
      if (!lines) {
        body.replaceChildren(notice('warn', `Construction unavailable: ${res.note}`));
        return;
      }
      body.replaceChildren(
        h('p', { class: 'muted research-summary' }, queueSummary(lines)),
        h('div', { class: 'construction-lines' }, lines.map(lineRow)));
    },
  });
}

export default {
  id: 'construction',
  title: 'Construction',
  short: 'CN',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const picker = await countryPicker(ctx);
    const tile = constructionPanel(ctx, tag);
    root.append(
      viewHeader('Construction', 'What the selected country builds and has queued, with the progress of each line (game memory).', picker),
      h('div', { class: 'country-head research-head' }, tagChip(tag, 'tag-chip-lg')),
      tile.el);
    return () => tile.stop();
  },
};
