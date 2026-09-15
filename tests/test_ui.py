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


def test_old_queued_start_cannot_undo_stop(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    starts = []
    monkeypatch.setattr(window, "start_session", lambda: starts.append("start"))
    old_epoch = window.worker.epoch
    window.worker.command("stop")
    window.hotkey("arm", old_epoch)
    assert starts == []
    window.hotkey("arm", window.worker.epoch)
    assert starts == ["start"]
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_closing_never_accepts_a_start(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    starts = []
    monkeypatch.setattr(window, "start_session", lambda: starts.append("start"))
    window.worker.close()
    window.hotkey("arm", window.worker.epoch)
    assert starts == []
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_beginner_screen_hides_technical_controls(qtbot, tmp_path):
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    window.show()
    assert window.advanced_panel.isHidden()
    assert window.guide_button.isVisible()
    assert not window.observe_button.isEnabled()
    assert not window.live.isChecked()
    window.advanced_button.setChecked(True)
    assert not window.advanced_panel.isHidden()
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())


def test_hotkey_cannot_arm_during_minimized_guide(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    starts = []
    monkeypatch.setattr(window, "start_session", lambda: starts.append(1))
    window.guide = object()
    window.hotkey("arm", window.worker.epoch)
    assert not starts
    window.guide = None
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())


def guide_scene():
    import numpy as np
    rng = np.random.default_rng(18)
    return rng.integers(20, 230, (260, 520, 3), dtype=np.uint8)


def test_setup_guide_cancel_is_transactional(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Rect
    store = Store(tmp_path)
    original = Profile(input_verified=True)
    store.save(original)
    before = (store.root / "profiles" / f"{original.id}.json").read_bytes()
    guide = SetupGuide(original, store)
    qtbot.addWidget(guide)
    guide.set_frame(guide_scene())
    guide.advance()
    guide.select(Rect(0, 0, 500, 250))
    guide.advance()
    guide.select(Rect(100, 80, 45, 40))
    assert guide.pending
    assert not list((store.root / "templates").glob("*.png"))
    guide.reject()
    assert (store.root / "profiles" / f"{original.id}.json").read_bytes() == before
    assert original.input_verified


def test_four_step_guide_saves_only_after_input_free_test(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Rect
    store = Store(tmp_path)
    original = Profile()
    store.save(original)
    guide = SetupGuide(original, store)
    qtbot.addWidget(guide)
    assert not guide.next_button.isEnabled()
    guide.set_frame(guide_scene())
    guide.name.setText("Contoh percobaan")
    guide.advance()
    guide.select(Rect(0, 0, 500, 250))
    guide.advance()
    guide.select(Rect(100, 80, 45, 40))
    guide.advance()
    assert guide.step == "review"
    guide.ack.setChecked(True)
    guide.accept()
    assert not guide.saved
    guide.run_test()
    qtbot.waitUntil(lambda: guide.test_done, timeout=5000)
    qtbot.waitUntil(lambda: not guide.test_thread.is_alive())
    assert guide.canvas.boxes
    guide.ack.setChecked(True)
    guide.accept()
    assert guide.saved
    result, errors = store.list_profiles()
    assert not errors and result[0].name == "Contoh percobaan"
    assert not result[0].input_verified
    assert "combat" not in result[0].regions
    assert store.asset(result[0].templates["monster"][0]).is_file()


def test_guide_rejects_new_resolution_without_reset(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Rect
    profile = Profile(width=500, height=250, regions={"world": Rect(0, 0, 500, 250)})
    guide = SetupGuide(profile, Store(tmp_path))
    qtbot.addWidget(guide)
    with pytest.raises(ValueError, match="Ukuran gambar berbeda"):
        guide.set_frame(guide_scene())
    assert guide.p.regions == profile.regions
    assert guide.canvas.frame is None
    guide.reject()


def test_guide_requires_name_and_ignores_outside_monster(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Rect
    guide = SetupGuide(Profile(), Store(tmp_path))
    qtbot.addWidget(guide)
    guide.set_frame(guide_scene())
    guide.name.setText("")
    assert not guide.next_button.isEnabled()
    guide.name.setText("Monster")
    guide.advance()
    guide.select(Rect(0, 0, 80, 80))
    guide.advance()
    guide.select(Rect(100, 100, 30, 30))
    assert not guide.pending
    assert not guide.step_ready()
    guide.reject()


def test_hp_guide_samples_inside_bar_only(qtbot, tmp_path):
    from autofarmseal.guide import SetupGuide
    from autofarmseal.model import Rect
    frame = guide_scene()
    frame[20:30, 20:120] = (20, 220, 220)
    frame[20:30, 120:220] = (0, 0, 0)
    guide = SetupGuide(Profile(), Store(tmp_path), mode="hp")
    qtbot.addWidget(guide)
    guide.set_frame(frame)
    guide.advance()
    guide.select(Rect(20, 20, 200, 10))
    guide.advance()
    guide.sample((300, 80))
    assert not guide.sampled_ok
    guide.sample((30, 25))
    assert guide.sampled_ok
    guide.advance()
    assert "50%" in guide.feedback.text()
    guide.ack.setChecked(True)
    guide.accept()
    assert not guide.p.input_verified
    assert not guide.p.hp_enabled


def test_simple_controls_never_reuses_verification(qtbot):
    from autofarmseal.guide import SimpleControls
    profile = Profile(input_verified=True)
    dialog = SimpleControls(profile)
    qtbot.addWidget(dialog)
    assert not dialog.verified.isChecked()
    dialog.save()
    assert not dialog.p.input_verified
    assert profile.input_verified


def test_one_image_observation_cannot_create_input_plan(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Store(tmp_path), smoke=True)
    qtbot.addWidget(window)
    from autofarmseal.model import Rect
    frame = guide_scene()
    p = window.current()
    p.width, p.height = 520, 260
    p.regions["world"] = Rect(0, 0, 500, 250)
    p.templates["monster"] = [window.store.image(frame[80:120, 100:145])]
    commands = []
    monkeypatch.setattr(window.worker, "command", lambda kind, spec=None: commands.append((kind, spec)))
    window.test_snapshot(frame)
    _, spec = commands[-1]
    assert not spec.live
    assert spec.window is None
    assert spec.image is frame
    window.close()
    qtbot.waitUntil(lambda: not window.worker.is_alive())
