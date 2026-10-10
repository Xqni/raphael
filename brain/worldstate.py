"""World state (Wave 5U task 6): what is happening RIGHT NOW, so fastpath
follow-ups ("now search X", "scroll down", "go back") resolve BEFORE the
LLM. OWNERSHIP.md grant 2026-10-10.

State sources (all pushed, never polled):
- focused window: `brain/foreground.py` push cache (ws `foreground`, body);
- active browser tab {url, title, site, tab_id}: ws `browser_tab` frame
  (body/pc — PROTOCOL request brain-core__to__integrator__browser-tab-
  frame.md; absent = no tab context, follow-ups fall back to today's tools);
- last action / last search: recorded by loop.py / fastpath.py.

Value-blind: strings are length-capped, never logged; `snapshot()` is for
in-process decisions and /status-style readouts only. All fields Optional —
absence is the normal case and NEVER an error (fail-open to fallbacks,
fail-closed on anything side-effecting stays in the tools themselves).
"""
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

_CAP = 200


def _cap(v: Any) -> str:
    return ' '.join(str(v or '').split())[:_CAP]


def _site_of(url: str) -> str:
    try:
        host = (urlparse(url).netloc or '').lower()
        return host[4:] if host.startswith('www.') else host
    except Exception:  # noqa: BLE001 — malformed URL = no site, never a crash
        return ''


_tab: Optional[Dict[str, Any]] = None      # {url,title,site,tab_id,ts}
_last_action: Optional[Dict[str, Any]] = None
_last_search: Optional[Dict[str, Any]] = None


def record_browser_tab(url: Optional[str], title: Optional[str] = None,
                       tab_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """ws `browser_tab` consumer. Empty/null url CLEARS the tab (browser
    closed / no tab) — follow-ups fall back to launch semantics."""
    global _tab
    if not url or not str(url).strip():
        _tab = None
        return None
    _tab = {'url': _cap(url), 'title': _cap(title),
            'site': _site_of(url), 'tab_id': _cap(tab_id) or None,
            'ts': time.time()}
    return dict(_tab)


def record_action(tool: str, ok: bool, args: Optional[Dict[str, Any]] = None,
                  detail: str = '') -> None:
    """loop.py records every dispatched tool (report-after-the-fact seam)."""
    global _last_action
    _last_action = {'tool': _cap(tool), 'ok': bool(ok),
                    'detail': _cap(detail), 'ts': time.time()}


def record_search(query: str, site: str, url: str,
                  tab_id: Optional[str] = None) -> None:
    """fastpath records every search dispatch (tab_id when known)."""
    global _last_search
    _last_search = {'query': _cap(query), 'site': _cap(site),
                    'url': _cap(url), 'tab_id': _cap(tab_id) or None,
                    'ts': time.time()}


def active_tab() -> Optional[Dict[str, Any]]:
    """Fresh-ish tab (<= 15 min) or None. Follow-ups must treat None as
    'no tab context' -> existing launch/search tools."""
    if _tab and (time.time() - _tab['ts']) <= 900.0:
        return dict(_tab)
    return None


def snapshot() -> Dict[str, Any]:
    from . import foreground
    return {
        'focused': foreground.status_block(),
        'tab': active_tab(),
        'last_action': dict(_last_action) if _last_action else None,
        'last_search': dict(_last_search) if _last_search else None,
    }


def reset_for_tests() -> None:
    global _tab, _last_action, _last_search
    _tab = None
    _last_action = None
    _last_search = None
