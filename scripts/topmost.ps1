# Raphael orb — Windows-side always-on-top (PowerToys mechanism, no keybinding).
# WSLg hosts each Linux window in a real Windows HWND via msrdc with title
# "<X title> (<distro>)", e.g. "Raphael Orb (Ubuntu-26.04)". We EnumWindows for
# a visible window whose title STARTS WITH the given prefix, set HWND_TOPMOST,
# and best-effort disable the DWM drop shadow. Idempotent; safe to re-run
# (main.js re-asserts periodically in case the host re-orders z-stacking).
# Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File topmost.ps1 [-Title "Raphael Orb"]
param([string]$Title = "Raphael Orb")

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

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
  [DllImport("dwmapi.dll")]
  public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int pv, int cb);
}
"@

$found = [IntPtr]::Zero
$enum = [Win32Top+EnumProc]{
  param([IntPtr]$h, [IntPtr]$l)
  if ([Win32Top]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder 512
    [void][Win32Top]::GetWindowText($h, $sb, 512)
    if ($sb.ToString().StartsWith($Title, [StringComparison]::OrdinalIgnoreCase)) {
      $script:found = $h
      return $false   # stop enumeration
    }
  }
  return $true
}
[void][Win32Top]::EnumWindows($enum, [IntPtr]::Zero)

if ($found -eq [IntPtr]::Zero) {
  Write-Output "NOT_FOUND prefix='$Title'"
  exit 1
}

# HWND_TOPMOST = -1 ; SWP_NOSIZE(0x1) | SWP_NOMOVE(0x2) | SWP_NOACTIVATE(0x10) | SWP_SHOWWINDOW(0x40) | SWP_FRAMECHANGED(0x20)
[void][Win32Top]::SetWindowPos($found, [IntPtr](-1), 0, 0, 0, 0,
  0x0001 -bor 0x0002 -bor 0x0010 -bor 0x0040 -bor 0x0020)

# Best-effort drop-shadow removal: DWMWA_NCRENDERING_POLICY(2) = DWMNCRP_DISABLED(1)
$ncr = 1
[void][Win32Top]::DwmSetWindowAttribute($found, 2, [ref]$ncr, 4)

# The DWM shadow + rounded corners hang off the CAPTION/THICKFRAME styles —
# strip them (borderless overlay should have neither) and force a frame refresh.
$GWL_STYLE = -16
$mask = 0x00C00000 -bor 0x00040000 -bor 0x00800000 -bor 0x00010000  # CAPTION|THICKFRAME|BORDER|DLGFRAME
$style = [Win32Top]::GetWindowLongPtr($found, $GWL_STYLE).ToInt64()
$newStyle = $style -band (-bnot [int64]$mask)
if ($newStyle -ne $style) {
  [void][Win32Top]::SetWindowLongPtr($found, $GWL_STYLE, [IntPtr]$newStyle)
}
# Win11: DWMWA_WINDOW_CORNER_PREFERENCE(33) = DWMWCP_DONOTROUND(1)
$noRound = 1
[void][Win32Top]::DwmSetWindowAttribute($found, 33, [ref]$noRound, 4)
# Force DWM to re-apply the stripped styles immediately (SWP_FRAMECHANGED=0x20)
[void][Win32Top]::SetWindowPos($found, [IntPtr](-1), 0, 0, 0, 0,
  0x0001 -bor 0x0002 -bor 0x0010 -bor 0x0040 -bor 0x0020)

# Verify: GWL_EXSTYLE(-20), WS_EX_TOPMOST = 0x8
$ex = [Win32Top]::GetWindowLongPtr($found, -20).ToInt64()
$topmost = (($ex -band 0x8) -ne 0)
Write-Output ("hwnd={0} topmost={1} exstyle=0x{2:X}" -f $found, $topmost, $ex)
if (-not $topmost) { exit 2 }
