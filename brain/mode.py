"""Global mode state — pause / private / watch.

Persisted in the SQLite `state` table (with the memory DB) so flags survive
brain restarts (PROTOCOL §3 control actions; addendum pause/private rules).
kill_gui is momentary — it never touches persistence.
"""
import json
from typing import Any, Dict

from brain.memory import get_conn

KEY = 'mode'


class ModeState:
    def __init__(self):
        s = self._load()
        self.paused = bool(s.get('paused'))
        self.private = bool(s.get('private'))
        self.watch = bool(s.get('watch'))

    def _load(self) -> Dict[str, Any]:
        conn = get_conn()
        try:
            row = conn.execute('SELECT value FROM state WHERE key=?', (KEY,)).fetchone()
        finally:
            conn.close()
        try:
            return json.loads(row['value']) if row else {}
        except (TypeError, ValueError):
            return {}

    def _save(self):
        payload = json.dumps({'paused': self.paused, 'private': self.private, 'watch': self.watch})
        conn = get_conn()
        try:
            conn.execute(
                'INSERT INTO state(key, value) VALUES(?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value, '
                'updated_at=CURRENT_TIMESTAMP',
                (KEY, payload),
            )
            conn.commit()
        finally:
            conn.close()

    def set(self, action: str, persist: bool = True) -> str:
        """Apply a control action; returns the mode label after the change."""
        if action == 'pause':
            self.paused = True
        elif action == 'resume':
            self.paused = False
        elif action == 'private_on':
            self.private = True
        elif action == 'private_off':
            self.private = False
        elif action == 'watch_on':
            self.watch = True
        elif action == 'watch_off':
            self.watch = False
        else:
            raise ValueError(f'unknown control action: {action}')
        if persist:
            self._save()
        return self.label()

    def label(self) -> str:
        if self.paused:
            return 'paused'
        if self.private:
            return 'private'
        return 'normal'

    def snapshot(self) -> Dict[str, Any]:
        return {'mode': self.label(), 'paused': self.paused,
                'private': self.private, 'watch': self.watch}


_mode: ModeState | None = None


def get_mode() -> ModeState:
    global _mode
    if _mode is None:
        _mode = ModeState()
    return _mode


def reset_mode_for_tests():
    """Drop the cached instance so tests re-read persisted state."""
    global _mode
    _mode = None
