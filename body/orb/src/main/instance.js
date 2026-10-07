// body/orb/src/main/instance.js — INTERFACES §d instance isolation (orb side).
//
// ONE source of truth for every value that must differ per lane instance:
//   RAPHAEL_INSTANCE unset / 'main'  -> EXACTLY today's behavior (zero change)
//   RAPHAEL_INSTANCE=<lane>          -> derived WS port, CDP port, token path,
//                                       Electron userData (== single-instance key)
//
// Derived from docs/INTERFACES.md §d:
//   ws/REST port : main 8765, lanes 8900 + laneIndex   (orb -> 8906)
//   CDP port     : main 9333, lanes 9400 + laneIndex   (orb -> 9406)
//   data-dir     : main ~/.raphael/  lanes ~/.raphael/<instance>/
//   orb userData : main <electron default>  lanes <data-dir>/orb/
//                  (Electron's requestSingleInstanceLock() is scoped to
//                   userData, so deriving userData derives the LOCK KEY too)
//   token        : <data-dir>/token, falling back to ~/.raphael/token
//
// Nothing here may be hardcoded at a call site — always read the derivation.
const os = require('os');
const fs = require('fs');
const path = require('path');

// Lane order as published in docs/WAVES.md merge order (router .. evolution-persona)
// -> the 8901..8910 / 9401..9410 slots of the §d table.
const LANE_INDEX = {
  router: 1,
  'brain-core': 2,
  'pc-control': 3,
  voice: 4,
  'computer-use': 5,
  orb: 6,
  infra: 7,
  'qa-security': 8,
  'tools-memory': 9,
  'evolution-persona': 10,
};

const MAIN_WS_PORT = 8765;
const MAIN_CDP_PORT = 9333;

function instance() {
  const v = process.env.RAPHAEL_INSTANCE;
  return v && String(v).trim() ? String(v).trim() : 'main';
}

function isMain() {
  return instance() === 'main';
}

function laneIndex() {
  const i = LANE_INDEX[instance()];
  return i === undefined ? 0 : i; // unknown instance name -> main numbering
}

/** WS/REST port of the Brain this orb talks to (INTERFACES §d col 2). */
function wsPort() {
  const env = parseInt(process.env.RAPHAEL_PORT || '', 10);
  if (Number.isFinite(env) && env > 0) return env;
  if (isMain() || laneIndex() === 0) return MAIN_WS_PORT;
  return 8900 + laneIndex();
}

/** DevTools/CDP port for the screenshot + trace harnesses (§d col 7). */
function cdpPort() {
  const env = parseInt(process.env.RAPHAEL_ORB_CDP || '', 10);
  if (Number.isFinite(env) && env > 0) return env;
  if (isMain() || laneIndex() === 0) return MAIN_CDP_PORT;
  return 9400 + laneIndex();
}

/** Per-instance data dir (§d last column). */
function dataDir() {
  if (isMain() || laneIndex() === 0) {
    return path.join(os.homedir(), '.raphael');
  }
  return path.join(os.homedir(), '.raphael', instance());
}

/** Token path — presence check ONLY, never read into a log (AGENT_RULES §7). */
function tokenPath() {
  const candidates = [path.join(dataDir(), 'token')];
  const fallback = path.join(os.homedir(), '.raphael', 'token');
  if (!candidates.includes(fallback)) candidates.push(fallback);
  for (const c of candidates) {
    try { if (fs.existsSync(c)) return c; } catch (e) { /* unreadable -> next */ }
  }
  return candidates[0];
}

/** Token value (may be null when absent). Never log the return value. */
function readToken() {
  const env = process.env.RAPHAEL_ORB_TOKEN;
  if (env) return env;
  try {
    const p = tokenPath();
    if (fs.existsSync(p)) return fs.readFileSync(p, 'utf8').trim();
  } catch (e) { /* missing -> orb stays offline, by design */ }
  return null;
}

/**
 * Electron userData path. MUST be applied with app.setPath('userData', ...)
 * BEFORE app ready — it decides where orb-position.json lives and, because
 * requestSingleInstanceLock() is scoped to userData, it IS the
 * single-instance key (§d "orb single-instance" column).
 * Returns null for `main` -> keep Electron's default (today's behavior).
 */
function userDataDir() {
  if (isMain() || laneIndex() === 0) return null;
  return path.join(dataDir(), 'orb');
}

/** ws:// URL of the Brain (`RAPHAEL_WS_URL` wins, then derivation). */
function wsUrl() {
  const env = process.env.RAPHAEL_WS_URL;
  if (env) return env;
  return `ws://127.0.0.1:${wsPort()}/ws`;
}

function summary() {
  return {
    instance: instance(), wsPort: wsPort(), cdpPort: cdpPort(),
    dataDir: dataDir(), tokenPath: tokenPath(), userData: userDataDir(),
    wsUrl: wsUrl(),
  };
}

module.exports = {
  instance, isMain, laneIndex, wsPort, cdpPort, dataDir,
  tokenPath, readToken, userDataDir, wsUrl, summary,
  LANE_INDEX, MAIN_WS_PORT, MAIN_CDP_PORT,
};
