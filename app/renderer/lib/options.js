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
};
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
  };
}

export function loadOptions() {
  try { return normalizeOptions(JSON.parse(localStorage.getItem(OPTIONS_KEY))); } catch { return normalizeOptions(null); }
}

export function saveOptions(options) {
  try { localStorage.setItem(OPTIONS_KEY, JSON.stringify(normalizeOptions(options))); } catch { /* convenience only */ }
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
