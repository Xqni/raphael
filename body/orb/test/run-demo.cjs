#!/usr/bin/env node
/* Instance-aware demo launcher (`npm run orb:demo`).
 *
 * The DevTools port used to be hardcoded at 9333 in package.json, which is
 * the `main` instance port only (INTERFACES §d). npm scripts cannot compute,
 * so the derivation lives here: RAPHAEL_INSTANCE -> CDP port (orb -> 9406).
 * Unset instance keeps 9333, exactly as before.
 *
 *   npm run orb:demo                      # main instance, port 9333
 *   RAPHAEL_INSTANCE=orb npm run orb:demo # lane instance,  port 9406
 */
const { spawn } = require('child_process');
const path = require('path');
const Instance = require('../src/main/instance');

const cdpPort = Instance.cdpPort();
const electron = path.join(__dirname, '..', 'node_modules', '.bin', 'electron');
const args = ['.', '--demo', `--remote-debugging-port=${cdpPort}`,
              '--no-sandbox', '--disable-gpu-sandbox', '--ignore-gpu-blocklist'];

const child = spawn(electron, args, {
  cwd: path.join(__dirname, '..'),
  stdio: 'inherit',
  env: {
    ...process.env,
    MESA_LOADER_DRIVER_OVERRIDE: process.env.MESA_LOADER_DRIVER_OVERRIDE || 'd3d12',
    GALLIUM_DRIVER: process.env.GALLIUM_DRIVER || 'd3d12',
  },
});

console.log(`[orb:demo] instance=${Instance.instance()} cdp=127.0.0.1:${cdpPort} ` +
            `ws=${Instance.wsUrl()} userData=${Instance.userDataDir() || '(electron default)'}`);

const forward = (sig) => () => { try { child.kill(sig); } catch (e) { /* gone */ } };
process.on('SIGINT', forward('SIGINT'));
process.on('SIGTERM', forward('SIGTERM'));
child.on('exit', (code) => process.exit(code === null ? 1 : code));
