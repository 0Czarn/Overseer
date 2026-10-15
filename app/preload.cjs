'use strict';
// Minimal, explicit bridge between the sandboxed renderer and the main process.

const { contextBridge, ipcRenderer, webFrame } = require('electron');

contextBridge.exposeInMainWorld('hoi4dbg', {
  request: (method, path, body) => ipcRenderer.invoke('api:request', { method, path, body }),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke('window:setAlwaysOnTop', Boolean(enabled)),
  getWindowState: () => ipcRenderer.invoke('window:getState'),
  openGameLogsFolder: () => ipcRenderer.invoke('shell:openGameLogs'),
  backendInfo: () => ipcRenderer.invoke('backend:info'),
  openDataFolder: () => ipcRenderer.invoke('shell:openDataFolder'),
  // text size (Options): zoom of this window, 0.7 - 1.6
  setZoom: (factor) => webFrame.setZoomFactor(Math.min(1.6, Math.max(0.7, Number(factor) || 1))),
});
