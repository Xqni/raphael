# Raphael orb - Windows-side always-on-top + shadow suppression (PowerToys
# mechanism, no keybinding). Handles ALL windows titled "Raphael Orb*":
#   - HWND_TOPMOST on each
#   - strips CAPTION|THICKFRAME|BORDER|DLGFRAME styles (DWM shadow/round anchors)
#   - DWM: no NC rendering, no rounded corners, no backdrop
#   - INNER region: WSLg/Weston bakes a ~32px shadow margin INSIDE the surface
#     (host 344x344 for a 280 app) - clipping to the inner content rect removes
#     those baked pixels, which no DWM API can touch.
# Idempotent; main.js re-runs this every 30s.
param([string]$Title = "Raphael Orb", [switch]$Wait)

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public struct RC { public int Left; public int Top; public int Right; public int Bottom; }

public class Win32Top {
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

# Collect ALL visible windows whose title starts with the prefix.
# -Wait: retry every 100ms (up to 10s) until the msrdc host window EXISTS -
# the taskbar entry must never get a visible gap (user: no taskbar window at
# ANY point, including app start).
$tries = 1
if ($Wait) { $tries = 100 }
$wins = @()
$enum = [Win32Top+EnumProc]{
  param([IntPtr]$h, [IntPtr]$l)
  if ([Win32Top]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder 512
    [void][Win32Top]::GetWindowText($h, $sb, 512)
    if ($sb.ToString().StartsWith($Title, [StringComparison]::OrdinalIgnoreCase)) {
      $script:wins += $h
    }
  }
  return $true
}
for ($t = 0; $t -lt $tries; $t++) {
  $wins = @()
  [void][Win32Top]::EnumWindows($enum, [IntPtr]::Zero)
  if ($wins.Count -gt 0) { break }
  Start-Sleep -Milliseconds 100
}

if ($wins.Count -eq 0) {
  Write-Output "NOT_FOUND prefix='$Title'"
  exit 1
}

$mask = 0x00C00000 -bor 0x00040000 -bor 0x00800000 -bor 0x00010000  # CAPTION|THICKFRAME|BORDER|DLGFRAME
$report = @()
foreach ($found in $wins) {
  # topmost (SWP_NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW|FRAMECHANGED)
  [void][Win32Top]::SetWindowPos($found, [IntPtr](-1), 0, 0, 0, 0,
    0x0001 -bor 0x0002 -bor 0x0010 -bor 0x0040 -bor 0x0020)

  # DWM: no NC rendering (shadow), no rounded corners, no backdrop
  $ncr = 1
  [void][Win32Top]::DwmSetWindowAttribute($found, 2, [ref]$ncr, 4)
  $noRound = 1
  [void][Win32Top]::DwmSetWindowAttribute($found, 33, [ref]$noRound, 4)
  $bd = 1
  [void][Win32Top]::DwmSetWindowAttribute($found, 38, [ref]$bd, 4)

  # strip caption styles
  $style = [Win32Top]::GetWindowLongPtr($found, -16).ToInt64()
  $newStyle = $style -band (-bnot [int64]$mask)
  if ($newStyle -ne $style) {
    [void][Win32Top]::SetWindowLongPtr($found, -16, [IntPtr]$newStyle)
  }

  # INNER region: clip away the compositor-baked shadow margin.
  # margin = (min(w,h) - 280) / 2 when the window is square and only modestly
  # larger than the 280px app; otherwise no region (never clip real content).
  $rc = New-Object RC
  $regApplied = "skipped"
  if ([Win32Top]::GetWindowRect($found, [ref]$rc)) {
    $w = $rc.Right - $rc.Left
    $h = $rc.Bottom - $rc.Top
    if ($w -eq $h -and $w -gt 280 -and $w -le 440) {
      $m = [int](($w - 280) / 2)
      $rgn = [Win32Top]::CreateRectRgn($m, $m, $w - $m, $h - $m)
      if ($rgn -ne [IntPtr]::Zero) {
        if ([Win32Top]::SetWindowRgn($found, $rgn, $true) -ne 0) { $regApplied = "inner(${m}px)" }
        else { [void][Win32Top]::DeleteObject($rgn); $regApplied = "FAILED" }
      }
    } else {
      $regApplied = "n/a(${w}x${h})"
    }
  }
  # Hide from taskbar + Alt-Tab (WS_EX_TOOLWINDOW=0x80) and never take focus
  # (WS_EX_NOACTIVATE=0x80000000) - user: no separate taskbar app entry;
  # the orb is a pure on-screen overlay. FRAMECHANGED re-applies it.
  $exv = [Win32Top]::GetWindowLongPtr($found, -20).ToInt64()
  $want = $exv -bor 0x80 -bor 0x80000000
  if ($want -ne $exv) {
    [void][Win32Top]::SetWindowLongPtr($found, -20, [IntPtr]$want)
    [void][Win32Top]::SetWindowPos($found, [IntPtr](-1), 0, 0, 0, 0,
      0x0001 -bor 0x0002 -bor 0x0010 -bor 0x0040 -bor 0x0020)
  }

  $ex = [Win32Top]::GetWindowLongPtr($found, -20).ToInt64()
  $report += ("hwnd={0} topmost={1} region={2}" -f $found, ((($ex -band 0x8) -ne 0)), $regApplied)
}
Write-Output ($report -join " | ")
