"""Wave 5U §5.2 task7: uia lookups default to the FOCUSED window — the
active window's subtree is enumerated first (pure stub, no Windows)."""
from types import SimpleNamespace

from body.win.winlayer import WindowsBackend


class _Wrap(SimpleNamespace):
    def descendants(self):
        return []

    def wrapper_object(self):
        return self


class _Desktop:
    def __init__(self):
        self.active = _Wrap(element_info=SimpleNamespace(
            name='Search', control_type='Edit', automation_id='',
            class_name='Chrome_WidgetWin_1'))
        self.tops = [
            _Wrap(element_info=SimpleNamespace(
                name='Notepad', control_type='Window', automation_id='',
                class_name='Notepad')),
            self.active,
        ]

    def window(self, active=False):
        return self.active if active else self.tops[0]

    def windows(self):
        return list(self.tops)


def test_iter_candidates_yields_active_subtree_first():
    be = object.__new__(WindowsBackend)          # no Windows init needed
    order = [w.element_info.name for w in be._iter_candidates(_Desktop())]
    assert order[0] == 'Search', order
    assert set(order) == {'Search', 'Notepad'}   # ordering = task7 contract
