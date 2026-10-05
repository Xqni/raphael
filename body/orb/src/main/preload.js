const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('raphael', {
  onOrbState: (cb) => ipcRenderer.on('orb-state', (_e, s) => cb(s)),
  onSubtitle: (cb) => ipcRenderer.on('subtitle', (_e, t) => cb(t)),
  onSpeak: (cb) => ipcRenderer.on('speak', (_e, ev) => cb(ev)),
  sendOrbInput: (msg) => ipcRenderer.send('orb-input', msg),
  sendOrbState: (s) => ipcRenderer.send('orb-visual-state', s), // main tracks it (roam gating)
  onGlide: (cb) => ipcRenderer.on('orb-glide', (_e, g) => cb(g)), // velocity feed for lag/blur
});

// Expose configuration values to renderer
const Config = require('./config');
const cfg = new Config();
contextBridge.exposeInMainWorld('orbConfig', {
  sizePx: cfg.sizePx,
  contentPx: cfg.content_px,
  opacity: cfg.opacity,
  fpsCap: cfg.fpsCap,
  quality: cfg.quality || 'auto',
  backingDiscAlpha: cfg.backing_disc_alpha || 0.0,
  reducedMotion: cfg.reduced_motion || false,
});
