# Raphael orb - persistent topmost/styling watcher.
# ONE long-lived process (spawned by main.js) instead of per-call PowerShell
# spawns (each paid ~1s Add-Type cold start -> taskbar flashed for a second).
# Polls every 100ms; applies to EVERY visible "Raphael Orb*" window:
#   HWND_TOPMOST + strip CAPTION/THICKFRAME/BORDER/DLGFRAME + WS_EX_TOOLWINDOW
#   (taskbar/Alt-Tab invisible) + WS_EX_NOACTIVATE + DWM no-shadow/no-round/
#   no-backdrop + inner region (baked-margin clip, only when window > 280).
# Exits itself 30s after the last Raphael window disappears (clean lifecycle).
param([string]$Title = "Raphael Orb")

# Warm-start: compile the interop code to a DLL on first-ever run, then plain
# -Path loads in ~50ms. Inline Add-Type costs ~1.5-2s — that sat exactly in
# the taskbar-flash window (user: no visible taskbar entry, ever).
$csharp = @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public struct RC { public int Left; public int Top; public int Right; public int Bottom; }

public class Watch32 {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")]
  public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
                                         int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
  public static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int nIndex);
  [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
  public static extern IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RC lpRect);
  [DllImport("user32.dll")] public static extern int SetWindowRgn(IntPtr hWnd, IntPtr hRgn, bool bRedraw);
  [DllImport("user32.dll")] public static extern int GetWindowRgn(IntPtr hWnd, IntPtr hRgn);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateRectRgn(int l, int t, int r, int b);
  [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr hObject);
  [DllImport("dwmapi.dll")]
  public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int pv, int cb);
}
"@
$dll = Join-Path $env:TEMP 'raphael-watch32.dll'
if (-not ('Watch32' -as [type])) {
  try {
    if (Test-Path $dll) {
      Add-Type -Path $dll -ErrorAction Stop            # steady state: ~50-100ms
    } else {
      Add-Type -TypeDefinition $csharp -OutputAssembly $dll -OutputType Library -ErrorAction Stop | Out-Null
      if (-not ('Watch32' -as [type])) { Add-Type -Path $dll -ErrorAction Stop }
    }
  } catch { Add-Type -TypeDefinition $csharp }         # fallback: inline compile
}

$mask = 0x00C00000 -bor 0x00040000 -bor 0x00800000 -bor 0x00010000 # CAPTION|THICKFRAME|BORDER|DLGFRAME
$styled = @{}          # hwnd -> last region size (skip redundant work)
$absentSince = $null   # when no windows were seen (30s -> exit)
$t0 = Get-Date

function Apply-To([IntPtr]$found, [hashtable]$seen) {
  $seen[[int]$found] = $true   # hwnd marker: dedupes the "new window" log
  # topmost (+ FRAMECHANGED)
  [void][Watch32]::SetWindowPos($found, [IntPtr](-1), 0, 0, 0, 0,
    0x0001 -bor 0x0002 -bor 0x0010 -bor 0x0040 -bor 0x0020)
  # exstyle: taskbar/Alt-Tab invisible + never take focus
  $exv = [Watch32]::GetWindowLongPtr($found, -20).ToInt64()
  $want = $exv -bor 0x80 -bor 0x80000000
  if ($want -ne $exv) { [void][Watch32]::SetWindowLongPtr($found, -20, [IntPtr]$want) }
  # strip caption styles (DWM shadow/round anchors)
  $style = [Watch32]::GetWindowLongPtr($found, -16).ToInt64()
  $newStyle = $style -band (-bnot [int64]$mask)
  if ($newStyle -ne $style) { [void][Watch32]::SetWindowLongPtr($found, -16, [IntPtr]$newStyle) }
  # DWM: no NC rendering (shadow), no rounded corners, no backdrop
  $ncr = 1; [void][Watch32]::DwmSetWindowAttribute($found, 2, [ref]$ncr, 4)
  $noR = 1; [void][Watch32]::DwmSetWindowAttribute($found, 33, [ref]$noR, 4)
  $bd  = 1; [void][Watch32]::DwmSetWindowAttribute($found, 38, [ref]$bd, 4)
  # inner region only when the window carries a baked margin (>280 square)
  $rc = New-Object RC
  if ([Watch32]::GetWindowRect($found, [ref]$rc)) {
    $w = $rc.Right - $rc.Left; $h = $rc.Bottom - $rc.Top
    $key = "$found|$w`x$h"
    if (-not $seen.ContainsKey($key)) {
      if ($w -eq $h -and $w -gt 280 -and $w -le 440) {
        $m = [int](($w - 280) / 2)
        $rgn = [Watch32]::CreateRectRgn($m, $m, $w - $m, $h - $m)
        if ($rgn -ne [IntPtr]::Zero) {
          if ([Watch32]::SetWindowRgn($found, $rgn, $true) -eq 0) { [void][Watch32]::DeleteObject($rgn) }
        }
      }
      $seen[$key] = $true
    }
  }
}

$enum = [Watch32+EnumProc]{
  param([IntPtr]$h, [IntPtr]$l)
  if ([Watch32]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder 512
    [void][Watch32]::GetWindowText($h, $sb, 512)
    if ($sb.ToString().StartsWith($Title, [StringComparison]::OrdinalIgnoreCase)) {
      $script:found = $h
    }
  }
  return $true
}

while ($true) {
  $script:found = [IntPtr]::Zero
  [void][Watch32]::EnumWindows($enum, [IntPtr]::Zero)
  if ($script:found -ne [IntPtr]::Zero) {
    $absentSince = $null
    $wasKnown = $styled.ContainsKey([int]$script:found)
    Apply-To $script:found $styled
    if (-not $wasKnown) {
      $el = [int]((Get-Date) - $t0).TotalMilliseconds
      Write-Output ("WATCHER: styled new hwnd=$script:found after {0} ms of watcher start" -f $el)
    }
  } else {
    if ($null -eq $absentSince) { $absentSince = Get-Date }
    elseif (((Get-Date) - $absentSince).TotalSeconds -gt 30) {
      Write-Output "WATCHER: no Raphael window for 30s - exiting"
      break
    }
  }
  Start-Sleep -Milliseconds 100
}
