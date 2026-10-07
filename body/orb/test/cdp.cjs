// Minimal CDP client for the orb lane (no deps beyond `ws`, which ships with
// the orb). Used by every harness in body/orb/test/: it gives you an eval()
// and a screenshot() against the FIRST page target on the DevTools port.
//
//   const cdp = await connect(port);
//   const fps = await cdp.evaluate('window.__orbStats().frame');
//   const png = await cdp.screenshot();
//   await cdp.close();
//
// Screenshots are the ONLY reliable capture path for the orb's WebGL surface
// (WSLg never presents the window to the Windows desktop and x11grab is blind
// to GL surfaces) — see docs/ORB_REBUILD_TASK.md appendix item 3.
const WebSocket = require('ws');
const http = require('http');

function listTargets(port) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/json' }, (res) => {
      let b = '';
      res.on('data', (c) => (b += c));
      res.on('end', () => {
        try { resolve(JSON.parse(b)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.setTimeout(2000, () => { req.destroy(new Error('cdp /json timeout')); });
  });
}

async function findTarget(port, tries = 40) {
  let lastErr = new Error('no target');
  for (let i = 0; i < tries; i++) {
    try {
      const list = await listTargets(port);
      const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
      if (page) return page;
      lastErr = new Error('page target not listed yet');
    } catch (e) { lastErr = e; }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw lastErr;
}

async function connect(port) {
  const target = await findTarget(port);
  const ws = new WebSocket(target.webSocketDebuggerUrl, { perMessageDeflate: false });
  let nextId = 1;
  const pending = new Map();
  const listeners = [];
  ws.on('message', (raw) => {
    const msg = JSON.parse(raw.toString());
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message));
      else resolve(msg.result);
      return;
    }
    if (msg.method) for (const fn of listeners) fn(msg);
  });
  await new Promise((resolve, reject) => {
    ws.once('open', resolve);
    ws.once('error', reject);
  });

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  await send('Page.enable');
  await send('Runtime.enable');

  return {
    ws,
    target,
    send,
    onEvent: (fn) => listeners.push(fn),
    async evaluate(expression) {
      const r = await send('Runtime.evaluate', {
        expression, returnByValue: true, awaitPromise: true,
      });
      if (r.exceptionDetails) {
        throw new Error('eval failed: ' + (r.exceptionDetails.exception
          ? r.exceptionDetails.exception.description : r.exceptionDetails.text));
      }
      return r.result.value;
    },
    async evaluateJson(expression) {
      const v = await this.evaluate(expression);
      return typeof v === 'string' ? JSON.parse(v) : v;
    },
    async screenshot() {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      return Buffer.from(shot.data, 'base64');
    },
    close() { try { ws.close(); } catch (e) { /* already closed */ } },
  };
}

/** Mean absolute per-pixel difference (0..255) of two raw RGBA buffers. */
function meanAbsDiff(a, b) {
  if (!a || !b || a.length !== b.length) return 255;
  let sum = 0;
  // sample every pixel (harness images are small — 320x320 ≈ 100k px)
  for (let i = 0; i < a.length; i += 4) {
    sum += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
  }
  const px = a.length / 4;
  return sum / (px * 3);
}

/** Share (0..1) of pixels whose RGB moved by more than `perChanThreshold`. */
function changedPixelRatio(a, b, perChanThreshold = 8) {
  if (!a || !b || a.length !== b.length) return 1;
  let changed = 0;
  for (let i = 0; i < a.length; i += 4) {
    const d = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
    if (d > perChanThreshold * 3) changed++;
  }
  return changed / (a.length / 4);
}

module.exports = { connect, findTarget, listTargets, meanAbsDiff, changedPixelRatio };
