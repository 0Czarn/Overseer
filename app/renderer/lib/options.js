// The app's own settings (Options tab), kept in localStorage: the style (1984 / classic), the Overseer's eye behind
// the views, a background image of the user's (stored by the backend, backgrounds.py) with its transparency, and the
// tab the app opens with. applyOptions puts them on the page.
import { setEyeOptions } from './eye.js';

export const OPTIONS_KEY = 'hoi4dbg.options';
export const DEFAULTS = {
  theme: '1984',          // '1984' | 'classic' (the look before the 1984 style)
  eye: true, eyeOpacity: 22, eyeTrack: true, eyeBlink: true,
  image: null,            // id of a background image (backend /api/backgrounds) or null
  imageOpacity: 35, imageFit: 'cover', imageBlur: 0,
  startTab: '',           // '' = the dashboard
  notifyFocus: true, notifyRecording: true, notifyGame: false,   // Windows notifications
  refresh: 'normal',      // live reading pace: 'fast' | 'normal' | 'light'
  lang: 'en', numbers: 'en',   // interface language, number format ('en' 1,234.5 | 'pl' 1 234,5 | 'system')
  textSize: 100,          // % zoom of the whole window
  shortcuts: true,
  hiddenTabs: [],         // tab ids not shown in the sidebar
  favCountry: '',         // pinned first in every country picker
  cleanupDays: 0, cleanupMB: 0,   // automatic clean-up of recorded campaigns (0 = off)
  showOnGame: false,      // bring the window up when the game starts
  overlayFields: ['political_power', 'stability', 'war_support', 'command_power', 'fuel', 'ic'],
  overlayOpacity: 85,
  playersRail: 'mp',      // the players of the session left of the tabs: 'mp' | 'always' | 'never'
};
export const OVERLAY_FIELDS = {
  political_power: 'Political Power', stability: 'Stability', war_support: 'War Support', command_power: 'Command Power',
  fuel: 'Fuel', army_experience: 'Army XP', navy_experience: 'Navy XP', air_experience: 'Air XP', ic: 'IC a day', date: 'Date',
};
export const PLAYERS_RAIL = { mp: 'In multiplayer', always: 'Always', never: 'Never' };
export const REFRESH = { fast: ['Fast', 0.5], normal: ['Normal', 1], light: ['Light on the CPU', 2.5] };
export const LANGS = { en: 'English', pl: 'Polski' };
export const NUMBERS = { en: '1,234.5', pl: '1 234,5', system: 'As in Windows' };
export const TEXT_MIN = 70;
export const TEXT_MAX = 160;
export const THEMES = { 1984: 'Overseer (1984)', classic: 'Classic (before)' };
export const FITS = { cover: 'Fill', contain: 'Fit', tile: 'Tile', center: 'Centre' };

const clamp = (v, lo, hi, d) => (Number.isFinite(+v) ? Math.min(hi, Math.max(lo, Math.round(+v))) : d);

/** Stored options checked and completed with the defaults. */
export function normalizeOptions(raw) {
  const o = { ...DEFAULTS, ...(raw && typeof raw === 'object' ? raw : {}) };
  return {
    theme: o.theme in THEMES ? o.theme : DEFAULTS.theme,
    eye: Boolean(o.eye), eyeOpacity: clamp(o.eyeOpacity, 0, 100, DEFAULTS.eyeOpacity),
    eyeTrack: Boolean(o.eyeTrack), eyeBlink: Boolean(o.eyeBlink),
    image: typeof o.image === 'string' && /^[0-9a-f]{16}$/.test(o.image) ? o.image : null,
    imageOpacity: clamp(o.imageOpacity, 0, 100, DEFAULTS.imageOpacity),
    imageFit: o.imageFit in FITS ? o.imageFit : DEFAULTS.imageFit,
    imageBlur: clamp(o.imageBlur, 0, 20, DEFAULTS.imageBlur),
    startTab: typeof o.startTab === 'string' ? o.startTab : '',
    notifyFocus: Boolean(o.notifyFocus), notifyRecording: Boolean(o.notifyRecording), notifyGame: Boolean(o.notifyGame),
    refresh: o.refresh in REFRESH ? o.refresh : DEFAULTS.refresh,
    lang: o.lang in LANGS ? o.lang : DEFAULTS.lang,
    numbers: o.numbers in NUMBERS ? o.numbers : DEFAULTS.numbers,
    textSize: clamp(o.textSize, TEXT_MIN, TEXT_MAX, DEFAULTS.textSize),
    shortcuts: Boolean(o.shortcuts),
    hiddenTabs: Array.isArray(o.hiddenTabs) ? o.hiddenTabs.filter((t) => typeof t === 'string' && t !== 'options') : [],
    favCountry: typeof o.favCountry === 'string' && /^[A-Z0-9]{2,4}$/.test(o.favCountry) ? o.favCountry : '',
    cleanupDays: clamp(o.cleanupDays, 0, 3650, 0), cleanupMB: clamp(o.cleanupMB, 0, 100000, 0),
    showOnGame: Boolean(o.showOnGame),
    overlayFields: Array.isArray(o.overlayFields) ? o.overlayFields.filter((f) => f in OVERLAY_FIELDS) : DEFAULTS.overlayFields,
    overlayOpacity: clamp(o.overlayOpacity, 20, 100, DEFAULTS.overlayOpacity),
    playersRail: o.playersRail in PLAYERS_RAIL ? o.playersRail : DEFAULTS.playersRail,
  };
}

let current = null;   // the options in use (read once, then kept up to date by saveOptions)

export function loadOptions() {
  if (current) return current;
  try { current = normalizeOptions(JSON.parse(localStorage.getItem(OPTIONS_KEY))); } catch { current = normalizeOptions(null); }
  return current;
}

/** Read the stored options again (another window of the app - the overlay - changed them). */
export function reloadOptions() {
  current = null;
  return loadOptions();
}

export function saveOptions(options) {
  current = normalizeOptions(options);
  try { localStorage.setItem(OPTIONS_KEY, JSON.stringify(current)); } catch { /* convenience only */ }
}

/** A polling interval of live reading at the chosen pace (Options > Refresh rate). */
export function refreshMs(ms) {
  return Math.round(ms * (REFRESH[loadOptions().refresh]?.[1] ?? 1));
}

/** Locale of numbers (Options > Number format); undefined = Windows' own. */
export function numberLocale() {
  return { en: 'en-US', pl: 'pl-PL', system: undefined }[loadOptions().numbers];
}

/** CSS of the image layer for a fit mode. */
export function fitStyle(fit) {
  return {
    cover: { backgroundSize: 'cover', backgroundRepeat: 'no-repeat', backgroundPosition: 'center' },
    contain: { backgroundSize: 'contain', backgroundRepeat: 'no-repeat', backgroundPosition: 'center' },
    tile: { backgroundSize: 'auto', backgroundRepeat: 'repeat', backgroundPosition: 'top left' },
    center: { backgroundSize: 'auto', backgroundRepeat: 'no-repeat', backgroundPosition: 'center' },
  }[fit] ?? {};
}

const uris = new Map();   // background id -> data: URI (read once per run)

/** The data: URI of a background image (cached). */
export async function backgroundUri(api, id) {
  if (!uris.has(id)) uris.set(id, api.get(`/api/backgrounds/${id}`).then((r) => r.data.uri));
  try { return await uris.get(id); } catch (err) { uris.delete(id); throw err; }
}

let imageLayer = null;

/** Puts the options on the page: theme class, the eye layer, the background image layer. */
export async function applyOptions(options, api, tries = 5) {
  const o = normalizeOptions(options);
  document.body.classList.toggle('theme-classic', o.theme === 'classic');
  document.body.classList.toggle('theme-1984', o.theme === '1984');
  const main = document.querySelector('.main');
  const eye = main?.querySelector('.bg-eye');
  if (eye) {
    eye.hidden = !o.eye;
    eye.style.opacity = String(o.eyeOpacity / 100);
  }
  setEyeOptions({ track: o.eyeTrack, blink: o.eyeBlink });
  try { globalThis.hoi4dbg?.setZoom?.(o.textSize / 100); } catch { /* no bridge (tests) */ }
  document.documentElement.lang = o.lang;
  if (!main) return;
  if (!imageLayer) {
    imageLayer = document.createElement('div');
    imageLayer.className = 'bg-image';
    imageLayer.setAttribute('aria-hidden', 'true');
    main.prepend(imageLayer);
  }
  if (!o.image) {
    imageLayer.hidden = true;
    imageLayer.style.backgroundImage = '';
    return;
  }
  try {
    const uri = await backgroundUri(api, o.image);
    Object.assign(imageLayer.style, fitStyle(o.imageFit), {
      backgroundImage: `url("${uri}")`, opacity: String(o.imageOpacity / 100),
      filter: o.imageBlur ? `blur(${o.imageBlur}px)` : '', inset: o.imageBlur ? `-${o.imageBlur * 2}px` : '0',
    });
    imageLayer.hidden = false;
  } catch (err) {
    imageLayer.hidden = true;   // deleted or unreadable: the page stays as it is
    if (err?.status !== 404 && tries > 1) setTimeout(() => applyOptions(loadOptions(), api, tries - 1), 2000);   // backend starting
  }
}
