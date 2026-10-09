import { h, card, demoBanner, meter, notice, sourceBadge, viewHeader } from '../lib/dom.js';
import { FOCUS_COLUMNS, groupFocuses } from '../lib/format.js';
import { countryPicker } from './shared.js';

function focusCard(focus, queueSupported) {
  return h('div', { class: `focus focus-${focus.status}` },
    h('div', { class: 'focus-name' }, focus.name),
    h('code', { class: 'focus-id' }, focus.id),
    h('div', { class: 'focus-meta' }, `${focus.days} days`,
      focus.blocked_by ? h('span', { class: 'warn-text' }, ` - needs ${focus.blocked_by}`) : null),
    focus.status === 'in_progress' ? meter(focus.progress ?? 0) : null,
    focus.status === 'available'
      ? h('button', { class: 'btn btn-small', disabled: !queueSupported, title: 'Queueing not available yet' },
        'Queue next')
      : null);
}

export default {
  id: 'focus',
  title: 'National Focus Manager',
  short: 'NF',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const [res, picker] = await Promise.all([ctx.api.get(`/api/focus/${encodeURIComponent(tag)}`), countryPicker(ctx)]);
    const groups = groupFocuses(res.data.focuses);

    root.append(
      viewHeader('National Focus Manager', 'Current, completed, available and blocked focuses.',
        picker, sourceBadge(res.source, res.note)),
      res.source === 'demo' ? demoBanner(res.note) : null,
      notice('info', 'Focuses are never completed instantly by this tool. Queueing the next focus will only be '
        + 'offered if the game provides a way to do it that works for all players.'),
      res.data.focuses.length
        ? h('div', { class: 'kanban' }, FOCUS_COLUMNS.map((col) => card(`${col.label} (${groups[col.status].length})`,
          groups[col.status].length
            ? groups[col.status].map((f) => focusCard(f, res.data.queue_supported))
            : h('p', { class: 'muted' }, 'None'))))
        : notice('muted', `No focus data for ${tag}.`),
    );
  },
};
