// Renderer entry: navigation, shared state, status polling.
import { createApi } from './lib/api.js';
import { clear, errorBox, h, toast } from './lib/dom.js';
import { startFocusWatch } from './lib/focus-watch.js';
import dashboard from './views/dashboard.js';
import countries from './views/countries.js';
import countryEditor from './views/country-editor.js';
import research from './views/research.js';
import construction from './views/construction.js';
import stateEditor from './views/state-editor.js';
import focus from './views/focus.js';
import equipment from './views/equipment.js';
import tools from './views/tools.js';
import intel from './views/intel.js';
import logs from './views/logs.js';

const VIEWS = [dashboard, countries, countryEditor, research, construction, stateEditor, focus, equipment, tools, intel, logs];
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
  return location.hash.replace(/^#\/?/, '') || 'dashboard';
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
  document.title = `${view.title} - HOI4 Debugger`;

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

function buildNav() {
  const nav = document.getElementById('nav');
  nav.append(...VIEWS.map((v) => h('a', { href: `#/${v.id}`, 'data-view': v.id, title: v.title },
    h('span', { class: 'nav-icon' }, v.short), h('span', { class: 'nav-label' }, v.title))));
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
    try { new Notification('HOI4 Debugger - national focus', { body: message }); } catch { /* notifications unavailable */ }
  }), 5000);
  await renderView();
  document.body.dataset.ready = '1';
}

init();
