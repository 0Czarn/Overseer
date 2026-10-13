// Doctrines: the selected country's grand doctrine and subdoctrines per folder (land, naval, air, special forces),
// laid out like the game's doctrine screen - each track with its subdoctrine, mastery, the reward thresholds I-V
// (unlocked or not, with their effects) and the doctrines that could be chosen instead (game memory).
import { h, notice, viewHeader } from '../lib/dom.js';
import { livePanel } from '../lib/refresh.js';
import { countryPicker, tagChip } from './shared.js';
import { formatModifier } from './spirits.js';

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'];
const TAB_KEY = 'hoi4dbg.doctrineFolder';

function readTab() {
  try { return localStorage.getItem(TAB_KEY); } catch { return null; }
}

function writeTab(id) {
  try { localStorage.setItem(TAB_KEY, id); } catch { /* preference only */ }
}

/** Tooltip text of a doctrine / reward: name, description, effects, tactics. */
export function doctrineTitle(d) {
  if (!d) return '';
  return [d.name, d.desc, ...(d.modifiers ?? []).map((m) => `${m.label}: ${formatModifier(m.key, m.value)}`),
    ...(d.tactics ?? []).map((t) => `Enables tactic: ${t}`)].filter(Boolean).join('\n');
}

/** "Next reward in 111 days (~0.70 a day)" / "All rewards unlocked" / "" (no gain). */
export function nextRewardText(t) {
  const next = t.sub?.rewards.find((r) => !r.unlocked);
  if (!t.sub) return '';
  if (!next) return 'All rewards unlocked';
  if (!t.daily) return `Next reward at ${next.threshold} - no mastery gained now`;
  const days = Math.ceil((next.threshold - t.mastery) / t.daily);
  return `Next reward in ${days} day${days === 1 ? '' : 's'} (~${t.daily.toFixed(2)} a day)`;
}

function emblem(d, cls) {
  return d?.icon ? h('img', { class: cls, src: d.icon, alt: '', draggable: 'false' }) : h('span', { class: `${cls} doc-icon-none` });
}

function trackColumn(t) {
  const max = t.max_mastery || 500;
  const pct = Math.min(100, (t.mastery / max) * 100);
  const head = h('div', { class: 'doc-track-head' },
    t.icon ? h('img', { class: 'doc-track-icon', src: t.icon, alt: '' }) : null,
    h('span', { class: 'doc-track-name' }, t.name));
  const sub = t.sub
    ? h('div', { class: 'doc-sub', title: doctrineTitle(t.sub) },
      emblem(t.sub, 'doc-sub-icon'),
      h('span', { class: 'doc-mastery', title: 'Mastery' }, Math.floor(t.mastery)),
      h('div', { class: 'doc-plate' }, t.sub.name))
    : h('div', { class: 'doc-sub doc-sub-empty', title: 'No subdoctrine chosen - mastery gained here is banked' },
      h('span', { class: 'doc-sub-icon doc-icon-none' }),
      t.bank ? h('span', { class: 'doc-mastery doc-bank', title: 'Banked mastery (max 200)' }, `+${Math.floor(t.bank)}`) : null,
      h('div', { class: 'doc-plate doc-plate-empty' }, 'No subdoctrine'));
  const ladder = t.sub ? h('div', { class: 'doc-ladder' },
    h('div', { class: 'doc-bar' }, h('div', { class: 'doc-bar-fill', style: { height: `${pct}%` } })),
    ...t.sub.rewards.map((r, i) => h('div', {
      class: `doc-reward ${r.unlocked ? 'doc-reward-on' : ''} ${i % 2 ? 'doc-reward-right' : 'doc-reward-left'}`,
      style: { top: `${(r.threshold / max) * 100}%` }, title: doctrineTitle(r) || r.name, tabindex: 0,
    }, h('span', { class: 'doc-roman' }, ROMAN[i] ?? i + 1), h('span', { class: 'doc-threshold' }, r.threshold),
    h('span', { class: 'doc-reward-name' }, r.name)))) : null;
  const options = t.options?.length ? h('div', { class: 'doc-options' },
    h('span', { class: 'muted doc-options-label' }, 'Other choices'),
    h('div', { class: 'doc-option-row' }, t.options.map((o) => h('span', { class: 'doc-option', title: doctrineTitle(o), tabindex: 0 },
      emblem(o, 'doc-option-icon'))))) : null;
  const milestone = t.milestone && (t.milestone.modifiers.length || t.milestone.tactics.length)
    ? h('div', { class: 'doc-milestone', title: doctrineTitle({ name: 'Milestone: all rewards of this track', ...t.milestone }) },
      `Milestone when the track is complete: ${[...t.milestone.modifiers.map((m) => `${m.label} ${formatModifier(m.key, m.value)}`), ...t.milestone.tactics].join(', ')}`)
    : null;
  return h('div', { class: 'doc-track' }, head, sub,
    h('div', { class: 'muted doc-next' }, nextRewardText(t)), ladder, milestone, options);
}

function folderView(f) {
  const grand = f.grand
    ? h('div', { class: 'doc-grand', title: doctrineTitle(f.grand) }, emblem(f.grand, 'doc-grand-icon'),
      h('div', { class: 'doc-plate doc-grand-plate' }, f.grand.name))
    : h('div', { class: 'doc-grand doc-grand-empty' }, h('div', { class: 'doc-plate doc-plate-empty' }, 'No grand doctrine chosen'));
  const others = f.grand_options?.length ? h('div', { class: 'doc-options doc-grand-options' },
    h('span', { class: 'muted doc-options-label' }, 'Other grand doctrines'),
    h('div', { class: 'doc-option-row' }, f.grand_options.map((o) => h('span', { class: 'doc-option', title: doctrineTitle(o), tabindex: 0 },
      emblem(o, 'doc-option-icon'))))) : null;
  return h('div', { class: 'doc-folder' }, grand, others,
    f.tracks.length ? h('div', { class: 'doc-tracks' }, f.tracks.map(trackColumn))
      : h('p', { class: 'muted' }, 'No tracks - choose a grand doctrine in the game first.'));
}

/** Doctrines tile (refreshable) with the game's folder tabs. Returns { el, refresh, stop }. */
export function doctrinesPanel(ctx, tag) {
  let selected = readTab();
  return livePanel(ctx, {
    title: 'Doctrines', url: `/api/countries/${encodeURIComponent(tag)}/doctrines`,
    liveParts: (res) => (res.data?.doctrine_source === 'live' ? ['doctrines, mastery'] : []),
    render(body, res) {
      const d = res.data;
      if (!d?.folders) {
        body.replaceChildren(notice('warn', `Doctrines unavailable: ${res.note}`));
        return;
      }
      if (!d.folders.some((f) => f.id === selected)) selected = d.folders[0]?.id;
      const host = h('div');
      const tabs = h('div', { class: 'doc-tabs', role: 'group', 'aria-label': 'Doctrine folders' });
      const show = () => {
        tabs.replaceChildren(...d.folders.map((f) => {
          const b = h('button', { type: 'button', class: `doc-tab ${f.id === selected ? 'doc-tab-on' : ''}`,
            'aria-pressed': f.id === selected ? 'true' : 'false' },
          f.icon ? h('img', { class: 'doc-tab-icon', src: f.icon, alt: '' }) : null, f.name);
          b.addEventListener('click', () => { selected = f.id; writeTab(f.id); show(); });
          return b;
        }));
        host.replaceChildren(folderView(d.folders.find((f) => f.id === selected)));
      };
      show();
      body.replaceChildren(tabs, host);
    },
  });
}

export default {
  id: 'doctrines',
  title: 'Doctrines',
  short: 'DC',
  async render(root, ctx) {
    const tag = ctx.state.selectedCountry;
    const picker = await countryPicker(ctx);
    const tile = doctrinesPanel(ctx, tag);
    root.append(
      viewHeader('Doctrines', 'Grand doctrine, subdoctrines and their mastery of the selected country (game memory).', picker),
      h('div', { class: 'country-head research-head' }, tagChip(tag, 'tag-chip-lg')),
      tile.el);
    return () => tile.stop();
  },
};
