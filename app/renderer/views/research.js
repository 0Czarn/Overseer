// Research: how many research slots the selected country has and what each one researches (game memory while
// the game runs, else the newest save). The tile has the usual [Live | On refresh] switch.
import { h, notice, viewHeader } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { countryPicker, tagChip } from './shared.js';

/** "+13%" for a research speed factor of 1.13 ('' when unknown or 1). */
export function speedText(speed) {
  if (speed == null || Math.abs(speed - 1) < 1e-9) return '';
  const pct = Math.round((speed - 1) * 1000) / 10;
  return `${pct > 0 ? '+' : ''}${pct}%`;
}

/** "2 of 3 slots researching" summary line. */
export function slotSummary(slots) {
  const busy = slots.filter((s) => s.technology).length;
  return `${busy} of ${slots.length} slot${slots.length === 1 ? '' : 's'} researching`;
}

/** "18.7% finished · 146 days left" (game rounding: progress cut to 0.1 %, days rounded up by the backend). */
export function progressText(s) {
  if (s.progress == null) return '';
  const pct = `${(Math.floor(s.progress * 1000) / 10).toFixed(1)}% finished`;
  if (s.days_left == null) return pct;
  return `${pct} · ${s.estimate ? '~' : ''}${s.days_left} day${s.days_left === 1 ? '' : 's'} left`;
}

/** "2.3 years ahead of time: -82% speed" for a technology researched before its start year ('' otherwise). */
export function aheadText(s) {
  if (!s.ahead_years || !s.base_speed || s.speed == null) return '';
  const pct = Math.round((s.speed / s.base_speed - 1) * 100);
  return `${s.ahead_years.toFixed(1)} years ahead of time: ${pct}% speed`;
}

function slotRow(s) {
  const speed = speedText(s.base_speed ?? s.speed);
  const ahead = aheadText(s);
  const info = h('span', { class: 'research-name' }, s.technology ? s.name : 'Empty slot',
    s.technology && s.name !== s.technology ? h('span', { class: 'muted research-id' }, ` ${s.technology}`) : null);
  const progress = s.progress == null ? null : h('div', { class: 'research-progress' },
    h('div', { class: 'research-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100,
      'aria-valuenow': Math.round(s.progress * 100) },
    h('div', { class: 'research-bar-fill', style: { width: `${Math.min(100, s.progress * 100)}%` } })),
    h('span', { class: 'research-progress-text', title: s.estimate
      ? 'Estimate: ahead of time the day count can differ by a day; from a save the technology bonus is unknown' : `Cost ${Math.round(s.cost)} research points` },
    progressText(s)),
    ahead ? h('span', { class: 'research-ahead', title: 'The game divides the research speed by 1 + 2 x years ahead; '
      + 'the penalty shrinks every day until the start year' }, ahead) : null);
  return h('div', { class: `research-slot ${s.technology ? '' : 'research-empty'}` },
    h('span', { class: 'research-no' }, s.slot),
    s.icon ? h('img', { class: 'research-icon', src: s.icon, alt: '' }) : h('span', { class: 'research-icon research-icon-none' }),
    h('div', { class: 'research-main' }, info, progress),
    h('span', { class: 'research-speed', title: 'Research speed bonus of this slot' }, speed));
}

/** "+50% · Motorization Research Speed · 1 use left" for a limited (one-time) research bonus. */
export function bonusText(b) {
  const pct = Math.round(b.bonus * 1000) / 10;
  const cats = (b.category_labels?.length ? b.category_labels : b.categories).join(', ');
  return `+${pct}% · ${cats} · ${b.uses} use${b.uses === 1 ? '' : 's'} left`;
}

function bonusList(bonuses) {
  if (!bonuses) return null;
  return h('div', { class: 'research-bonuses' },
    h('h3', { class: 'research-subhead' }, `Limited bonuses: ${bonuses.length}`),
    bonuses.length
      ? h('ul', { class: 'research-bonus-list' }, bonuses.map((b) => h('li', { class: 'research-bonus' },
        h('span', { class: 'research-bonus-name' }, b.label || b.name),
        h('span', { class: 'research-bonus-info', title: `${b.name} · ${b.categories.join(', ')}` }, bonusText(b)))))
      : h('p', { class: 'muted' }, 'No one-time research bonuses available.'));
}

/** Research slots tile (refreshable). Returns { el, refresh, stop }. */
export function researchPanel(ctx, tag) {
  return livePanel(ctx, {
    title: 'Research slots', url: `/api/countries/${encodeURIComponent(tag)}/research`,
    liveParts: (res) => (res.data?.research_source === 'live' ? ['research slots'] : []),
    render(body, res) {
      const slots = res.data?.slots;
      if (!slots) {
        body.replaceChildren(notice('warn', `Research unavailable: ${res.note}`));
        return;
      }
      body.replaceChildren(
        h('p', { class: 'muted research-summary' }, slotSummary(slots)),
        h('div', { class: 'research-slots' }, slots.map(slotRow)),
        bonusList(res.data.bonuses));
    },
  });
}

export default {
  id: 'research',
  title: 'Research',
  short: 'RS',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const picker = await countryPicker(ctx);
    const tile = researchPanel(ctx, tag);
    root.append(
      viewHeader('Research', 'Research slots of the selected country and what each one researches.', picker),
      h('div', { class: 'country-head research-head' }, tagChip(tag, 'tag-chip-lg')),
      tile.el);
    return () => tile.stop();
  },
};
