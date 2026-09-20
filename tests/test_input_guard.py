"""Platform adapter tests with fakes. Never instantiate real PyAutoGUI."""
import threading
import time
from types import SimpleNamespace

import pytest

from autofarmseal.engine import Action
from autofarmseal.model import Profile, Rect
from autofarmseal.windows import Native, SafetyError, Window


class FakePG:
    FAILSAFE = True
    KEYBOARD_KEYS = ["ctrl", "1", "2", "space"]

    def __init__(self):
        self.events = []
        self.on_move = lambda: None
        self.fail_down = False

    def moveTo(self, *args, **kwargs):
        self.events.append("move")
        self.on_move()

    def keyDown(self, key):
        self.events.append("down:"+key)

    def keyUp(self, key):
        self.events.append("up:"+key)

    def mouseDown(self, **kw):
        self.events.append("mouse-down")
        if self.fail_down:
            raise RuntimeError("simulated failsafe")

    def mouseUp(self, **kw):
        self.events.append("mouse-up")


def setup_native():
    n = Native.__new__(Native)
    n.blocked = threading.Event()
    n.lock = threading.RLock()
    n.keys = set()
    n.mouse = False
    n.pg = FakePG()
    n.api = SimpleNamespace(GetSystemMetrics=lambda index: (1920, 1080)[index])
    expected = Window(10, 123, "Test game", Rect(20, 40, 320, 200))
    n.window = lambda hwnd: expected
    n.is_foreground = lambda window: True
    p = Profile(width=320, height=200, regions={"world": Rect(0, 20, 320, 180)})
    return n, expected, p


def test_blocked_input_never_sends_down():
    n, w, p = setup_native()
    n.blocked.set()
    with pytest.raises(SafetyError):
        n.execute(Action("attack", (50, 50)), w, time.monotonic(), p)
    assert not n.pg.events


def test_stale_input_rejected():
    n, w, p = setup_native()
    with pytest.raises(SafetyError):
        n.guard(w, time.monotonic()-2, p)


@pytest.mark.parametrize("change", ["focus", "geometry", "pid", "monitor", "excluded"])
def test_input_guard_rechecks_all_invariants(change):
    n, w, p = setup_native()
    if change == "focus":
        n.is_foreground = lambda window: False
    elif change == "geometry":
        n.window = lambda hwnd: Window(10, 123, "game", Rect(50, 40, 320, 200))
    elif change == "pid":
        n.window = lambda hwnd: Window(10, 999, "game", w.rect)
    elif change == "monitor":
        n.window = lambda hwnd: Window(10, 123, "game", Rect(-100, 40, 320, 200))
    else:
        p.exclusions = [Rect(40, 40, 20, 20)]
    with pytest.raises(SafetyError):
        n.guard(w, time.monotonic(), p, (50, 50))


def test_cancellation_between_move_and_mouse_down():
    n, w, p = setup_native()
    n.pg.on_move = n.blocked.set
    with pytest.raises(SafetyError):
        n.execute(Action("attack", (50, 50)), w, time.monotonic(), p)
    assert n.pg.events == ["move"]


def test_exception_releases_owned_keys_mouse_and_restores_failsafe():
    n, w, p = setup_native()
    n.pg.fail_down = True
    with pytest.raises(RuntimeError):
        n.execute(Action("attack", (50, 50)), w, time.monotonic(), p)
    assert "up:ctrl" in n.pg.events and "mouse-up" in n.pg.events
    assert not n.keys and not n.mouse and n.pg.FAILSAFE


def test_successful_bounded_input_has_no_held_keys():
    n, w, p = setup_native()
    n.execute(Action("hp"), w, time.monotonic(), p)
    assert n.pg.events == ["down:1", "up:1"]
    assert not n.keys and n.pg.FAILSAFE
