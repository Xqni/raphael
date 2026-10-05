const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage } = require('electron');
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
    if (!win.isDestroyed()) {
      const b = win.getBounds();
      savePosition(b.x, b.y);
    }
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
