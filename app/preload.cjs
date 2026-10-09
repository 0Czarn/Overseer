'use strict';
// Minimal, explicit bridge between the sandboxed renderer and the main process.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('hoi4dbg', {
  request: (method, path, body) => ipcRenderer.invoke('api:request', { method, path, body }),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke('window:setAlwaysOnTop', Boolean(enabled)),
  getWindowState: () => ipcRenderer.invoke('window:getState'),
  openGameLogsFolder: () => ipcRenderer.invoke('shell:openGameLogs'),
  backendInfo: () => ipcRenderer.invoke('backend:info'),
});
