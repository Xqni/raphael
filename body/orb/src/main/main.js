const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, screen } = require('electron');
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
let roamTimer = null;
let roamAnim = null;
let roaming = false;
let lastProgMoveAt = 0;
let holdUntil = 0;
let lastVisualState = 'idle'; // assume calm until the renderer echoes its state

ipcMain.on('orb-visual-state', (_e, s) => {
  if (typeof s === 'string') lastVisualState = s;
});

function easeInOut2(x) { return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; }

function scheduleRoam(delayMs) {
  if (!config || config.roam === false) return;
  clearTimeout(roamTimer);
  const d = (delayMs !== undefined)
    ? delayMs
    : ROAM.minPauseMs + Math.random() * (ROAM.maxPauseMs - ROAM.minPauseMs);
  roamTimer = setTimeout(startRoam, d);
}

function startRoam() {
  if (!win || win.isDestroyed() || config.roam === false) return;
  if (!ROAM_CALM.has(lastVisualState) || Date.now() < holdUntil) {
    scheduleRoam();
    return;
  }
  const b = win.getBounds();
  const disp = screen.getDisplayMatching(b);
  const m = ROAM.margin;
  const minX = disp.bounds.x + m;
  const maxX = disp.bounds.x + disp.bounds.width - b.width - m;
  const minY = disp.bounds.y + m;
  const maxY = disp.bounds.y + disp.bounds.height - b.height - m;
  if (maxX <= minX || maxY <= minY) { scheduleRoam(); return; }
  const tx = Math.round(minX + Math.random() * (maxX - minX));
  const ty = Math.round(minY + Math.random() * (maxY - minY));
  const dist = Math.hypot(tx - b.x, ty - b.y);
  if (dist < ROAM.minDistance) { scheduleRoam(); return; }
  const dur = Math.min(5000, Math.max(900, (dist / ROAM.speed) * 1000));
  glideTo(b.x, b.y, tx, ty, dur);
}

function glideTo(x0, y0, x1, y1, durMs) {
  roaming = true;
  const t0 = Date.now();
  if (roamAnim) clearInterval(roamAnim);
  roamAnim = setInterval(() => {
    const p = Math.min(1, (Date.now() - t0) / durMs);
    const e = easeInOut2(p);
    lastProgMoveAt = Date.now();
    win.setPosition(Math.round(x0 + (x1 - x0) * e), Math.round(y0 + (y1 - y0) * e));
    if (p >= 1) {
      clearInterval(roamAnim);
      roamAnim = null;
      roaming = false;
      savePosition(x1, y1); // persist the resting spot only
      scheduleRoam();
    }
  }, 33);
}

function noteExternalMove() {
  // Called from the 'moved' handler when the movement was NOT ours.
  if (roaming) { // user grabbed mid-glide: abort the glide
    clearInterval(roamAnim);
    roamAnim = null;
    roaming = false;
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
      setTimeout(assertTopmost, 800);
      setInterval(assertTopmost, 30000);
    });
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
