// Renderer entry: navigation, shared state, status polling.
import { createApi } from './lib/api.js';
import { clear, errorBox, h, toast } from './lib/dom.js';
import { startFocusWatch } from './lib/focus-watch.js';
import { sortMessage, startConstructionSort } from './lib/construction-sort.js';
import { autostartMessage, startFocusAutostart } from './lib/focus-autostart.js';
import dashboard from './views/dashboard.js';
import countries from './views/countries.js';
import countryEditor from './views/country-editor.js';
import research from './views/research.js';
import construction from './views/construction.js';
import doctrines from './views/doctrines.js';
import stateEditor from './views/state-editor.js';
import focus from './views/focus.js';
import equipment from './views/equipment.js';
import tools from './views/tools.js';
import logs from './views/logs.js';
import summary from './views/summary.js';
import actions from './views/actions.js';
import { loadNavOrder, moveTab, orderTabs, saveNavOrder } from './lib/nav-order.js';
import { mountEye } from './lib/eye.js';
import { applyOptions, loadOptions } from './lib/options.js';
import options from './views/options.js';

const VIEWS = [dashboard, summary, actions, countries, countryEditor, research, construction, doctrines, stateEditor, focus, equipment, tools, logs, options];
const STATUS_INTERVAL_MS = 3000;
const PREFS_KEY = 'hoi4dbg.prefs';

const bridge = globalThis.hoi4dbg;
const api = createApi(bridge);
const viewEl = document.getElementById('view');
const statusListeners = new Set();

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY)) ?? {};
  } catch {
    return {};
  }
}

const prefs = loadPrefs();
const state = {
  selectedCountry: prefs.selectedCountry ?? 'GER',
  observerCountry: prefs.observerCountry ?? 'SOV',
  compact: Boolean(prefs.compact),
  alwaysOnTop: false,
  status: null,
};

function savePrefs() {
  try {
    const { selectedCountry, observerCountry, compact } = state;
    localStorage.setItem(PREFS_KEY, JSON.stringify({ selectedCountry, observerCountry, compact }));
  } catch {
    /* storage unavailable - preferences are a convenience only */
  }
}

let cleanup = null;
let renderSeq = 0;

const ctx = {
  api,
  bridge,
  state,
  setState(patch) {
    const needsRerender = ['selectedCountry', 'observerCountry'].some((k) => k in patch && patch[k] !== state[k]);
    Object.assign(state, patch);
    applyCompact();
    syncToggles();
    savePrefs();
    if (needsRerender) renderView();
  },
  navigate(id) {
    location.hash = `#/${id}`;
  },
  rerender: () => renderView(),
  views: null,           // the tabs (set below; Options lists them)
  resetNavOrder: () => {},   // set by buildNav
  onStatus(fn) {
    statusListeners.add(fn);
    return () => statusListeners.delete(fn);
  },
  refreshStatus: () => pollStatus(),
  async setAlwaysOnTop(enabled) {
    state.alwaysOnTop = await bridge.setAlwaysOnTop(enabled);
    syncToggles();
  },
};

function currentViewId() {
  return location.hash.replace(/^#\/?/, '') || loadOptions().startTab || 'dashboard';
}

async function renderView() {
  const view = VIEWS.find((v) => v.id === currentViewId()) ?? VIEWS[0];
  const seq = ++renderSeq;
  if (cleanup) {
    cleanup();
    cleanup = null;
  }
  document.body.dataset.view = view.id;
  document.body.dataset.loading = '1';
  delete document.body.dataset.rendered; // set only when THIS view's content is on screen (smoke test waits on it)
  for (const link of document.querySelectorAll('.nav a')) link.classList.toggle('active', link.dataset.view === view.id);
  document.title = `${view.title} - Project OVERSEER`;

  const root = h('div', { class: 'view-inner' });
  let viewCleanup = null;
  try {
    viewCleanup = await view.render(root, ctx);
  } catch (err) {
    root.append(h('div', { class: 'view-header' }, h('h1', null, view.title)), errorBox(`Could not load this view: ${err.message}`));
    api.log('error', `View ${view.id} failed: ${err.message}`);
  }
  if (seq !== renderSeq) {
    viewCleanup?.();
    return;
  }
  cleanup = typeof viewCleanup === 'function' ? viewCleanup : null;
  clear(viewEl).append(root);
  root.dispatchEvent(new Event('mounted'));
  document.body.dataset.loading = '0';
  document.body.dataset.rendered = view.id;
}

// Sidebar icons (assets/texticons, from the mods Modifier Icons / Descriptive Icons) - the two-letter short name is
// shown only for a view without one.
const NAV_ICONS = {
  dashboard: 'civilian_intel_texticon.png', summary: 'factory_output_modifier_texticon.png', actions: 'decision_icon_small.png',
  countries: 'ai_faction_texticon.png', 'country-editor': 'political_power_texticon.png', research: 'research_speed_texticon.png',
  construction: 'construction_speed_texticon.png', doctrines: 'divisions_texticon.png', 'state-editor': 'infrastructure_building_texticon.png',
  focus: 'decision_modifier_texticon.png', equipment: 'ai_military_equipment_texticon.png', tools: 'repairing.png',
  logs: 'decryption_texticon.png', options: '../options.svg',
};

// The sidebar in the user's order (lib/nav-order.js): drag a tab, or Alt+Up / Alt+Down on a focused one.
function buildNav() {
  const nav = document.getElementById('nav');
  const ids = VIEWS.map((v) => v.id);
  let order = orderTabs(ids, loadNavOrder());
  let dragged = null;
  const apply = (next) => {
    order = next;
    saveNavOrder(order.join() === ids.join() ? null : order);
    render();
  };
  function render() {
    const custom = order.join() !== ids.join();
    nav.replaceChildren(...order.map((id) => {
      const v = VIEWS.find((x) => x.id === id);
      return h('a', { href: `#/${v.id}`, 'data-view': v.id, title: `${v.title} - drag to move (or Alt+Up / Alt+Down)`,
        draggable: 'true', class: v.id === currentViewId() ? 'active' : '',
        ondragstart: (e) => { dragged = v.id; e.dataTransfer.effectAllowed = 'move'; e.currentTarget.classList.add('nav-dragging'); },
        ondragend: (e) => { dragged = null; e.currentTarget.classList.remove('nav-dragging'); },
        ondragover: (e) => { if (dragged && dragged !== v.id) { e.preventDefault(); e.currentTarget.classList.add('nav-drop'); } },
        ondragleave: (e) => e.currentTarget.classList.remove('nav-drop'),
        ondrop: (e) => { e.preventDefault(); if (dragged) apply(moveTab(order, dragged, v.id)); },
        onkeydown: (e) => {
          if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
          e.preventDefault();
          const i = order.indexOf(v.id) + (e.key === 'ArrowUp' ? -1 : 1);
          if (i < 0 || i >= order.length) return;
          apply(moveTab(order, v.id, order[i]));
          nav.querySelector(`a[data-view="${v.id}"]`)?.focus();
        } },
      NAV_ICONS[v.id] ? h('img', { class: 'nav-icon nav-img', src: `assets/texticons/${NAV_ICONS[v.id]}`, alt: '' })
        : h('span', { class: 'nav-icon' }, v.short),
      h('span', { class: 'nav-label' }, v.title));
    }), ...(custom ? [h('button', { class: 'nav-reset', title: 'Back to the default order of the tabs',
      onclick: () => apply(ids) }, 'Reset tab order')] : []));
  }
  ctx.resetNavOrder = () => apply(ids);
  render();
}

function renderStatus(status, error) {
  const pill = document.getElementById('game-pill');
  const meta = document.getElementById('game-meta');
  if (error) {
    pill.className = 'pill pill-bad';
    pill.textContent = 'Backend offline';
    meta.textContent = error;
    return;
  }
  const { game } = status;
  if (game.detected) {
    pill.className = 'pill pill-ok';
    pill.textContent = `HOI4 running · PID ${game.process.pid}`;
  } else {
    pill.className = 'pill pill-muted';
    pill.textContent = 'HOI4 not detected';
  }
  const version = game.install?.version?.display;
  const date = game.session?.last_game_date;
  meta.textContent = [version, date ? `game.log date (may lag): ${date}` : null].filter(Boolean).join(' · ');
}

async function pollStatus() {
  try {
    const status = await api.get('/api/status');
    state.status = status;
    renderStatus(status);
    for (const fn of statusListeners) fn(status);
    return status;
  } catch (err) {
    renderStatus(null, err.message);
    return null;
  }
}

function applyCompact() {
  document.body.classList.toggle('compact', state.compact);
}

function syncToggles() {
  document.getElementById('toggle-compact').checked = state.compact;
  document.getElementById('toggle-ontop').checked = state.alwaysOnTop;
}

async function init() {
  buildNav();
  mountEye(document.querySelector('.main'));
  ctx.views = VIEWS;
  applyOptions(loadOptions(), api);
  applyCompact();
  document.getElementById('toggle-compact').addEventListener('change', (e) => ctx.setState({ compact: e.target.checked }));
  document.getElementById('toggle-ontop').addEventListener('change', (e) => ctx.setAlwaysOnTop(e.target.checked));
  if (bridge) {
    state.alwaysOnTop = (await bridge.getWindowState()).alwaysOnTop;
    const info = await bridge.backendInfo();
    document.getElementById('sidebar-foot').textContent = info.running ? `Backend: ${info.python}` : 'Backend not running';
  }
  syncToggles();
  window.addEventListener('hashchange', renderView);
  window.addEventListener('error', (e) => api.log('error', `Renderer error: ${e.message}`));
  window.addEventListener('unhandledrejection', (e) => api.log('error', `Unhandled rejection: ${e.reason?.message ?? e.reason}`));

  await pollStatus();
  setInterval(pollStatus, STATUS_INTERVAL_MS);
  // Focus alerts: in-app toast + system notification (shown even when the game has focus). Not in the UI smoke
  // test (its logic has unit tests) - the first reading of a large save would slow the views under test.
  const smoke = bridge ? (await bridge.backendInfo()).smoke : false;
  if (!smoke) setTimeout(() => startFocusWatch(api, (message) => {
    toast(message, 'info');
    api.log('info', `Focus alert: ${message}`);
    try { new Notification('Project OVERSEER - national focus', { body: message }); } catch { /* notifications unavailable */ }
  }), 5000);
  // Optional construction queue auto-sort (switch on the Construction tab): a refusal (multiplayer, player not
  // known) is shown once per reason, not every few seconds
  let lastSortError = null;
  if (!smoke) startConstructionSort(api, (res, err) => {
    const message = sortMessage(res);
    if (message) {
      toast(message, 'ok');
      api.log('warning', `Local memory write: ${message}`);
    }
    if (err && err.message !== lastSortError) toast(`Construction auto-sort: ${err.message}`, 'warn');
    lastSortError = err ? err.message : null;
  });
  // Optional focus auto-start (switch on the National Focus Manager tab); refusals shown once per reason
  const manualSeen = new Set();
  let lastFocusError = null;
  if (!smoke) startFocusAutostart(api, (res, err) => {
    const msg = autostartMessage(res, manualSeen);
    if (msg) {
      toast(msg.text, msg.kind);
      api.log(msg.kind === 'ok' ? 'warning' : 'info', `Focus auto-start: ${msg.text}`);
      try { new Notification('Project OVERSEER - national focus', { body: msg.text }); } catch { /* unavailable */ }
    }
    if (err && err.message !== lastFocusError) toast(`Focus auto-start: ${err.message}`, 'warn');
    lastFocusError = err ? err.message : null;
  });
  await renderView();
  document.body.dataset.ready = '1';
}

init();
