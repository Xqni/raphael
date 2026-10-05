// Raphael orb - persistent topmost/styling watcher (compiled EXE).
// PowerShell cold-start (~2s) sat in the taskbar-flash window; this EXE starts
// in ~50ms, polls every 100ms, and styles EVERY visible "Raphael Orb*" window:
//   HWND_TOPMOST + strip CAPTION/THICKFRAME/BORDER/DLGFRAME + WS_EX_TOOLWINDOW
//   (taskbar/Alt-Tab invisible) + WS_EX_NOACTIVATE + DWM no-shadow/no-round/
//   no-backdrop + inner region when the window carries a baked margin (>280).
// Exits itself 30s after the last Raphael window disappears.
// Compiled with: csc /nologo /target:exe /out:topmost-watcher.exe topmost-watcher.cs
using System;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;

public struct RC { public int Left, Top, Right, Bottom; }

public static class Watcher {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr h, int n);
  [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] static extern IntPtr SetWindowLongPtr(IntPtr h, int n, IntPtr v);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RC r);
  [DllImport("user32.dll")] static extern int SetWindowRgn(IntPtr h, IntPtr rg, bool redraw);
  [DllImport("gdi32.dll")] static extern IntPtr CreateRectRgn(int l, int t, int r, int b);
  [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr o);
  [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int v, int cb);

  static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
  const uint SWP_NOSIZE = 0x1, SWP_NOMOVE = 0x2, SWP_NOACTIVATE = 0x10, SWP_SHOWWINDOW = 0x40, SWP_FRAMECHANGED = 0x20;
  const long STYLE_MASK = 0x00C00000L | 0x00040000L | 0x00800000L | 0x00010000L; // CAPTION|THICKFRAME|BORDER|DLGFRAME
  const string TITLE_PREFIX = "Raphael Orb";

  static readonly HashSet<long> Styled = new HashSet<long>();
  static IntPtr lastSeen = IntPtr.Zero;

  static bool Collect(IntPtr h, IntPtr l) {
    if (!IsWindowVisible(h)) return true;
    var sb = new StringBuilder(512);
    GetWindowText(h, sb, 512);
    if (sb.ToString().StartsWith(TITLE_PREFIX, StringComparison.OrdinalIgnoreCase)) { lastSeen = h; return false; }
    return true;
  }

  static void Apply(IntPtr h) {
    SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED);
    long ex = GetWindowLongPtr(h, -20).ToInt64();
    long want = ex | 0x80L | 0x80000000L;            // TOOLWINDOW + NOACTIVATE
    if (want != ex) SetWindowLongPtr(h, -20, new IntPtr(want));
    long st = GetWindowLongPtr(h, -16).ToInt64();
    long ns = st & ~STYLE_MASK;
    if (ns != st) SetWindowLongPtr(h, -16, new IntPtr(ns));
    int one = 1;
    DwmSetWindowAttribute(h, 2, ref one, 4);          // no NC rendering (shadow)
    int nr = 1; DwmSetWindowAttribute(h, 33, ref nr, 4);  // no rounded corners
    int bd = 1; DwmSetWindowAttribute(h, 38, ref bd, 4);  // no backdrop

    RC r;
    if (GetWindowRect(h, out r)) {
      int w = r.Right - r.Left, hh = r.Bottom - r.Top;
      long key = ((long)h.ToInt64() << 32) | (uint)(w * 4096 + hh);
      if (!Styled.Contains(key)) {
        if (w == hh && w > 280 && w <= 440) {
          int m = (w - 280) / 2;
          IntPtr rg = CreateRectRgn(m, m, w - m, hh - m);
          if (rg != IntPtr.Zero && SetWindowRgn(h, rg, true) == 0) DeleteObject(rg);
        }
        Styled.Add(key);
      }
    }
  }

  public static int Main(string[] args) {
    DateTime start = DateTime.Now;
    DateTime? absentSince = null;
    var seen = new HashSet<long>();
    while (true) {
      lastSeen = IntPtr.Zero;
      EnumWindows(Collect, IntPtr.Zero);
      if (lastSeen != IntPtr.Zero) {
        absentSince = null;
        long hwndKey = lastSeen.ToInt64();
        bool isNew = !seen.Contains(hwndKey);
        seen.Add(hwndKey);
        Apply(lastSeen);
        if (isNew) {
          int ms = (int)(DateTime.Now - start).TotalMilliseconds;
          Console.WriteLine("WATCHER: styled hwnd=0x" + hwndKey.ToString("X") + " after " + ms + " ms");
        }
      } else {
        if (absentSince == null) absentSince = DateTime.Now;
        else if ((DateTime.Now - absentSince.Value).TotalSeconds > 30) {
          Console.WriteLine("WATCHER: no Raphael window for 30s - exiting");
          return 0;
        }
      }
      System.Threading.Thread.Sleep(100);
    }
  }
}
