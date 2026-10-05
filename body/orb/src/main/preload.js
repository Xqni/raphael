const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('raphael', {
  onOrbState: (cb) => ipcRenderer.on('orb-state', (_e, s) => cb(s)),
  onSubtitle: (cb) => ipcRenderer.on('subtitle', (_e, t) => cb(t)),
  onSpeak: (cb) => ipcRenderer.on('speak', (_e, ev) => cb(ev)),
  sendOrbInput: (msg) => ipcRenderer.send('orb-input', msg),
});

// Expose configuration values to renderer
const Config = require('./config');
const cfg = new Config();
contextBridge.exposeInMainWorld('orbConfig', {
  sizePx: cfg.sizePx,
  opacity: cfg.opacity,
  fpsCap: cfg.fpsCap,
  quality: cfg.quality || 'auto',
  backingDiscAlpha: cfg.backing_disc_alpha || 0.0,
  reducedMotion: cfg.reduced_motion || false,
});
