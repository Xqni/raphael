const fs = require('fs');
const path = require('path');

class Config {
  constructor() {
    this.sizePx = 180;
    this.opacity = 0.95;
    this.fpsCap = 60;
    this.wsUrl = process.env.RAPHAEL_WS_URL || 'ws://127.0.0.1:8765/ws';
    this.token = process.env.RAPHAEL_ORB_TOKEN || null;
    this.client = 'orb';
    this.clientV = '0.1.0';
    this.reconnectInitial = 5000;
    this.reconnectMax = 30000;
    this.heartbeatInterval = 10000;
    this.loadFromRootConfig();
  }

  loadFromRootConfig() {
    try {
      const root = path.join(__dirname, '..', '..', '..');
      const cfgPath = path.join(root, 'config.yaml');
      if (fs.existsSync(cfgPath)) {
        const txt = fs.readFileSync(cfgPath, 'utf8');
        // minimal parse of orb: and server: if present
        this.sizePx = this.extractInt(txt, /size_px:\s*(\d+)/, this.sizePx);
        this.opacity = this.extractFloat(txt, /opacity:\s*([0-9.]+)/, this.opacity);
        this.fpsCap = this.extractInt(txt, /fps_cap:\s*(\d+)/, this.fpsCap);
        const port = this.extractInt(txt, /port:\s*(\d+)/, 8765);
        this.wsUrl = this.wsUrl || `ws://127.0.0.1:${port}/ws`;
      }
    } catch (e) {
      // ignore
    }
  }

  extractInt(txt, re, def) {
    const m = txt.match(re);
    return m ? parseInt(m[1], 10) : def;
  }
  extractFloat(txt, re, def) {
    const m = txt.match(re);
    return m ? parseFloat(m[1]) : def;
  }
}

module.exports = Config;
