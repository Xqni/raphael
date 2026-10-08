# ARCH-1 — Windows-native Electron orb: migration plan (PLAN ONLY)

**Status: PLAN. No code, no installs, no prototype.** The prototype is gated on
explicit human approval to bring a native Node/Electron toolchain up on Windows —
raised as `coord user_attention` (packet `docs/audit-tasks/orb.md`, ARCH-1 P1).
The WSLg path stays fully working and fully gated until native parity passes.

Research backing this document: `.opencode/research/windows-native-electron-orb.md`
(every non-obvious claim cited; anything unverified is marked as such and pushed
into §9 "needs prototype").

---

## 0. Verdict

**Recommended: yes, migrate — but as a second, parallel path, not a switch.**
The WSLg path does not merely add latency; it exists only because the orb is a
Linux process shown through an RDP stream, and the compensations for that are
scattered across four mechanisms that a native window deletes outright:

| WSLg compensation today | What it works around | Native equivalent |
|---|---|---|
| `scripts/wslg-shadow/weston-wrapper` (`WESTON_RDP_WINDOW_SHADOW_REMOTING=0`) | Weston bakes a drop shadow into every surface | nothing needed |
| `scripts/wslg-shadow/{install.sh,boot-hook.sh,raphael-wslg-shadow.service}` | the system-distro overlay **resets on every `wsl --shutdown`**, so the wrapper must be re-installed at boot | nothing needed |
| `scripts/topmost.ps1` run every 30 s from `main.js` | WSLg windows are not topmost and carry a DWM shadow | `setAlwaysOnTop(true)` + `thickFrame:false` |
| `topmost.ps1` inner `SetWindowRgn` clip | WSLg bakes a **~32 px shadow margin INSIDE** the surface (344×344 host for a 280 px app) — no DWM API can remove it | nothing needed |
| msrdc/RDP streaming + `vmwp` copy every frame | presentation layer | direct DWM compose |

That is the entire argument: the native build does not need a shadow kill-switch,
a 30-second topmost re-applier, a region clip, or a boot service to reinstall any
of them.

---

## 1. Required Windows Node version

| Question | Answer | Source |
|---|---|---|
| Node already on this box? | **YES — `C:\Program Files\nodejs\node.exe` = `v24.1.0`** (verified by running it; file dated 2025-05-20) | measured here |
| What Node does Electron need? | Electron embeds its own Node. **Electron 44 (current stable, Oct 2026) embeds Node v24.18.1** (Chromium 152). So Node 24 is the correct line — the system install already matches it. | electronjs.org/blog/electron-44-0 |
| Build tooling floor | electron-builder v27 and `@electron/rebuild` both require **Node ≥ 22.12.0** (`require(esm)` stabilization). Node 24.1.0 satisfies this. | electron.build/docs/migration/v27 |
| The real trap: **ABI** | Electron has its own `NODE_MODULE_VERSION`. **Electron 44 = ABI 149, Node 24 = ABI 137** — a native module prebuilt for `node` will not load in Electron. Every native module must be rebuilt with `@electron/rebuild` against Electron headers. | node-abi `abi_registry.json` |
| Windows-specific native-module gotcha | keep `win_delay_load_hook: true` in `binding.gyp` (Electron ≥4 exports symbols from `electron.exe`, not `node.dll`) or you get "Module did not self-register". | Electron native-modules docs |

**Conclusion:** *no Node install is required* — v24.1.0 is already present and is
the right major line. What the ATTENTION actually asks permission for is the
**prototype itself**: downloading the ~100 MB Electron dist onto Windows,
running an unsigned `electron.exe` (SmartScreen will prompt), and binding an
ephemeral test port.

> Verdict for the audit: **ALREADY-DONE** (Node on Windows) / **PLAN** (prototype).

---

## 2. Config path handling

The orb reads repo-root `config.yaml` then sorted `config.d/*.yaml`
(`src/main/config.js:57-75`, `main.js:530-531` `CONFIG_ROOT = path.join(__dirname,'..','..','..','..')`).
That 4-level `__dirname` climb is **WSL/repo-layout specific** and is the first
thing a packaged build breaks: inside an asar there is no repo root.

Proposed resolution order (first hit wins), preserving today's behaviour exactly
in the dev layout:

1. **Explicit override** — `RAPHAEL_CONFIG_DIR` env or `--config-dir=` argv flag.
2. **Dev layout (unchanged)** — `app.getAppPath()` / repo root: read
   `config.yaml` + `config.d/*.yaml` directly. This is what every current test
   uses, so the gate results below stay valid.
3. **Portable layout** — `config.yaml` sitting next to `process.execPath`
   (electron-builder `portable` target); treat that directory as `CONFIG_ROOT`.
4. **Installed layout** — `%APPDATA%\Raphael\config.yaml` + `config.d\`, with
   packaged defaults shipped via `extraResources` (read-only) and layered on top.

Merge order: packaged defaults → user config dir → env overrides; `config.d`
stays lexicographically sorted for determinism (same as
`INTERFACES §c`, which is what keeps orb and Brain agreeing).

Other path facts to bake in:
- `app.getPath('userData')` = `%APPDATA%\<app>` on Windows; **write into a
  subdirectory** (Chromium already owns `Cache`, `GPUCache`, `Local Storage`
  there).
- Caches / large state → `LOCALAPPDATA` (read `process.env.LOCALAPPDATA`; Electron
  has no `getPath('localAppData')`).
- asar is read-only at runtime — never expect to write config inside the app dir.
- Instance isolation (`RAPHAEL_INSTANCE` → userData, ports, token path) is already
  driven by `src/main/instance.js` and is env-derived, so it survives the move
  unchanged — **but** `requestSingleInstanceLock()` is scoped to `userData`, so
  `Instance.userDataDir()` must keep re-pathing **before** `app.ready`
  (`main.js:23-25`), exactly as it does today.

---

## 3. Token delivery (never argv / never plain env)

**Why argv is disqualified:** `Win32_Process.CommandLine` is readable by any user
via WMI (`Get-CimInstance Win32_Process`) and shown in Task Manager → Details →
"Command line". Electron adds a second leak: `requestSingleInstanceLock()`
forwards the **second instance's argv into the first** via the `second-instance`
event — so a token in argv reaches the primary process's handler too.

**Why plain env is only half a defence:** env blocks are not exposed via WMI, but
any process running as the **same user** can read another process's environment
with `PROCESS_VM_READ` (no admin required). It protects against other users, not
against same-user code.

**Proposed pipeline (two stages):**

1. **Per-launch handoff — stdin or a user-DACL'd named pipe.**
   - *stdin* is best: nothing touches any OS query surface. Caveat: GUI-subsystem
     processes launched from Explorer/shortcuts have **invalid stdin**, so stdin
     only works when a launcher (the supervisor / an agent) spawns the orb.
   - *Named pipe* as the fallback: Node's `net` module supports
     `\\.\pipe\<name>` on Windows. Create the pipe **before** spawning, with an
     explicit `SECURITY_ATTRIBUTES` DACL granting only the current user SID —
     otherwise there is a pipe-squatting race. Pipe ACLs are the 0600-equivalent.
2. **At-rest persistence — Electron `safeStorage`.** On Windows the key is
   generated via **DPAPI**; store the base64 blob under `userData`. Electron's own
   docs state it protects "from other users on the same machine, but not from
   other apps running in the same userspace" — the same honest limit applies to
   plain DPAPI and to `icacls` ACLs, so this is not a regression, it is the
   correct ceiling on a single-user box.

Rejected alternatives, for the record: **Credential Manager** (`cmdkey`) cannot
read values back without a native `CredRead` binding — no Electron built-in;
**`icacls`-hardened token file** is plaintext at rest and ACLs are a multi-user
boundary, not a same-user one.

**Rules that carry over unchanged (PROTOCOL §11):** never in logs, never in the
orb UI, never in a WS frame after `auth`. The orb already proves this pattern —
F-4 reads `GET /status` with `Authorization: Bearer <token>` from
`refreshStatus()` (`main.js`), and the mock-brain test asserts only the header's
*presence*, never its value.

---

## 4. Always-on-top and click-through

Proposed native window recipe:

```js
frame: false, transparent: true, backgroundColor: '#00000000',
alwaysOnTop: true,          // level: see table below
focusable: false,           // WS_EX_NOACTIVATE + implies skipTaskbar
thickFrame: false,          // documented DWM-shadow + animation killer
roundedCorners: false, backgroundMaterial: 'none',
resizable: false, fullscreenable: false, skipTaskbar: true,
webPreferences: { backgroundThrottling: false }   // THIS window only
```

| Behaviour | Native mechanism | Note |
|---|---|---|
| Always on top | `setAlwaysOnTop(true, level)` | On Windows **every** always-on-top window is topmost; the level is effectively an **above/below-taskbar** switch. Electron source: `floating`…`status` → *behind* the taskbar; `pop-up-menu` / `screen-saver` → *above* it. There are no distinct z-bands. |
| DWM shadow (the thing `topmost.ps1` strips) | `thickFrame: false` | Documented: "removes window shadow and window animations". This is the direct replacement for the 30-second PowerShell re-applier **and** for the region clip, since the ~32 px baked margin is a WSLg artefact that will not exist. |
| Click-through | `setIgnoreMouseEvents(true, { forward: true })` | Verified in source: sets `WS_EX_TRANSPARENT \| WS_EX_LAYERED`; `forward` re-enables `mousemove`/`mouseenter`/`mouseleave` so hover-detection still works. This is exactly the current `mouseThrough` contract in `main.js`. |
| **Do NOT use** the legacy hack | `app.disableHardwareAcceleration()` / `--disable-gpu-compositing` | Historically made transparent pixels click-through — **broken since Chromium 139 / Electron 38**; restoring it needs `--disable-direct-composition` and forces the GDI path, **killing WebGL** (#48064). Fatal for this orb. |
| Taskbar | `setSkipTaskbar(true)` | = `ITaskbarList::DeleteTab` (source-verified), **not** `WS_EX_TOOLWINDOW`. |
| **Alt-Tab exclusion** | `focusable: false` → `WS_EX_NOACTIVATE` prevents activation but does **not provably** exclude the window from Alt-Tab | If the prototype shows it in Alt-Tab, the only Win32 answer is `WS_EX_TOOLWINDOW`, reachable via a native module. **Open item.** |

Known residual minefield (all Electron issues, sized for a small always-present orb):
phantom titlebar on blur (#39959), **white inactive-frame corners on focus loss
(#51662 — the one directly in our threat model)**, transparency destroyed by
toggling `setResizable()` (#51175), transparency not respected on some setups
(#40515), DevTools breaks transparency (by design), and transparent windows
require DWM to be enabled.

`forward: true` has a flaky history (#33281, #30808, #35030 — one of them affected
*other apps'* drag behaviour). Treat hover-forward as "works on current stable,
needs a regression test", not as a given.

---

## 5. Multi-monitor / DPI

- All `BrowserWindow` geometry (`setPosition`, `getBounds`) and `screen` point
  APIs are **DIP**; physical = DIP × `Display.scaleFactor`. Mixing `getBounds()`
  (DIP) with `GetWindowRect` off `getNativeWindowHandle()` (physical) without
  `screenToDipRect`/`dipToScreenRect` is the classic bug.
- Modern Chromium declares **PerMonitorV2** DPI awareness by default — there is
  **no `app.enableHostRuntime` API** (that name does not exist in Electron's
  docs). Verify empirically on the target box: `Get-Process electron |
  Select DPIAwareness`. Marked UNVERIFIED.
- **The mixed-DPI trap:** a window straddling two monitors with different scale
  factors gets `WM_DPICHANGED` and Chromium applies **one** scale to the whole
  window — a persisted DIP coordinate can land on the wrong display or off-screen
  (#10862).
- **Persist-dragged-position pattern** (what `orb-position.json` must become):
  on `'move'` (DIP), debounce and store `{x, y, displayId, scaleFactor}`. On
  restore, `screen.getDisplayNearestPoint({x, y})`; if that display is gone
  (`'display-removed'` / `'display-metrics-changed'` with `scaleFactor` in
  `changedMetrics`), re-clamp into `display.workArea` — anchor on the primary
  rather than trusting stale coordinates.
- Events to subscribe: `'display-added'`, `'display-removed'`,
  `'display-metrics-changed'` (`changedMetrics` ∈ bounds, workArea, scaleFactor,
  rotation).

**Parity note:** drag + persistence is already tested today via `orb:trace`'s
interaction phase (hit-testing) and the position file; those tests must be
re-pointed at the native run for parity, not rewritten.

---

## 6. GPU flags

| Flag | Verdict |
|---|---|
| `frame:false` + `transparent:true` + `backgroundColor:'#00000000'` | required (transparent *requires* frameless on Windows) |
| **keep hardware acceleration ON** | mandatory — WebGL |
| `appendSwitch('disable-features','CalculateNativeWinOcclusion')` | **recommended.** Chromium's native occlusion tracker stops rendering + throttles JS when it thinks the window is covered; explicitly disabling it is confirmed effective in Electron (#29280). **Gotcha: `appendSwitch('disable-features', …)` clobbers any existing value — merge/dedupe manually.** Whether Electron 44 enables occlusion tracking by default is UNVERIFIED; the switch is cheap insurance either way. |
| `--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows` | recommended |
| `webPreferences: { backgroundThrottling: false }` | **scoped to the orb window ONLY.** A real app measured a *global* `backgroundThrottling:false` at **~20% idle CPU burn** (hermes-agent). This is the single biggest idle-cost risk in the whole plan. |
| `--enable-gpu-rasterization`, `--enable-zero-copy` | optional, measure before keeping |
| `--use-gl=angle --use-angle=d3d11` | Windows-only; modern Chromium already defaults to ANGLE/D3D11 — set only for driver debugging |
| `app.disableHardwareAcceleration()`, `--disable-gpu`, `--in-process-gpu` | **avoid** (first two break WebGL; third widens crash blast radius) |
| `--force_high_performance_gpu` / `--force_low_power_gpu` | only if the box has hybrid graphics worth choosing on |

Inspect at runtime: `app.getGPUFeatureStatus()` / `app.getGPUInfo('complete')`.

Note for continuity: the WSLg run **already renders through ANGLE/D3D12 on the
Intel Iris Xe** (`__orbStats().gl` in `docs/orb/PERFORMANCE.md`), so the GPU stack
is the same silicon either way — what changes is only the presentation path.

---

## 7. Measured idle CPU/GPU — both paths

### 7a. WSLg path (MEASURED — existing evidence, `docs/orb/PERFORMANCE.md`)

Production instance, logon-boot, quality=auto, 280²:

| Metric | Method | Result | Target | Verdict |
|---|---|---|---|---|
| GPU (all engines, Windows counters) | 10×3s samples | max ≈0–0.5% idle | <2% | **MET** |
| electron CPU (WSL `/proc` deltas) | 2×5s | **0.0–0.1%** idle (≈6% during boot anim) | <1% | **MET** |
| WSLg bridge `msrdc` CPU | 6×2s avg | **0.52%** | — | — |
| supervisor `pythonw` CPU | 6×2s | ~0% | ~0 | **MET** |
| Total system CPU | 6×2s avg | 3.65% (dwm desktop baseline 4.6%) | — | — |
| Render path | `__orbStats` | ANGLE/D3D12 Intel Iris Xe, dpr 1.0 | hardware GL | **MET** |

Caveat carried forward: `vmmemwsl` read 24% while the orchestration session ran
in the same WSL instance — at true logon-idle the orb-only VM cost is ~1–3%.

### 7b. Native path (NOT MEASURABLE YET — this is what the prototype is for)

No native number can honestly be written here before a native build runs. The
**measurement protocol** the prototype must execute:

```
CPU : typeperf "\Process(electron*)\% Processor Time" -si 2 -sc 10      (≥2 samples — PDH needs a delta)
      or Get-Counter '\Process(electron*)\% Processor Time' -SampleInterval 2 -MaxSamples 5
      sum the per-process instances (main/GPU/renderer each appear; names truncate to 15 chars + _1,_2)
      cross-check in-app with app.getAppMetrics()  (ProcessMetric[] — CPU + memory per process)
GPU : \GPU Engine(*)\Utilization Percentage  (Windows 10 1809+; instance names encode
      pid/luid/engine, e.g. pid_1234_luid_0x..._eng_0_engtype_3D) — sum all engines for our PID
      companion: \GPU Adapter Memory(*)\Dedicated Usage
heavy: wpr -start GPU -filemode → wpr -stop trace.etl → Windows Performance Analyzer
```

Expected healthy target (**estimate, must be measured**): low-single-digit % CPU
across processes and low-single-digit % GPU-engine utilization at 30 fps.
**>5–10% sustained CPU at idle is a red flag** (throttling-off burn, occlusion
loops, or a compositor fight).

**Comparability rules so the two numbers mean the same thing:** same box, same
display, quality=`auto`, dpr ladder unchanged, orb at rest (`idle` state,
`__orbStats().gov` untouched), 10+ samples, note whether the orchestration
session is running (it moved the WSLg number by ~20 points once already).

### 7c. What WSLg costs that native will not (documented, not yet measured here)

Microsoft's own WSLg README: rendered data is copied **VRAM → system memory →
Weston → back onto the GPU**, a penalty "proportionate to the presentation rate…
at very high frame rates such as 600fps on a discrete GPU that overhead can be as
high as 50%." Independent measurement: Unigine Heaven **17.3 fps under WSLg vs
43.4 fps native** on a Radeon Pro WX3200 (Tom Fenton, Virtualization Review).

For a *small 30 fps overlay* the absolute cost is modest — every frame still
crosses GPU→sysmem→Weston→virtio-gpu→msrdc→DWM, plus input/cursor relay. The
stronger argument is not the frame cost: it is that the shadow-margin clip, the
30 s topmost re-applier and the boot service **are themselves symptoms of
fighting the RDP presentation layer**. A native window composes directly with DWM
and none of that path exists.

---

## 8. Parity checklist (all must pass before the WSLg path is retired)

Run both builds against the **same mock-brain** and diff the results.

| # | Parity item | Existing gate / evidence | Native status |
|---|---|---|---|
| 1 | **Drag** + position persistence across restart | `orb-position.json` + `orb:trace` interaction (hit-testing, `mouseThrough` contract) | pending |
| 2 | **Persistence** — single-instance lock, instance isolation, config load order | `main.js:23-25` re-path before `ready`; `tests/fakebrain-port.test.cjs` (instance→8906, main refuses) | pending |
| 3 | **Transparency** — border alpha exactly 0, no box, no shadow, no baked margin | `orb:trace` transparency phase (`borderA0`, lit counts) + `orb:size` `no_edge_clipping` | pending |
| 4 | **Hotkeys / interactions** — right-click menu, dblclick → typed input → `command{source:'orb'}`, `control` frames | `orb:trace` interaction phase (**30/30** after F-4) | pending |
| 5 | **Mutex** — second instance quits, no double orb | `requestSingleInstanceLock()` scoped to per-instance userData | pending |
| 6 | **CDP** — `--remote-debugging-port` attach still works for the whole trace harness | every `orb:trace` / `orb:size` / `orb:diff` phase depends on it | pending |
| 7 | **Boot sequence** — `starting → idle → <event>` | `orb:trace` boot phase **5/5** + `tests/boot-sequence.test.cjs` **13/13** | pending |
| 8 | **Cage / state distinctness** — sphere cages, colour-only states | `cage guard` **4/4** (`cageRadiusSpread < 0.02`), distinctness **104 pairs**, `orb:diff` | pending |
| 9 | **Idle cost** — must not regress vs 7a | §7 measurement protocol | pending |
| 10 | **Autostart** | Task Scheduler logon task (logon + delay) — writing the task is the deliverable, not running `schtasks` | pending |

**Retirement rule:** the WSLg path (`weston-wrapper`, `topmost.ps1`,
`wslg-shadow/*`) is removed **only** after items 1–9 are green on native in a
single run, and never before. Until then both paths coexist and both stay gated.

---

## 9. Prototype plan (GATED — needs `user_attention` approval)

Sequenced so the first step already answers the biggest unknowns:

1. **Approve + provision** — ATTENTION raised. Node v24.1.0 is already installed;
   the ask is to download the Electron dist on Windows and run it (SmartScreen
   will warn on unsigned `electron.exe`).
2. **Smoke launch** — `npx electron .` from the repo with `--enable-logging=file`
   (Windows child processes do not write to stderr), confirm the orb renders with
   the window recipe in §4.
3. **Measure idle** — the §7b protocol, side by side with the running WSLg orb.
4. **Parity sweep** — the §8 checklist against the mock brain.
5. **Report + go/no-go** — no retirement decision without an explicit approval.

### Open questions that ONLY the prototype can answer

1. Measured idle CPU + GPU of native vs WSLg on this box (§7).
2. Is `CalculateNativeWinOcclusion` on by default in Electron 44 — and is the
   switch even needed? (Cover the orb with another window; watch rAF +
   `document.visibilityState` + GPU counters.)
3. `forward: true` hover reliability on current stable, Win10 **and** Win11
   (#33281 / #30808 / #35030).
4. Alt-Tab exclusion — does `focusable:false` hide the orb, or is
   `WS_EX_TOOLWINDOW` (native module) required?
5. Z-order vs real games: borderless-windowed vs exclusive-fullscreen;
   `screen-saver` vs `floating` level against Discord/OBS/GPU overlays.
6. DWM artefacts on this build: does `thickFrame:false` fully kill the shadow
   (the 32 px-margin equivalent)? Does #51662 (white inactive corners on blur)
   reproduce at our shape/size?
7. Electron 44's DPI-awareness context and mixed-DPI drag (100%↔150%).
8. Token handoff end-to-end: stdin validity from Explorer vs from a launcher;
   named-pipe DACL timing vs pipe squatting; `safeStorage` round-trip.
9. `backgroundThrottling:false` scoped to the orb window — confirm no ~20% burn
   and that it keeps animating while occluded.
10. `npx electron .` on the actual machine: Node 24 + Electron 44 download path,
    first-run timing, SmartScreen behaviour.

---

## 10. Rollback

Rollback is deliberately trivial because **nothing in the WSLg path is deleted**:

- **Build-level:** the native build ships as a separate entry/flag
  (`--native` or a separate package). The supervisor keeps launching the current
  WSL entry point by default; the native path is opt-in until §8 passes.
- **Runtime-level:** killing the native orb and starting the WSL one needs no
  state migration — both read the same `config.yaml`/`config.d`, the same token
  file, the same `orb-position.json` format (DIP vs today's coordinates is the
  one field to version-guard; see §5).
- **System-level rollback:** delete the native install, leave
  `scripts/wslg-shadow/*` and `scripts/topmost.ps1` untouched — the boot service
  and the 30 s topmost re-applier are still installed and still correct.
- **Abort criteria for the whole effort:** if the prototype cannot reach
  transparency-with-zero-border-alpha (item 3) or if idle CPU exceeds the WSLg
  figure, stop and keep WSLg — no partial migration, no orphaned mechanisms.

---

## 11. Deliverables of this packet

| Item | Status |
|---|---|
| `docs/orb/WINDOWS-NATIVE-PLAN.md` (this file) | **DONE — plan only** |
| Research backing | `.opencode/research/windows-native-electron-orb.md` |
| Prototype | **BLOCKED on human approval** — `coord user_attention` posted |
| Code / installs | **NONE** (ARCH-1 is explicitly plan-only) |
| WSLg path | untouched and still fully gated |

---

## 12. AUD-30/22 fold-in — Electron supply-chain + hardening (wave-5H addendum)

Raised by the integrator: *"qa-security filed
`qa-security__to__orb__electron-audit-highs.md` (electron 30.5.1 = 2 npm highs:
ASAR bypass + extract-zip, fix = major bump) — read + fold into your ARCH-1 plan
(supported Electron + restore sandbox + will-navigate/IPC sender validation per
the audit; audit checklist refs: security checklist + timelines)."*

**Verify-first verdicts (every claim quoted from code in this repo):**

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Electron is pinned at 30.5.1 | **CONFIRMED** | `body/orb/package.json` → `"electron": "30.5.1"`; `package-lock.json` → `node_modules/electron -> 30.5.1` |
| 2 | 2 npm highs (ASAR bypass + extract-zip) | **TAKEN ON QA'S WORD — not independently reproducible here** | `npm audit` in `body/orb` returns `400 Bad Request … Invalid request payload JSON format` from the configured registry (`pkgs.safetycli.com`); and `docs/ORB_REBUILD_TASK.md:116` already records: *"npm audit endpoint broken (ignore audit failures)."* I could not confirm severity or fix range myself. |
| 3 | Sandbox is off | **CONFIRMED** | `src/main/main.js:326` → `sandbox: false,` |
| 4 | No `will-navigate` / window-open guard | **CONFIRMED** | `grep -rn "will-navigate\|setWindowOpenHandler\|new-window\|navigate" body/orb/src/` → **NONE FOUND** |
| 5 | No IPC sender validation | **CONFIRMED** | 9 × `ipcMain.handle(...)` in `src/main/main.js`; `grep -rn "senderFrame\|event.sender\|validateSender" src/main/main.js` → **no hits** |
| 6 | Mitigations already present | **ALREADY-DONE** | `src/main/main.js:324-325` → `contextIsolation: true, nodeIntegration: false` |

So: the renderer is not a free RCE path (`contextIsolation` on, `nodeIntegration`
off), and the residual surface is exactly what the audit names — **navigation
guards, IPC sender validation, sandbox, and an unsupported Electron major.**

### What this does to the migration plan (the important part)

1. **The major bump is a PREREQUISITE, not a parallel chore.** The plan targets
   Electron 44 (§1); we are on 30.5.1 — **14 majors behind**. Migrating to a
   native build *on 30.5.1* would ship an EOL runtime and then require a second,
   full parity pass at 44. **Do ONE upgrade to a supported major, then run the
   native prototype on it**, reusing the §8 parity checklist as the upgrade's own
   regression gate.
2. **It conflicts with the base spec, so it needs an integrator decision.**
   `docs/ORB_REBUILD_TASK.md:116` pins *"electron 30.5.1, three 0.170.0, ws
   8.22.0 — **no version drift**."* Bumping Electron is a deliberate spec change,
   not a routine dependency update — ARCH-1 is plan-only, so **no bump is made
   here**; raised for decision instead.
3. **ABI is the cost driver, not the version number** (§1): Electron 44 = ABI
   149 vs Node 24 = ABI 137, so *any* native module must be `@electron/rebuild`ed
   (`win_delay_load_hook` stays on). Budget the bump for that, not for the
   semver diff.

### Hardening timeline (sequenced so nothing is done twice)

| Step | Item | Owner | Gate |
|---|---|---|---|
| **H1 (cheap, now)** | `will-navigate` block + `setWindowOpenHandler({action:'deny'})` on the orb window | orb | new `orb:trace` check; no visual change |
| **H2 (cheap, now)** | IPC sender validation on the 9 `ipcMain.handle` routes (reject any `event.senderFrame` that is not the orb window) | orb | new `orb:trace` check |
| **H3 (needs a decision)** | Electron 30.5.1 → supported major; resolve `ORB_REBUILD_TASK.md:116` "no version drift" | integrator + orb | **full §8 parity checklist** (this becomes the bump's regression suite) |
| **H4 (with H3)** | `sandbox: true` — verify `preload.js` still works (it only uses `contextBridge` + `ipcRenderer`, both allowed in a sandboxed preload) | orb | `test:unit` + `orb:trace` + interaction 34/34 |
| **H5 (after H3)** | Native prototype (§9) **on the new major** | orb, human-gated | §8 parity + §7 measurement |

H1/H2 are independent of the native migration and of H3 — they can land on
30.5.1 today. H4 is deliberately sequenced *with* H3 because restoring the
sandbox on an EOL runtime would have to be re-verified after the bump anyway.

### Audit checklist / timeline references

- Packet: `docs/audit-tasks/orb.md` (ARCH-1 row, plan-only + human gate).
- Project audit: `docs/AUDIT-2026-10-07.md` (priority waves; the electron
  highs are a *later* filing than that document — `grep -n "AUD-30\|AUD-22"`
  over `docs/` returns nothing, so the qa-security request file itself has not
  landed in the tree yet. The findings above are verified from **our own code**,
  not from that file.)
- Deps policy being superseded: `docs/ORB_REBUILD_TASK.md:116`.
- Security invariants that already bind us: `docs/PROTOCOL.md` §11.
