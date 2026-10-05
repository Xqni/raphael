#!/usr/bin/env node
/* Screenshot matrix harness (spec §7 deliverable + checklist §8).
 *
 * Connects to the demo instance over CDP (npm run orb:demo -> port 9333),
 * enumerates the state dropdown, and captures every state x {dark, light,
 * busy} into docs/orb/matrix/<state>--<bg>.png. Also dumps the frame-time
 * governor stats (__orbStats().gov) for PERFORMANCE.md.
 *
 * Usage: node test/orb-matrix.cjs [cdpPort]
 */
const WebSocket = require('ws');
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.argv[2] || '9333', 10);
const OUT_DIR = path.join(__dirname, '..', '..', '..', 'docs', 'orb', 'matrix');
const BGS = ['dark', 'light', 'busy'];
const SETTLE_MS = 900;

function cdpTarget(port) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port, path: '/json' }, (res) => {
      let b = '';
      res.on('data', (c) => (b += c));
      res.on('end', () => {
        try {
          const list = JSON.parse(b);
          const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
          if (page) resolve(page.webSocketDebuggerUrl);
          else reject(new Error('no page target'));
        } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function main() {
  const url = await cdpTarget(PORT);
  const ws = new WebSocket(url, { perMessageDeflate: false });
  let nextId = 1;
  const pending = new Map();
  ws.on('message', (raw) => {
    const msg = JSON.parse(raw);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message));
      else resolve(msg.result);
    }
  });
  await new Promise((r) => ws.on('open', r));
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  await send('Page.enable');
  await send('Runtime.enable');
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'eval failed');
    return r.result.value;
  };

  const states = await evalJs(
    "Array.from((document.getElementById('stateSelect')||{options:[]}).options).map(o=>o.value)"
  );
  console.log('states:', states.join(','));

  fs.mkdirSync(OUT_DIR, { recursive: true });
  let count = 0;
  for (const state of states) {
    for (const bg of BGS) {
      await evalJs(`window.__orbDemo.setBg(${JSON.stringify(bg)})`);
      await evalJs(`window.__orbDemo.setState(${JSON.stringify(state)})`);
      await new Promise((r) => setTimeout(r, SETTLE_MS));
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      const file = path.join(OUT_DIR, `${state}--${bg}.png`);
      fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
      count++;
      process.stdout.write(`shot ${count}: ${state} / ${bg}\n`);
    }
  }

  // leave the orb in a neutral state + bg
  await evalJs(`window.__orbDemo.setBg('transparent')`);
  await evalJs(`window.__orbDemo.setState('idle')`);
  await new Promise((r) => setTimeout(r, 1500));
  const stats = await evalJs('JSON.stringify(window.__orbStats())');
  console.log('STATS:', stats);
  ws.close();
  console.log(`DONE: ${count} screenshots -> ${OUT_DIR}`);
}

main().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
