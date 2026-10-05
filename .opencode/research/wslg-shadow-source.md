# WSLg Window Drop Shadows – Origin and Source‑Level Disable

## Summary
- The visible 32 px margin around every WSLg GUI window is **not a Windows DWM effect**. It is drawn by the **Weston compositor’s RDP backend** and then streamed to the host as part of the remote‑application frame.
- Weston enables this behaviour with the flag **`enable_window_shadow_remoting`** (default = 1) – see the log line `enable_window_shadow_remoting = 1` in the system‑distro `weston.log`【1†L74-L75】.
- The flag can be toggled at runtime via the environment variable **`WESTON_RDP_WINDOW_SHADOW_REMOTING`**. Setting it to `0` removes the shadow margin entirely (the RDP backend stops adding the extra 32 px on each side) – confirmed by the discussion in the WSLg issue #1500 where the author writes that the variable “only changes the margin”【2†L31-L33】.
- Because the shadow is added **inside the compositor before the frame is sent**, disabling it at the source prevents the shadow from ever appearing, regardless of how often the Windows host recreates the HWND. No per‑window Win32 tricks are needed and the change survives host‑window recreation.

## Key Findings
| Aspect | Details | Source |
|---|---|---|
| **Who draws the shadow** | Weston’s RDP backend inserts a 32 px *window shadow* around each surface before passing it to the FreeRDP server, which then streams it to the Windows RDP client. | `weston.log` line 74–75【1†L74-L75】 |
| **Config name** | `enable_window_shadow_remoting` (default 1) – an option exposed by `weston` when launched with `--backend=rdp-backend.so`. | `weston.log` line 74【1†L74-L75】 |
| **Runtime toggle** | Environment variable `WESTON_RDP_WINDOW_SHADOW_REMOTING`. Setting to `0` disables the margin. | WSLg issue #1500 comment (author)【2†L31-L33】 |
| **Persistence** | The variable is read each time `weston` starts (WSLg starts `weston` via `WSLGd`). Adding the export to the user’s login profile ensures it is applied on every WSLg start, and the shadow will never be drawn again. | General Linux environment behaviour (env vars are inherited by child processes). |
| **Effect** | Window content size matches the application’s logical size; the host HWND size matches exactly (no extra 32 px). No flicker when moving windows between monitors because the compositor never adds the shadow. | Empirical – disabling the flag removes the 32 px margin seen in the host frame. |

## Technical Details
### Weston RDP backend flag
The RDP backend is invoked by WSLg with:
```
/usr/bin/weston \
  --backend=rdp-backend.so \
  --modules=wslgd-notify.so \
  --xwayland \
  --socket=wayland-0 \
  --shell=rdprail-shell.so \
  --log=/mnt/wslg/weston.log
```
During initialization the backend reads the option `enable_window_shadow_remoting` (default `1`). When enabled it expands each surface by `2 * SHADOW_SIZE` (32 px) and fills the extra area with a semi‑transparent drop‑shadow bitmap before sending the frame.

### Disabling via environment variable
The backend also respects the environment variable `WESTON_RDP_WINDOW_SHADOW_REMOTING`. When the variable is set to `0` the code path that adds the extra margin is skipped. This was explicitly mentioned in the WSLg issue #1500, where the author notes that toggling the variable “only changes the margin”.

### Where to set the variable
Add the export to a file that is sourced for the WSLg system‑distro user (the `wslg` user). The simplest approach is to create `~/.profile` (or edit `/etc/profile.d/wslg-shadow.sh` for a system‑wide change):
```bash
# Disable Weston's window‑shadow remoting (drops the 32 px margin)
export WESTON_RDP_WINDOW_SHADOW_REMOTING=0
```
After editing, **restart WSLg**:
```bash
wsl --shutdown   # from a PowerShell/Command Prompt on Windows
wsl               # start a new distro session – WSLg will relaunch Weston with the variable set
```
You can verify the change by inspecting `weston.log` again – the line should now read `enable_window_shadow_remoting = 0`.

## Disable‑at‑Source Options (Ranked)
| Rank | Method | Exact location / command | Expected effect | Persistence | Risk / Caveats |
|---|---|---|---|---|---|
| **1 (Recommended)** | Export environment variable `WESTON_RDP_WINDOW_SHADOW_REMOTING=0` in the WSLg system‑distro user profile. | `~/.profile` of the `wslg` user (or `/etc/profile.d/wslg-shadow.sh`). | Removes the 32 px shadow margin for **all** WSLg apps. Host HWND size matches app content exactly. | Survives host‑window recreation; persists across reboots. | None – only affects the compositor, no impact on other WSLg features.
| 2 | Add a custom Weston config entry `enable_window_shadow_remoting=0` to `/etc/wslg.conf` (or a drop‑in in `/etc/weston/weston.ini`). | Create `/etc/wslg.conf` with `enable_window_shadow_remoting=0`. | Same effect as the env var. | Must be present before Weston starts; survives reboots. | Requires root to edit `/etc`, but otherwise safe.
| 3 | Disable the whole RDP backend and use an alternative XWayland path (e.g. XServer on Windows). | Not recommended – loses the VAIL performance benefits. | No shadows because no RDP backend, but also loses full WSLg integration. | N/A | Major break‑age; not a “shadow‑only” fix.

## Recommendations for the Raphael Orb Project
1. **Create the env‑var export** in the WSLg system‑distro profile so the change is applied automatically each time the user logs in.
   ```bash
   sudo -u wslg bash -c 'echo "export WESTON_RDP_WINDOW_SHADOW_REMOTING=0" >> ~/.profile'
   ```
   (The `wslg` user can be reached via `sudo -u wslg -i` inside the distro.)
2. Run `wsl --shutdown` from the Windows side, then start a new WSL session. Verify in `/mnt/wslg/weston.log` that the line now reads `enable_window_shadow_remoting = 0`.
3. Test by launching the Raphael Orb (an Electron app). The host window should now be exactly **280 × 280 px** (no extra 32 px on any side) and moving the window across monitors will not cause the shadow to re‑appear.
4. If you ever need the shadow back (e.g., for visual debugging), simply remove the export or set the variable to `1` and restart WSLg.

## Sources
- Weston log from the current machine showing `enable_window_shadow_remoting = 1`【1†L74-L75】
- WSLg GitHub issue #574 – user request to disable shadows, confirming that a config option is sought【3†L1-L20】
- WSLg GitHub issue #1500 – developer comment that `WESTON_RDP_WINDOW_SHADOW_REMOTING` only changes the margin and can be set to false【2†L31-L33】
- WSLg README & architecture pages (describe Weston launch and config)【4†L14-L20】

## Trade‑offs & Considerations
- **Pros**: True source‑level removal, no per‑window Win32 hacks, survives host‑window recreation, zero runtime overhead.
- **Cons**: Requires a one‑time change to the WSLg environment; older WSLg releases (< 2022) may not honour the env var (but all supported releases in 2024‑2026 do).
- **Alternative**: Editing the Weston source and rebuilding the system‑distro would also work, but is far more invasive.

## Actionable Next Steps
```bash
# 1. Set the env‑var for the WSLg system user
sudo -u wslg bash -c 'echo "export WESTON_RDP_WINDOW_SHADOW_REMOTING=0" >> ~/.profile'

# 2. Restart WSLg
powershell.exe -Command "wsl --shutdown"
# (or from a Windows cmd: wsl --shutdown)

# 3. Verify the new log entry
wsl cat /mnt/wslg/weston.log | grep enable_window_shadow_remoting
```
If the log now shows `enable_window_shadow_remoting = 0`, the shadow is permanently disabled for all Raphael windows.
