import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF
from autofarmseal.dialogs import Canvas, SettingsDialog
from autofarmseal.model import Profile
from autofarmseal.storage import Store
from autofarmseal.ui import MainWindow


def test_ui_safe_defaults_and_close(qtbot, tmp_path):
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    window.show()
    assert not window.live.isChecked()
    assert not window.live.isEnabled()
    assert window.profile_combo.count() == 1
    assert window.worker.engine is None
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_settings_cancel_does_not_mutate_profile(qtbot):
    p = Profile()
    dialog = SettingsDialog(p)
    qtbot.addWidget(dialog)
    dialog.fields["name"][0].setText("Changed")
    dialog.reject()
    assert p.name == "Monster baru"


def test_canvas_letterbox_mapping(qtbot):
    import numpy as np
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.set_frame(np.zeros((400, 800, 3), dtype=np.uint8))
    assert canvas.point(QPointF(400, 300)).x() == 400
    assert canvas.point(QPointF(400, 300)).y() == 200
    assert canvas.point(QPointF(5, 5)) is None
