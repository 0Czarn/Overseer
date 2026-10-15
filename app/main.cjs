'use strict';
// Electron main process: starts the Python backend, creates the window, bridges IPC.

const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { app, BrowserWindow, Menu, ipcMain, protocol, net, shell, dialog } = require('electron');
const { startBackend } = require('./backend-process.cjs');
const { forwardApiRequest } = require('./api-bridge.cjs');

const RENDERER_DIR = path.join(__dirname, 'renderer');
const BACKEND_DIR = path.join(__dirname, '..', 'backend');
const SMOKE_DIR = process.env.HOI4DBG_SMOKE_DIR || '';

let backend = null;
let mainWindow = null;
const token = crypto.randomBytes(24).toString('base64url');

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

function serveRenderer() {
  protocol.handle('app', (request) => {
    const { pathname } = new URL(request.url);
    const filePath = path.normalize(path.join(RENDERER_DIR, decodeURIComponent(pathname)));
    if (!filePath.startsWith(RENDERER_DIR + path.sep) || !fs.existsSync(filePath)) {
      return new Response('Not found', { status: 404 });
    }
    return net.fetch(pathToFileURL(filePath).toString());
  });
}

function api(request) {
  if (!backend) return { ok: false, status: 0, body: { error: 'Backend not running' } };
  return forwardApiRequest({ port: backend.port, token }, request);
}

function registerIpc() {
  ipcMain.handle('api:request', (_event, request) => api(request));
  ipcMain.handle('backend:info', () => ({
    running: Boolean(backend),
    python: backend ? [backend.candidate.command, ...backend.candidate.args].join(' ') : null,
    smoke: Boolean(SMOKE_DIR),
  }));
  ipcMain.handle('window:setAlwaysOnTop', (_event, enabled) => {
    mainWindow?.setAlwaysOnTop(Boolean(enabled), 'floating');
    return mainWindow?.isAlwaysOnTop() ?? false;
  });
  ipcMain.handle('window:getState', () => ({ alwaysOnTop: mainWindow?.isAlwaysOnTop() ?? false }));
  ipcMain.handle('shell:openGameLogs', async () => {
    // The path comes from the backend's own detection, never from the renderer.
    const res = await api({ method: 'GET', path: '/api/status' });
    const dir = res.body?.game?.userdata?.logs_dir;
    if (!dir || !fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
      return { ok: false, error: 'HOI4 logs folder not detected' };
    }
    const error = await shell.openPath(dir);
    return error ? { ok: false, error } : { ok: true, path: dir };
  });
  ipcMain.handle('shell:openDataFolder', async () => {
    // The app's data folder (recordings, backgrounds, logs) as the backend reports it, never from the renderer.
    const res = await api({ method: 'GET', path: '/api/status' });
    const dir = res.body?.app?.data_dir;
    if (!dir || !fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return { ok: false, error: 'Data folder not found' };
    const error = await shell.openPath(dir);
    return error ? { ok: false, error } : { ok: true, path: dir };
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 420,
    minHeight: 480,
    backgroundColor: '#0f1318',
    title: 'The OVERSEER',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    autoHideMenuBar: true,
    show: !SMOKE_DIR || process.env.HOI4DBG_SMOKE_SHOW === '1',   // visible smoke run: screenshots of large views
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('app://ui/')) event.preventDefault();
  });
  mainWindow.loadURL('app://ui/index.html');
  if (SMOKE_DIR) {
    require('./smoke.cjs').runSmoke(mainWindow, SMOKE_DIR, (code) => {
      backend?.stop();
      app.exit(code);
    });
  }
}

// Windows shows system notifications (focus alerts) only for an app with a user model id.
if (process.platform === 'win32') app.setAppUserModelId('TheOverseer');

app.whenReady().then(async () => {
  // The default menu's zoom keys would fight the app's own text size (Options, Ctrl+= / Ctrl+- / Ctrl+0): a menu
  // without them, hidden like before (Alt shows it)
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: 'View', submenu: [{ role: 'reload' }, { role: 'forceReload' },
    { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'togglefullscreen' }] }]));
  serveRenderer();
  registerIpc();
  try {
    backend = await startBackend({
      backendDir: BACKEND_DIR,
      token,
      extraArgs: process.env.HOI4DBG_NO_GAME ? ['--no-game'] : [],
      onLog: (stream, line) => console.log(`[backend ${stream}] ${line}`),
    });
    backend.child.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`);
      backend = null;
    });
  } catch (err) {
    console.error(err.message);
    if (!SMOKE_DIR) dialog.showErrorBox('The OVERSEER - backend error', err.message);
  }
  createWindow();
});

app.on('window-all-closed', () => app.quit());
app.on('will-quit', () => backend?.stop());
