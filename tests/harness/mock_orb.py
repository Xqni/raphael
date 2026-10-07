"""Mock Orb/UI client (PROTOCOL §3/§8, INTERFACES §e): role=ui session that
records every orb_state frame (and every other frame) it receives, in order —
the regression baseline for lifecycle state transitions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .wssession import WSSession


class MockOrb(WSSession):
    role = 'ui'
    client_name = 'orb-mock'

    @property
    def orb_states(self) -> List[Dict[str, Any]]:
        return [f for f in self.frames if f.get('type') == 'orb_state']

    @property
    def state_sequence(self) -> List[Tuple[str, str, int]]:
        """[(state, mode, jobs_active), ...] in arrival order."""
        return [(f.get('state'), f.get('mode'), f.get('jobs_active', -1))
                for f in self.orb_states]

    @property
    def states(self) -> List[str]:
        return [f.get('state') for f in self.orb_states]

    def job_events(self, job: Optional[str] = None) -> List[Dict[str, Any]]:
        evs = [f for f in self.frames if f.get('type') == 'job_event']
        if job is not None:
            evs = [f for f in evs if f.get('job') == job]
        return evs

    def subtitles(self) -> List[Dict[str, Any]]:
        return [f for f in self.frames if f.get('type') == 'subtitle']

    def wait_state(self, state: str, timeout: float = 8.0) -> Dict[str, Any]:
        return self.wait(lambda m: m.get('type') == 'orb_state'
                         and m.get('state') == state, timeout=timeout)
