"""Exercise UI button->real worker->capture mailbox->drag->save, not just slots."""
import time
from types import SimpleNamespace
import threading
import sys

import numpy as np
import pytest

pytest.importorskip("PySide6")


def scene():
    return np.random.default_rng(129).integers(30, 240, (300, 560, 3), np.uint8)


class Desktop:
    input_available = False
    def __init__(self):
        from autofarmseal.windows import Window
        from autofarmseal.model import Rect
        self.selected = Window(123, 321, "Seal test fixture", Rect(20, 30, 560, 300))
        self.blocked = threading.Event()
        self.blocked.set()
        self.activations = 0
        self.ready = True

    def window(self, hwnd):
        return self.selected

    def list_windows(self):
        return [self.selected]

    def request_foreground(self, expected):
        self.activations += 1
        return True

    def check_capture_window(self, expected):
        from autofarmseal.windows import FocusError
        if not self.ready:
            raise FocusError("game not active")
        return self.selected

    def halt(self):
        self.blocked.set()

    def execute(self, *args):
        raise AssertionError("Input must never be reached by a setup guide")


class Screen:
    def grab(self, region):
        frame = scene()
        return np.dstack((frame, np.full(frame.shape[:2], 255, np.uint8)))

    def close(self):
        pass


def main(qtbot, tmp_path, monkeypatch):
    from autofarmseal.storage import Store
    from autofarmseal.ui import MainWindow
    native = Desktop()
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    window.native = window.worker.native = native
    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=Screen))
    window.refresh_windows()
    window.show()
    return window


def drag(qtbot, canvas, points):
    from PySide6.QtCore import QPoint, Qt
    b = canvas.bounds()
    w, h = canvas.image.width(), canvas.image.height()
    a, c = [QPoint(round(b.x()+x*b.width()/w), round(b.y()+y*b.height()/h)) for x,y in points]
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=a)
    qtbot.mouseMove(canvas, c)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=c)


def test_button_worker_capture_drag_test_save(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    window = main(qtbot, tmp_path, monkeypatch)
    try:
        qtbot.mouseClick(window.guide_button, Qt.MouseButton.LeftButton)
        guide = window.guide
        assert guide is not None and guide.isVisible()
        qtbot.mouseClick(guide.capture_button, Qt.MouseButton.LeftButton)
        assert guide.capture_pending
        assert not guide.capture_button.isEnabled()
        assert not guide.file_button.isEnabled()
        qtbot.waitUntil(lambda: guide.canvas.frame is not None, timeout=6000)
        assert window.guide is guide
        assert not guide.capture_pending
        assert guide.next_button.isEnabled()
        assert np.array_equal(guide.canvas.frame, scene())
        qtbot.mouseClick(guide.next_button, Qt.MouseButton.LeftButton)
        drag(qtbot, guide.canvas, ((10, 10), (545, 280)))
        assert guide.next_button.isEnabled()
        qtbot.mouseClick(guide.next_button, Qt.MouseButton.LeftButton)
        drag(qtbot, guide.canvas, ((100, 100), (150, 150)))
        assert guide.next_button.isEnabled()
        qtbot.mouseClick(guide.next_button, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(guide.test_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: guide.test_done, timeout=4000)
        qtbot.waitUntil(lambda: not guide.test_thread.is_alive())
        assert not guide.next_button.isEnabled()
        assert "centang" in guide.requirement.text()
        qtbot.mouseClick(guide.ack, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(guide.next_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: window.guide is None)
        assert window.current().templates["monster"]
        assert not window.current().input_verified
        assert not window.live.isChecked()
        assert window.worker.engine is None
    finally:
        window.close()
        qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_failed_capture_preserves_actual_error_and_allows_retry(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    window = main(qtbot, tmp_path, monkeypatch)
    try:
        window.guided_setup()
        guide = window.guide
        def failed():
            raise RuntimeError("fixture capture backend unavailable")
        monkeypatch.setattr(window.worker, "_capture", failed)
        qtbot.mouseClick(guide.capture_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: not guide.capture_pending, timeout=5000)
        assert "fixture capture backend unavailable" in guide.feedback.text()
        assert guide.isVisible()
        assert guide.capture_button.isEnabled()
        assert guide.file_button.isEnabled()
        assert not guide.next_button.isEnabled()
        assert "ambil gambar" in guide.requirement.text()
    finally:
        window.close()
        qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_previous_pause_snapshot_cannot_cancel_new_capture(qtbot, tmp_path, monkeypatch):
    window = main(qtbot, tmp_path, monkeypatch)
    try:
        window.timer.stop()
        window.guided_setup()
        window.guide_capture()
        epoch = window.worker.epoch
        monkeypatch.setattr(window.worker, "read", lambda: ({"state": "Dijeda", "reason": "old"}, []))
        window.capture_wait = ("guide", epoch, time.monotonic()-1)
        window.poll()
        assert window.capture_wait is not None
        assert window.guide.capture_pending
    finally:
        window.close()
        qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_draft_save_does_not_require_detection_or_enable_input(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.storage import Store
    from autofarmseal.model import Profile, Rect
    from PySide6.QtCore import Qt
    store = Store(tmp_path)
    guide = SetupGuide(Profile(), store)
    qtbot.addWidget(guide)
    guide.show()
    guide.set_frame(scene())
    guide.advance()
    guide.select(Rect(0, 0, 560, 300))
    guide.advance()
    guide.select(Rect(100, 100, 50, 50))
    guide.advance()
    assert not guide.next_button.isEnabled()
    assert guide.draft_button.isEnabled()
    qtbot.mouseClick(guide.draft_button, Qt.MouseButton.LeftButton)
    assert guide.saved
    assert not store.list_profiles()[0][0].input_verified


def test_guide_has_visible_reason_for_each_missing_step(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Profile
    from autofarmseal.storage import Store
    guide = SetupGuide(Profile(), Store(tmp_path))
    qtbot.addWidget(guide)
    guide.show()
    assert guide.requirement.isVisible()
    assert "ambil gambar" in guide.requirement.text()
    assert guide.capture_button.isEnabled()
    guide.set_frame(scene())
    guide.advance()
    assert "kotak area dunia" in guide.requirement.text()
    guide.reject()


def test_resolution_reset_is_explicit_and_cancel_preserves_disk(qtbot, tmp_path, monkeypatch):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Profile, Rect
    from autofarmseal.storage import Store
    from PySide6.QtWidgets import QMessageBox
    store = Store(tmp_path)
    p = Profile(width=200, height=120, regions={"world": Rect(0,0,200,120)})
    store.save(p)
    before = (store.root/'profiles'/f'{p.id}.json').read_bytes()
    guide = SetupGuide(p, store)
    qtbot.addWidget(guide)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)
    assert not guide.receive_frame(scene())
    assert guide.p.width == 200
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    assert guide.receive_frame(scene())
    assert guide.p.width == 560 and not guide.p.regions
    guide.reject()
    assert (store.root/'profiles'/f'{p.id}.json').read_bytes() == before


def test_double_capture_and_f8_cannot_replace_active_request(qtbot, tmp_path, monkeypatch):
    window = main(qtbot, tmp_path, monkeypatch)
    try:
        window.guided_setup()
        window.guide_capture()
        epoch = window.worker.epoch
        window.guide_capture()
        window.hotkey("arm", epoch)
        assert window.worker.epoch == epoch
        window.cancel_snapshot()
        assert not window.guide.capture_pending
        assert window.guide.capture_button.isEnabled()
        assert window.guide.canvas.frame is None
    finally:
        window.close()
        qtbot.waitUntil(lambda: not window.worker.is_alive())
