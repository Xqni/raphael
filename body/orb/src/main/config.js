const fs = require('fs');
const path = require('path');
const Instance = require('./instance');

const ROOT = path.join(__dirname, '..', '..', '..', '..');

class Config {
  constructor() {
    this.sizePx = 180;
    this.opacity = 0.95;
    this.fpsCap = 60;
    // Instance isolation (INTERFACES §d): port + token path derive from
    // RAPHAEL_INSTANCE — never hardcoded. Explicit env always wins.
    this.wsUrl = Instance.wsUrl();
    this.token = Instance.readToken();   // presence-only; never logged
    this.instance = Instance.instance();
    this.cdpPort = Instance.cdpPort();
    this.client = 'orb';
    this.clientV = '0.1.0';
    this.reconnectInitial = 5000;
    this.reconnectMax = 30000;
    this.heartbeatInterval = 10000;
    // Fidelity-pass defaults (overridden by config.yaml / config.d/*.yaml)
    this.theme = 'raphael';        // raphael | ciel | custom  (docs/orb/THEMES.md)
    this.vibrance = 1.15;          // 0.8 .. 1.5
    this.motionBlur = 'auto';      // auto | off | low | high
    this.startupSpinTauMs = 1400;  // exponential spin-down tau (spec §1)
    // Palette tokens for orb.theme (defaults = the Raphael palette)
    this.themeTokens = {
      core_tint: '#FFFFFF',
      haze_lime: '#B8E02A',
      haze_teal: '#2DD4BF',
      haze_blue: '#3B82F6',
      haze_magenta: '#C026D3',
      ring_color: '#FFFFFF',
      glyph_color: '#FFB000',
      accent: '#2DD4BF',
    };
    this.loadFromRootConfig();
  }

  /**
   * config.yaml first, then config.d/*.yaml sorted by filename — the same
   * order INTERFACES §c defines for brain-core's loader, so the orb and the
   * Brain always agree on what the config says. Later files win per key.
   * (Flat-key regex extraction: a key present in a file overrides, absent
   * keys leave the previous value untouched — equivalent to a deep-merge for
   * the scalar keys the orb reads.)
   */
  loadFromRootConfig() {
    const files = [];
    const base = path.join(ROOT, 'config.yaml');
    if (fs.existsSync(base)) files.push(base);
    const dd = path.join(ROOT, 'config.d');
    try {
      if (fs.existsSync(dd)) {
        for (const f of fs.readdirSync(dd).sort()) {
          if (f.endsWith('.yaml') || f.endsWith('.yml')) files.push(path.join(dd, f));
        }
      }
    } catch (e) { /* unreadable config.d -> base only */ }

    for (const file of files) {
      let txt;
      try { txt = fs.readFileSync(file, 'utf8'); } catch (e) { continue; }
      this._apply(txt);
    }
    this.vibrance = Math.min(1.5, Math.max(0.8, this.vibrance));
  }

  _apply(rawTxt) {
    // Strip YAML comments first: `reduced_motion: true` written inside a
    // comment line must never configure anything (caught by a real run — the
    // fidelity-pass note in config.d/orb.yaml flipped it to true).
    const txt = rawTxt
      .replace(/^[ \t]*#[^\n]*/gm, '')          // full-line comments
      .replace(/(^|\s)#[^\n]*/g, '$1');          // inline comments (a quoted
                                                 // "#RRGGBB" has no space
                                                 // before the #, so tokens stay)
    this.sizePx = this._int(txt, /size_px:\s*(\d+)/, this.sizePx);
    this.content_px = this._int(txt, /content_px:\s*(\d+)/, this.content_px || 200);
    this.opacity = this._float(txt, /opacity:\s*([0-9.]+)/, this.opacity);
    this.fpsCap = this._int(txt, /fps_cap:\s*(\d+)/, this.fpsCap);
    this.quality = this._str(txt, /quality:\s*(auto|low|medium|high)/, this.quality || 'auto');
    this.backing_disc_alpha = this._float(txt, /backing_disc_alpha:\s*([0-9.]+)/, this.backing_disc_alpha || 0.0);
    this.reduced_motion = this._bool(txt, /reduced_motion:\s*(true|false)/, this.reduced_motion || false);
    this.roam = this._bool(txt, /roam:\s*(true|false)/, this.roam === undefined ? false : this.roam);
    // NB: no port extraction here — the WS port comes from the instance
    // derivation (INTERFACES §d), never from a hardcoded yaml regex.
    // Fidelity pass
    this.theme = this._str(txt, /theme:\s*(raphael|ciel|custom)/, this.theme);
    this.vibrance = this._float(txt, /vibrance:\s*([0-9.]+)/, this.vibrance);
    this.motionBlur = this._str(txt, /motion_blur:\s*(auto|off|low|high)/, this.motionBlur);
    this.startupSpinTauMs = this._int(txt, /spin_tau_ms:\s*(\d+)/, this.startupSpinTauMs);
    // Palette tokens (docs/orb/THEMES.md) — only present under orb.custom_theme,
    // so the defaults above survive unless a theme block really overrides them.
    for (const k of Object.keys(this.themeTokens)) {
      const re = new RegExp(k + ':\\s*"?#?([0-9a-fA-F]{6})"?');
      this.themeTokens[k] = this._hex(txt, re, this.themeTokens[k]);
    }
  }

  _hex(txt, re, def) { const m = txt.match(re); return m ? '#' + m[1].toUpperCase() : def; }

  _int(txt, re, def) { const m = txt.match(re); return m ? parseInt(m[1], 10) : def; }
  _float(txt, re, def) { const m = txt.match(re); return m ? parseFloat(m[1]) : def; }
  _bool(txt, re, def) { const m = txt.match(re); return m ? (m[1] === 'true') : def; }
  _str(txt, re, def) { const m = txt.match(re); return m ? m[1] : def; }
}

module.exports = Config;
