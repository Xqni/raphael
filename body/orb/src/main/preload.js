const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('raphael', {
  onOrbState: (cb) => ipcRenderer.on('orb-state', (_e, s) => cb(s)),
  onSubtitle: (cb) => ipcRenderer.on('subtitle', (_e, t) => cb(t)),
  onSpeak: (cb) => ipcRenderer.on('speak', (_e, ev) => cb(ev)),
  onConfirm: (cb) => ipcRenderer.on('confirm', (_e, c) => cb(c)),
  onNotice: (cb) => ipcRenderer.on('notice', (_e, n) => cb(n)),
  onJobs: (cb) => ipcRenderer.on('orb-jobs', (_e, j) => cb(j)),
  onAnswer: (cb) => ipcRenderer.on('answer', (_e, a) => cb(a)),
  onReport: (cb) => ipcRenderer.on('report', (_e, r) => cb(r)),
  onJobList: (cb) => ipcRenderer.on('job-list', (_e, jobs) => cb(jobs)),
  onGlide: (cb) => ipcRenderer.on('orb-glide', (_e, g) => cb(g)), // velocity feed for lag/blur
  sendOrbInput: (msg) => ipcRenderer.send('orb-input', msg),
  sendOrbState: (s) => ipcRenderer.send('orb-visual-state', s), // main tracks it (roam gating)
  // W2.3 typed input (TODO §3e): text box -> PROTOCOL §3 `command` (source: orb)
  sendCommand: (text) => ipcRenderer.invoke('orb-command', text),
  requestJobList: () => ipcRenderer.invoke('orb-job-list'),
  cancelJob: (ref) => ipcRenderer.invoke('orb-cancel', ref),
  sendControl: (action) => ipcRenderer.invoke('orb-control', action),
  // Right-click menu / hover hit-testing (main owns the native menu)
  openContextMenu: () => ipcRenderer.invoke('orb-context-menu'),
  menuSpec: () => ipcRenderer.invoke('orb-menu-spec'),   // testable, does not popup
  setMouseThrough: (through) => ipcRenderer.send('orb-mouse-through', through),
  focusWindow: () => ipcRenderer.invoke('orb-focus'),
  // W2.1 trace: frames the MAIN process received off the WS
  traceWs: () => ipcRenderer.invoke('orb-trace-ws'),
  // Instance info for the right-click menu header (no secrets)
  instanceInfo: () => ipcRenderer.invoke('orb-instance-info'),
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
  instance: cfg.instance,
  cdpPort: cfg.cdpPort,
  theme: cfg.theme,
  personaTier: cfg.personaTier,
  vibrance: cfg.vibrance,
  motionBlur: cfg.motionBlur,
  startupSpinTauMs: cfg.startupSpinTauMs,
  themeTokens: cfg.themeTokens,
});
