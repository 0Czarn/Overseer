'use strict';
// Desktop integration of the main process (Options): start with Windows (optionally hidden in the tray), the tray
// icon, closing / minimising to the tray, and the overlay window - a small always-on-top window over the game with
// chosen values (app://ui/overlay.html). Settings in <userData>/desktop-options.json: the main process needs them
// before any page loads.

const path = require('node:path');
const fs = require('node:fs');
const { app, BrowserWindow, Menu, Tray, nativeImage } = require('electron');

const DEFAULTS = { openAtLogin: false, startHidden: false, closeToTray: false, minimizeToTray: false,
  overlay: false, overlayLocked: false, overlayBounds: null, navOrder: null };
const HIDDEN_ARG = '--hidden';

let options = { ...DEFAULTS };
let file = null;
let mainWindow = null;
let tray = null;
let overlay = null;
let quitting = false;
let webPreferences = null;

function load() {
  try { options = { ...DEFAULTS, ...JSON.parse(fs.readFileSync(file, 'utf8')) }; } catch { options = { ...DEFAULTS }; }
}

function save() {
  try { fs.writeFileSync(file, JSON.stringify(options, null, 1)); } catch { /* next change tries again */ }
}

function applyLogin() {
  if (process.platform !== 'win32' && process.platform !== 'darwin') return;
  // a development run starts electron.exe with this app's folder; a packaged one only its own exe
  const args = app.isPackaged ? [] : [app.getAppPath()];
  app.setLoginItemSettings({ openAtLogin: options.openAtLogin, path: process.execPath,
    args: options.startHidden ? [...args, HIDDEN_ARG] : args });
}

function showMain() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function trayMenu() {
  return Menu.buildFromTemplate([
    { label: 'Show The OVERSEER', click: showMain },
    { label: 'Overlay over the game', type: 'checkbox', checked: Boolean(overlay), click: (item) => setOverlay(item.checked) },
    { type: 'separator' },
    { label: 'Quit', click: () => { quitting = true; app.quit(); } },
  ]);
}

function ensureTray() {
  if (tray) { tray.setContextMenu(trayMenu()); return; }
  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, 'assets', 'icon.png')).resize({ width: 16, height: 16 }));
  tray.setToolTip('The OVERSEER');
  tray.on('click', showMain);
  tray.setContextMenu(trayMenu());
}

function setOverlay(on) {
  options.overlay = Boolean(on);
  save();
  if (!on) {
    overlay?.close();
    overlay = null;
  } else if (!overlay) {
    const b = options.overlayBounds ?? {};
    overlay = new BrowserWindow({ width: b.width ?? 260, height: b.height ?? 230, x: b.x, y: b.y, minWidth: 160, minHeight: 90,
      frame: false, transparent: true, alwaysOnTop: true, skipTaskbar: true, resizable: true, maximizable: false,
      fullscreenable: false, title: 'The OVERSEER overlay', backgroundColor: '#00000000', webPreferences });
    overlay.setAlwaysOnTop(true, 'screen-saver');   // above a borderless (windowed) game
    overlay.setIgnoreMouseEvents(options.overlayLocked, { forward: true });
    overlay.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    overlay.webContents.on('will-navigate', (event) => event.preventDefault());
    const keep = () => { if (overlay) { options.overlayBounds = overlay.getBounds(); save(); } };
    overlay.on('moved', keep);
    overlay.on('resized', keep);
    overlay.on('closed', () => { overlay = null; if (tray) tray.setContextMenu(trayMenu()); });
    overlay.loadURL('app://ui/overlay.html');
  }
  if (tray) tray.setContextMenu(trayMenu());
  return Boolean(overlay);
}

/** The user's order of the sidebar tabs: tab ids, or null for the default order. */
const checkOrder = (v) => (Array.isArray(v) && v.length <= 64 && v.every((id) => typeof id === 'string' && /^[a-z-]{1,40}$/.test(id)) ? v : null);

function setOptions(patch) {
  for (const key of Object.keys(DEFAULTS)) if (key in (patch ?? {}) && key !== 'overlayBounds') options[key] = patch[key];
  options.navOrder = checkOrder(options.navOrder);
  save();
  applyLogin();
  if (overlay) overlay.setIgnoreMouseEvents(Boolean(options.overlayLocked), { forward: true });
  if (options.closeToTray || options.minimizeToTray || options.startHidden) ensureTray();
  return state();
}

const state = () => ({ ...options, overlay: Boolean(overlay), overlayBounds: undefined });

/** Called once the main window exists. Returns whether it should stay hidden (started with Windows into the tray). */
function setup(win, prefs, ipcMain) {
  mainWindow = win;
  webPreferences = prefs;
  ipcMain.handle('desktop:get', () => state());
  ipcMain.handle('desktop:set', (_e, patch) => setOptions(patch));
  ipcMain.handle('window:show', () => { showMain(); return true; });
  ipcMain.handle('overlay:set', (_e, on) => setOverlay(Boolean(on)));
  win.on('close', (e) => {
    if (!quitting && options.closeToTray) { e.preventDefault(); ensureTray(); win.hide(); }
  });
  win.on('minimize', (e) => {
    if (options.minimizeToTray) { e.preventDefault(); ensureTray(); win.hide(); }
  });
  win.on('closed', () => { overlay?.close(); });
  const hidden = process.argv.includes(HIDDEN_ARG);
  if (hidden || options.closeToTray || options.minimizeToTray) ensureTray();
  if (options.overlay) setOverlay(true);
  return hidden;
}

function init() {
  file = path.join(app.getPath('userData'), 'desktop-options.json');
  load();
  app.on('before-quit', () => { quitting = true; });
}

module.exports = { init, setup, showMain, HIDDEN_ARG };
