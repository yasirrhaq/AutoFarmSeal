"""No native capture or input: exercise the beginner UI boundary with fake results."""
import time

import pytest

pytest.importorskip("PySide6")


def test_capture_button_emits_no_argument(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Profile
    from autofarmseal.storage import Store
    guide = SetupGuide(Profile(), Store(tmp_path), can_capture=True)
    qtbot.addWidget(guide)
    guide.show()
    requests = []
    guide.capture_requested.connect(lambda: requests.append(True))
    qtbot.mouseClick(guide.capture_button, Qt.MouseButton.LeftButton)
    assert requests == [True]
    assert guide.canvas.frame is None
    guide.reject()


def test_cancelled_capture_does_not_load_stale_image(qtbot, tmp_path, monkeypatch):
    import numpy as np
    from autofarmseal.guide import SetupGuide
    from autofarmseal.storage import Store
    from autofarmseal.ui import MainWindow
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    window.timer.stop()
    guide = SetupGuide(window.current(), window.store, parent=window)
    qtbot.addWidget(guide)
    window.guide = guide
    guide.capture_pending = True
    old_epoch = window.worker.epoch
    window.worker.command("stop")
    window.capture_wait = ("guide", old_epoch, time.monotonic())
    frame = np.random.default_rng(21).integers(0, 255, (250, 500, 3), dtype=np.uint8)
    monkeypatch.setattr(window.worker, "read", lambda: ({"state": "Capture selesai", "captured": frame}, []))
    window.poll()
    assert window.capture_wait is None
    assert not guide.capture_pending
    assert guide.canvas.frame is None
    assert "belum diambil" in guide.feedback.text()
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_successful_capture_returns_to_current_guide(qtbot, tmp_path, monkeypatch):
    import numpy as np
    from autofarmseal.guide import SetupGuide
    from autofarmseal.storage import Store
    from autofarmseal.ui import MainWindow
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    window.timer.stop()
    guide = SetupGuide(window.current(), window.store, parent=window)
    qtbot.addWidget(guide)
    window.guide = guide
    guide.capture_pending = True
    window.capture_wait = ("guide", window.worker.epoch, time.monotonic())
    frame = np.random.default_rng(22).integers(0, 255, (250, 500, 3), dtype=np.uint8)
    monkeypatch.setattr(window.worker, "read", lambda: ({"state": "Capture selesai", "captured": frame}, []))
    window.poll()
    assert window.capture_wait is None
    assert not guide.capture_pending
    assert guide.canvas.frame is not None
    assert guide.step == "source"
    assert guide.next_button.isEnabled()
    assert window.worker.engine is None
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())
