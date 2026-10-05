const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, screen } = require('electron');

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
let reassertTopmost = null; // assigned in createWindow (WSL host re-assert)
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

function scheduleRoam(delayMs) {
  if (!config || config.roam === false) return;
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
  let assertTick = 0;
  if (roamAnim) clearInterval(roamAnim);
  roamAnim = setInterval(() => {
    // mid-glide: the WSLg host can be recreated while crossing displays
    // (shadow returns) — re-assert every ~290ms in-flight (was 700ms = the
    // user-visible ~1s shadow window between moves)
    if (reassertTopmost && ++assertTick >= 18) { assertTick = 0; reassertTopmost(); }
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
      // cross-display hops recreate the WSLg host window (region/topmost drop
      // and the shadow briefly returns) — re-assert immediately AND a few
      // times after landing to catch delayed host recreation.
      if (reassertTopmost) {
        setTimeout(reassertTopmost, 150);
        setTimeout(reassertTopmost, 700);
        setTimeout(reassertTopmost, 2000);
        setTimeout(reassertTopmost, 5000);
      }
      scheduleRoam();
    }
  }, 16); // 60 Hz — smooth steps instead of 33ms chops
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
  const pos = loadPosition();
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
  // WSLg: Electron's alwaysOnTop never reaches the host HWND — apply the
  // PowerToys mechanism (HWND_TOPMOST via scripts/topmost.ps1) on the Windows
  // side, re-asserted periodically. No-op on native Windows (alwaysOnTop works).
  if (process.env.WSL_DISTRO_NAME) {
    const { execFile } = require('child_process');
    const wslRoot = path.join(__dirname, '..', '..', '..', '..');
    const psWin = '\\\\wsl.localhost\\' + process.env.WSL_DISTRO_NAME +
      wslRoot.replace(/\//g, '\\') + '\\scripts\\topmost.ps1';
    const assertTopmost = () => {
      execFile('powershell.exe',
        ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', psWin],
        { windowsHide: true }, () => {});
    };
    win.webContents.once('did-finish-load', () => {
      // Startup: the host window may not be finalized yet (shadow visible on
      // restart) — hammer the region/topmost every 700ms for ~9s, then 10s.
      let fastLeft = 12;
      const fast = () => { assertTopmost(); if (fastLeft-- > 0) setTimeout(fast, 700); };
      setTimeout(fast, 300);
      setInterval(assertTopmost, 10000);
    });
    reassertTopmost = assertTopmost;
  }
  // Start the roam cycle (first hop a few seconds after launch; config roam:false disables).
  if (config.roam !== false) scheduleRoam(5000);
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

function setupIPC() {
  ipcMain.on('orb-input', (_evt, msg) => {
    statusWS && statusWS.sendOrbInput(msg);
  });
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
  statusWS.start();
}

app.whenReady().then(async () => {
  // single-instance mutex
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
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
});

app.on('second-instance', () => {
  if (win) {
    win.show();
    win.focus();
  }
});
