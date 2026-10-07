const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, screen, shell } = require('electron');

// Capture ANY uncaught main-process error to a file (so errors from launches
// outside the orchestrator's logs are still diagnosable).
process.on('uncaughtException', (err) => {
  try {
    const line = new Date().toISOString() + ' ' + (err && err.stack ? err.stack : String(err)) + '\n';
    fs.appendFileSync(path.join(app.getPath('userData'), 'main-errors.log'), line);
  } catch (e) { /* logging must never throw */ }
  console.error('UNCAUGHT_MAIN', err);
});
const Config = require('./config');
const StatusWS = require('./ws-status');
const Instance = require('./instance');

// Instance isolation (INTERFACES §d): userData MUST be re-pathed before app
// ready — it decides where orb-position.json lives and, because Electron's
// requestSingleInstanceLock() is scoped to userData, it is the per-instance
// SINGLE-INSTANCE KEY (lane `orb` -> ~/.raphael/orb/orb/, main -> default).
// Must happen before anything calls app.getPath('userData').
const INSTANCE_USERDATA = Instance.userDataDir();
if (INSTANCE_USERDATA) app.setPath('userData', INSTANCE_USERDATA);

let win = null;
let tray = null;
let config = null;
let statusWS = null;
let isQuitting = false;

// Track last known position
const POS_FILE = path.join(app.getPath('userData'), 'orb-position.json');

function loadPosition() {
  try {
    if (fs.existsSync(POS_FILE)) {
      const d = JSON.parse(fs.readFileSync(POS_FILE));
      if (d.x !== undefined && d.y !== undefined) {
        return { x: d.x, y: d.y };
      }
    }
  } catch (e) {
    // ignore
  }
  const { screen } = require('electron');
  const p = screen.getPrimaryDisplay().workAreaSize;
  return { x: Math.floor(p.width - 240), y: Math.floor(p.height - 240) };
}

function savePosition(x, y) {
  try {
    const dir = app.getPath('userData');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(POS_FILE, JSON.stringify({ x, y }));
  } catch (e) {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// ROAM: autonomous gentle movement across the current monitor (user feature).
// Every 8-20s pick a random target within the display bounds and glide there
// with ease-in-out. Only in calm states; paused 30s after a user drag; never
// persists mid-glide positions to the position memory.
// ---------------------------------------------------------------------------
const ROAM = {
  minPauseMs: 8000,
  maxPauseMs: 20000,
  margin: 24,
  speed: 90,          // px/s
  minDistance: 60,    // skip near-identical targets
  userHoldMs: 30000,  // pause after manual drag
};
const ROAM_CALM = new Set(['idle', 'listening', 'thinking']);
let topmostWatcher = null; // persistent styling watcher (scripts/topmost-watcher.ps1)

// Spawn the styling watcher at MODULE LOAD (before Electron boots the app):
// compiled EXE (resources/topmost-watcher.exe) starts in ~50ms — PowerShell
// cold-start (~2s) caused the taskbar flash the user reported. Copied to
// Windows TEMP on each launch (WSL interop only executes PEs from DrvFs);
// falls back to the PS script if the copy/exec fails.
if (process.env.WSL_DISTRO_NAME) {
  const { execFile } = require('child_process');
  const watcherRoot = path.join(__dirname, '..', '..', '..'); // body/orb/resources
  const srcExe = path.join(watcherRoot, 'topmost-watcher.exe');
  const startWatcher = (target) => {
    topmostWatcher = execFile(target,
      [], { windowsHide: true }, (_e, out) => {
        if (out && out.trim()) console.log('WATCHER:', out.trim());
      });
    topmostWatcher.stdout && topmostWatcher.stdout.on('data', (d) => {
      const s = d.toString().trim();
      if (s) console.log('WATCHER:', s);
    });
    topmostWatcher.on('error', () => {
      // fallback: PowerShell watcher
      try {
        const psScript = '\\\\wsl.localhost\\' + process.env.WSL_DISTRO_NAME +
          path.join(__dirname, '..', '..', '..').replace(/\//g, '\\') + '\\scripts\\topmost-watcher.ps1';
        topmostWatcher = execFile('powershell.exe',
          ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', psScript],
          { windowsHide: true }, () => {});
      } catch (e) { console.error('WATCHER_FALLBACK_FAILED', e); }
    });
  };
  try {
    let winTemp = null;
    try {
      winTemp = require('child_process')
        .execFileSync('cmd.exe', ['/c', 'echo', '%TEMP%'], { encoding: 'utf8' })
        .replace(/[\r\n]/g, '');
    } catch (e) { winTemp = null; }
    if (winTemp && /^[A-Za-z]:\\/.test(winTemp)) {
      const destLnx = '/mnt/c' + winTemp.slice(2).replace(/\\/g, '/') + '/raphael-watcher.exe';
      const destWin = destLnx; // execFile takes the WSL path; interop runs the PE
      try { require('fs').copyFileSync(srcExe, destLnx); } catch (e) { /* keep existing */ }
      if (require('fs').existsSync(destLnx)) { startWatcher(destWin); }
      else { startWatcher(srcExe); }
    } else {
      startWatcher(srcExe);
    }
  } catch (e) { console.error('WATCHER_SPAWN_FAILED', e); }
}
let roamTimer = null;
let roamAnim = null;
let roaming = false;
let lastProgMoveAt = 0;
let holdUntil = 0;
let lastVisualState = 'idle'; // assume calm until the renderer echoes its state

ipcMain.on('orb-visual-state', (_e, s) => {
  if (typeof s === 'string') lastVisualState = s;
});

// Quintic smootherstep: zero velocity at BOTH ends — soft launch AND a long
// gentle settle (user: the quad ease "felt like it stopped without easing").
function easeInOut2(x) { const t = Math.min(Math.max(x, 0), 1); return t * t * t * (t * (t * 6 - 15) + 10); }

// --- PINNED DOCK (user): top-right of the second monitor; falls back to the
// laptop/primary top-right when the second monitor disconnects (display
// events re-dock). Roam stays available via config orb.roam: true.
function dockTarget(w, h) {
  // Prefer the RIGHTMOST display: that's the user's second monitor (the
  // historically accepted top-right spot at ~x3536); when it disconnects the
  // laptop becomes rightmost -> automatic fallback to laptop top-right.
  const displays = screen.getAllDisplays().slice().sort((a, b) => a.bounds.x - b.bounds.x);
  const target = displays[displays.length - 1];
  const m = 24;
  return {
    x: Math.round(target.bounds.x + target.bounds.width - w - m),
    y: Math.round(target.bounds.y + m),
  };
}
function dockTopRight() {
  if (!win || win.isDestroyed()) return;
  const b = win.getBounds();
  const t = dockTarget(b.width, b.height);
  lastProgMoveAt = Date.now();
  win.setPosition(t.x, t.y);
  savePosition(t.x, t.y);
}

function scheduleRoam(delayMs) {
  if (!config || config.roam === false) return; // pinned mode: no roam cycle
  clearTimeout(roamTimer);
  const d = (delayMs !== undefined)
    ? delayMs
    : ROAM.minPauseMs + Math.random() * (ROAM.maxPauseMs - ROAM.minPauseMs);
  roamTimer = setTimeout(startRoam, d);
}

// All displays' corner spots (user: corners only — she may even cross to the
// laptop screen; 4 corners per display, window-size aware).
function displayCorners(w, h) {
  const pts = [];
  const m = ROAM.margin;
  for (const d of screen.getAllDisplays()) {
    const xs = [d.bounds.x + m, d.bounds.x + d.bounds.width - w - m];
    const ys = [d.bounds.y + m, d.bounds.y + d.bounds.height - h - m];
    for (const x of xs) for (const y of ys) pts.push({ x: Math.round(x), y: Math.round(y) });
  }
  return pts;
}

function startRoam() {
  if (!win || win.isDestroyed() || config.roam === false) return;
  if (!ROAM_CALM.has(lastVisualState) || Date.now() < holdUntil) {
    scheduleRoam();
    return;
  }
  const b = win.getBounds();
  const corners = displayCorners(b.width, b.height);
  if (!corners.length) { scheduleRoam(); return; }
  const distOf = (p) => Math.hypot(p.x - b.x, p.y - b.y);
  const pool = corners.filter((p) => distOf(p) >= 400);
  const target = (pool.length ? pool : corners)[Math.floor(Math.random() * (pool.length ? pool.length : corners.length))];
  if (!target) { scheduleRoam(); return; }
  const dist = distOf(target);
  if (dist < ROAM.minDistance) { scheduleRoam(); return; }

  // Distance physics (user spec): short = SLOW glide; long = faster + MORE
  // motion blur and particle lag. d01 in 0..1 over 3000px.
  const d01 = Math.min(1, dist / 3000);
  const speed = 75 + d01 * 85;                       // 75..160 px/s
  const dur = Math.min(7000, Math.max(1000, (dist / speed) * 1000));
  const lagPx = 14 + d01 * 44;                       // max lag 14..58px (motion blur bump v2)

  // orbital ARC: quadratic bezier bowed perpendicular to the chord (solar feel)
  const mx = (b.x + target.x) / 2;
  const my = (b.y + target.y) / 2;
  let nx = -(target.y - b.y);
  let ny = (target.x - b.x);
  const nl = Math.hypot(nx, ny) || 1;
  const bow = (Math.random() - 0.5) * 0.24 * dist;
  const ctrl = { x: mx + (nx / nl) * bow, y: my + (ny / nl) * bow };

  glideTo(b, target, ctrl, dur, lagPx);
}

function glideTo(from, to, ctrl, durMs, lagPx) {
  // Finite + range validation: Electron's setPosition throws
  // "TypeError: error processing argument at index 1, conversion failure" for
  // NaN AND out-of-int32 values (seen on cross-display hops). Bad frames are
  // skipped; persistent badness aborts the glide cleanly.
  const bad = (v) => !Number.isFinite(v) || Math.abs(v) > 2147483000;
  if (bad(from.x) || bad(from.y) || bad(to.x) || bad(to.y) ||
      bad(ctrl.x) || bad(ctrl.y) || bad(durMs) || bad(lagPx)) {
    console.error('GLIDE_ABORT non-finite input', JSON.stringify({ from, to, ctrl, durMs, lagPx }));
    scheduleRoam();
    return;
  }
  roaming = true;
  const t0 = Date.now();
  let badFrames = 0;
  if (roamAnim) clearInterval(roamAnim);
  roamAnim = setInterval(() => {
    const p = Math.min(1, (Date.now() - t0) / durMs);
    const e = easeInOut2(p);
    const inv = 1 - e;
    const x = inv * inv * from.x + 2 * inv * e * ctrl.x + e * e * to.x;
    const y = inv * inv * from.y + 2 * inv * e * ctrl.y + e * e * to.y;
    if (bad(x) || bad(y)) {
      badFrames++;
      if (badFrames > 5) { // persistently broken: stop instead of spamming errors
        console.error('GLIDE_ABORT non-finite frame', JSON.stringify({ x, y, p, e }));
        clearInterval(roamAnim);
        roamAnim = null;
        roaming = false;
        if (win && !win.isDestroyed() && win.webContents) win.webContents.send('orb-glide', { on: false });
        scheduleRoam();
      }
      return;
    }
    badFrames = 0;
    // velocity direction (bezier derivative) for the renderer's lag/blur
    let vx = 2 * inv * (ctrl.x - from.x) + 2 * e * (to.x - ctrl.x);
    let vy = 2 * inv * (ctrl.y - from.y) + 2 * e * (to.y - ctrl.y);
    const vl = Math.hypot(vx, vy) || 1;
    vx /= vl; vy /= vl;
    const bell = Math.sin(Math.PI * e); // intensity eases in AND out
    lastProgMoveAt = Date.now();
    if (win && !win.isDestroyed()) {
      try {
        win.setPosition(Math.round(x), Math.round(y));
      } catch (err) {
        // conversion failure survived the guard — capture the EXACT values so
        // the next occurrence is diagnosable with data, not speculation
        console.error('SETPOS_FAIL', JSON.stringify({
          x, y, p, e, badFrames,
          from: [from.x, from.y], to: [to.x, to.y], ctrl: [ctrl.x, ctrl.y],
          msg: String(err && err.message),
        }));
        badFrames++;
        return;
      }
    }
    if (win && !win.isDestroyed() && win.webContents) {
      win.webContents.send('orb-glide', { on: true, vx, vy, px: lagPx * bell });
    }
    if (p >= 1) {
      clearInterval(roamAnim);
      roamAnim = null;
      roaming = false;
      if (win && !win.isDestroyed() && win.webContents) win.webContents.send('orb-glide', { on: false });
      savePosition(to.x, to.y);
      // (styling/topmost re-assert after hops = the persistent watcher's job,
      // re-applied within ~100ms of any host-window recreation)
      scheduleRoam();
    }
  }, 8); // 120Hz updates — smoother glide (host samples finer steps)
}

function noteExternalMove() {
  // Called from the 'moved' handler when the movement was NOT ours.
  if (roaming) { // user grabbed mid-glide: abort the glide
    clearInterval(roamAnim);
    roamAnim = null;
    roaming = false;
    if (win && win.webContents) win.webContents.send('orb-glide', { on: false });
  }
  holdUntil = Date.now() + ROAM.userHoldMs;
  scheduleRoam(ROAM.userHoldMs + 2000);
}

function createWindow() {
  const pos = config.roam === true ? loadPosition() : dockTarget(config.sizePx, config.sizePx);
  win = new BrowserWindow({
    x: pos.x,
    y: pos.y,
    width: config.sizePx,
    height: config.sizePx,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    movable: true,
    focusable: true,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // ORB_REBUILD §5: "disable background throttling only for the orb
      // window" — otherwise rAF collapses to ~1 Hz whenever the window is
      // occluded/unfocused and the orb looks frozen (W2.1 cause list).
      backgroundThrottling: false,
    },
  });

  win.setOpacity(config.opacity);
  win.setAlwaysOnTop(true, 'screen-saver');

  const demoMode = process.argv.includes('--demo') || process.env.RAPHAEL_ORB_DEMO === '1';
  // Object form: Electron drops a raw string query like '?demo=1' silently.
  const opts = demoMode ? { query: { demo: '1' } } : {};
  const page = demoMode ? 'demo.html' : 'index.html';
  win.loadFile(path.join(__dirname, '..', 'renderer', page), opts);
  // Sit ON TOP of every other app (user review). 'screen-saver' level is the
  // strongest z-order; full effect on Windows native — WSLg may cap stacking.
  win.setAlwaysOnTop(true, 'screen-saver');
  if (typeof win.setVisibleOnAllWorkspaces === 'function') {
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }
  // Fully click-through by DEFAULT (user: the orb never eats input) but with
  // mouse events FORWARDED, so the renderer can see the pointer and stop being
  // click-through only while the cursor is over the orb itself — otherwise a
  // 280px transparent square would swallow clicks meant for the app below.
  // Toggled by 'orb-mouse-through' (W2.3 right-click menu + typed input).
  win.setIgnoreMouseEvents(true, { forward: true });
  // WSLg: Electron's alwaysOnTop never reaches the host HWND — apply the
  // (styling watcher spawns at module load - see topmostWatcher - so its
  // warmup overlaps Electron's boot and the taskbar never flashes)
  // PINNED DOCK (user): start docked top-right; re-dock when monitors change
  // (second monitor preferred, laptop/primary fallback). Roam = opt-in only.
  setTimeout(dockTopRight, 700);
  screen.on('display-added', () => setTimeout(dockTopRight, 800));
  screen.on('display-removed', () => setTimeout(dockTopRight, 800));
  if (config.roam === true) scheduleRoam(5000);
  // Screenshots are taken externally via DevTools Page.captureScreenshot
  // (see docs/ORB_REBUILD_TASK.md appendix) — never auto-capture or auto-close
  // the app itself; `npm run orb:demo` must stay interactive.

  win.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      win.hide();
    }
  });

  win.on('moved', () => {
    if (win.isDestroyed()) return;
    if (roaming) {
      // moves arriving well after our last programmatic set = user grabbed it
      if (Date.now() - lastProgMoveAt > 250) noteExternalMove();
      return; // never persist mid-glide positions
    }
    const b = win.getBounds();
    savePosition(b.x, b.y);
    if (Date.now() - lastProgMoveAt > 250) noteExternalMove(); // user dragged: hold roaming
  });
}

function createTray() {
  const iconPath = path.join(__dirname, '..', '..', 'assets', 'icon.png');
  let icon = nativeImage.createEmpty();
  try {
    if (fs.existsSync(iconPath)) icon = nativeImage.createFromPath(iconPath);
  } catch (e) {
    // ignore
  }
  tray = new Tray(icon);
  tray.setToolTip('Raphael Orb');
  tray.on('click', () => {
    if (win && win.isVisible()) win.hide();
    else if (win) win.show();
  });
  updateTrayMenu();
}

function updateTrayMenu() {
  const menu = Menu.buildFromTemplate([
    {
      label: 'Show Orb',
      click: () => win && win.show(),
    },
    {
      label: 'Hide Orb',
      click: () => win && win.hide(),
    },
    { type: 'separator' },
    {
      label: 'Private Mode',
      type: 'checkbox',
      checked: statusWS ? statusWS.state.private : false,
      click: (mi) => {
        statusWS && statusWS.sendControl({ action: mi.checked ? 'private_on' : 'private_off' });
      },
    },
    {
      label: 'Pause',
      type: 'checkbox',
      checked: statusWS ? statusWS.state.paused : false,
      click: (mi) => {
        statusWS && statusWS.sendControl({ action: mi.checked ? 'pause' : 'resume' });
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray && tray.setContextMenu(menu);
}

// ---------------------------------------------------------------------------
// W2.3 right-click menu (TODO §3e) — also the only place provider/model are
// surfaced, which is the still-open half of Wave-2 checklist item #1.
// ---------------------------------------------------------------------------
let lastJobs = [];
let mouseThrough = true;   // matches win.setIgnoreMouseEvents initial state

function findLogsDir() {
  const candidates = [
    path.join(__dirname, '..', '..', '..', '..', 'logs'), // repo logs/
    app.getPath('userData'),                             // main-errors.log lives here
  ];
  for (const d of candidates) {
    try { if (fs.existsSync(d)) return d; } catch (e) { /* try next */ }
  }
  return app.getPath('userData');
}

/**
 * The menu as DATA rather than a built Menu, so tests can assert its structure
 * over IPC (`orb-menu-spec`) without popping a native window.
 */
function orbMenuTemplate() {
  const s = statusWS ? statusWS.state : {};
  const jobs = lastJobs.map((j) => ({
    id: 'job-' + (j.job || ''),
    label: `${(j.status || '?').toUpperCase()}  ${String(j.text || j.job || '').slice(0, 42)}`,
    submenu: [{ id: 'cancel-' + (j.job || ''), label: 'Cancel this job', cancel: j.job }],
  }));
  return [
    // INTERFACES §e: provider/model ride every orb_state frame — surfaced here
    { id: 'info-provider', label: `Provider: ${s.provider || '(none yet)'}`, enabled: false },
    { id: 'info-model', label: `Model: ${s.model || '(none yet)'}`, enabled: false },
    { type: 'separator' },
    { id: 'pause', label: s.paused ? 'Resume' : 'Pause', type: 'checkbox',
      checked: !!s.paused, action: s.paused ? 'resume' : 'pause' },
    { id: 'private', label: 'Private Mode', type: 'checkbox',
      checked: !!s.private, action: s.private ? 'private_off' : 'private_on' },
    { type: 'separator' },
    { id: 'jobs', label: jobs.length ? `Jobs (${jobs.length})` : 'Jobs (idle)',
      enabled: jobs.length > 0, submenu: jobs },
    { type: 'separator' },
    { id: 'logs', label: 'Open Logs', action: 'open_logs' },
    { id: 'restart', label: 'Restart Orb', action: 'restart' },
    { id: 'quit', label: 'Quit', action: 'quit' },
  ];
}

function runMenuAction(it) {
  if (it.cancel) { statusWS && statusWS.cancelJob(it.cancel); return; }
  if (!it.action) return;
  if (it.action === 'open_logs') { shell.openPath(findLogsDir()); return; }
  if (it.action === 'restart') { app.relaunch(); app.exit(0); return; }
  if (it.action === 'quit') { isQuitting = true; app.quit(); return; }
  statusWS && statusWS.sendControl({ action: it.action });
}

function popupOrbMenu() {
  const build = (items) => items.map((it) => {
    if (it.type === 'separator') return { type: 'separator' };
    const out = { label: it.label };
    if (it.enabled === false) out.enabled = false;
    if (it.type) out.type = it.type;
    if (it.checked !== undefined) out.checked = it.checked;
    if (it.submenu) { out.submenu = build(it.submenu); if (it.enabled === false) out.enabled = false; }
    else out.click = () => runMenuAction(it);
    return out;
  });
  const menu = Menu.buildFromTemplate(build(orbMenuTemplate()));
  if (win && !win.isDestroyed()) menu.popup({ window: win });
}

function setupIPC() {
  ipcMain.on('orb-input', (_evt, msg) => {
    statusWS && statusWS.sendOrbInput(msg);
  });
  // W2.1 trace: frames the main process received off the WS (evidence chain).
  ipcMain.handle('orb-trace-ws', () => (statusWS ? statusWS.traceFrames() : []));

  // --- W2.3 ---
  ipcMain.on('orb-mouse-through', (_evt, through) => {
    if (!win || win.isDestroyed()) return;
    // forward:true keeps mousemove flowing to the renderer while we are still
    // click-through, which is what lets the orb decide when to become solid.
    mouseThrough = !!through;
    win.setIgnoreMouseEvents(mouseThrough, mouseThrough ? { forward: true } : undefined);
  });
  ipcMain.handle('orb-context-menu', async () => {
    try {
      // refresh the job list first so "Jobs" is not stale on the first open
      statusWS && statusWS.requestJobList();
      await new Promise((r) => setTimeout(r, 150));
      popupOrbMenu();
      return true;
    } catch (e) { return false; }
  });
  ipcMain.handle('orb-menu-spec', () => orbMenuTemplate());
  ipcMain.handle('orb-focus', () => {
    if (win && !win.isDestroyed()) { win.show(); win.focus(); }
    return true;
  });
  ipcMain.handle('orb-command', (_e, text) =>
    (statusWS ? statusWS.sendCommand(String(text || '').slice(0, 300)) : false));
  ipcMain.handle('orb-job-list', () => { statusWS && statusWS.requestJobList(); return lastJobs; });
  ipcMain.handle('orb-cancel', (_e, ref) => (statusWS ? statusWS.cancelJob(ref) : false));
  ipcMain.handle('orb-control', (_e, action) => {
    if (statusWS) statusWS.sendControl({ action });
    return true;
  });
  ipcMain.handle('orb-instance-info', () => ({
    instance: config ? config.instance : 'main',
    sizePx: config ? config.sizePx : 0,
    wsUrl: config ? config.wsUrl : '',
    theme: config ? config.theme : null,
    mouseThrough,   // current setIgnoreMouseEvents state (W2.3 hit-testing)
  }));
}

function startStatusWS() {
  statusWS = new StatusWS(config);
  statusWS.on('state', (_s) => {
    // push to renderer
    if (win && !win.isDestroyed()) {
      win.webContents.send('orb-state', statusWS.getOrbState());
    }
    updateTrayMenu();
  });
  statusWS.on('subtitle', (t) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('subtitle', t);
    }
  });
  statusWS.on('speak', (ev) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('speak', ev);
    }
  });
  statusWS.on('confirm', (c) => {
    if (win && !win.isDestroyed()) win.webContents.send('confirm', c);
  });
  statusWS.on('job_list', (jobs) => {
    lastJobs = Array.isArray(jobs) ? jobs : [];
    if (win && !win.isDestroyed()) win.webContents.send('job-list', lastJobs);
  });
  statusWS.start();
}

app.whenReady().then(async () => {
  // single-instance mutex — ONLY ONE Raphael in the whole system (user rule):
  // a second launch (manual npm run orb:demo, supervisor restart race, etc.)
  // detects the held lock and quits immediately.
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    console.log('SINGLE_INSTANCE: another Raphael orb is already running — this launch quits');
    app.quit();
    return;
  }

  config = new Config();
  createWindow();
  createTray();
  setupIPC();
  startStatusWS();
});

app.on('before-quit', () => {
  isQuitting = true;
  if (topmostWatcher) {
    try { topmostWatcher.kill(); } catch (e) { /* already gone */ }
    topmostWatcher = null;
  }
});

app.on('second-instance', () => {
  if (win) {
    win.show();
    win.focus();
  }
});
