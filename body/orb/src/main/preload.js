const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('raphael', {
  onOrbState: (cb) => ipcRenderer.on('orb-state', (_e, s) => cb(s)),
  onSubtitle: (cb) => ipcRenderer.on('subtitle', (_e, t) => cb(t)),
  onSpeak: (cb) => ipcRenderer.on('speak', (_e, ev) => cb(ev)),
  sendOrbInput: (msg) => ipcRenderer.send('orb-input', msg),
});
