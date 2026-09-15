import time
from dataclasses import replace

import numpy as np

from autofarmseal.model import Profile, Rect
from autofarmseal.runtime import RunSpec, Worker
from autofarmseal.storage import Store


def spec_with_image(store):
    frame = np.random.default_rng(2).integers(0, 255, (100, 200, 3), np.uint8)
    template = store.image(frame[20:50, 30:60])
    p = Profile(width=200, height=100, regions={"world": Rect(0, 0, 200, 100)})
    p.templates["monster"] = [template]
    p.scales = [1.0]
    return RunSpec(p, image=frame)


def wait_until(predicate, timeout=3):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Worker timeout")


def test_offline_worker_no_input_and_shutdown(tmp_path):
    store = Store(tmp_path)
    worker = Worker(store, None)
    worker.preview_visible = True
    worker.start()
    try:
        worker.command("arm", spec_with_image(store))
        wait_until(lambda: "obs" in worker.read()[0])
        snap, _ = worker.read()
        assert snap["state"] == "Observasi / TANPA INPUT"
        assert len(snap["obs"].detections) >= 1
        assert worker.engine is None
        assert worker.latest["image"] is not None
    finally:
        worker.close()
        worker.join(3)
    assert not worker.is_alive()


def test_new_stop_invalidates_queued_arm(tmp_path):
    store = Store(tmp_path)
    worker = Worker(store, None)
    worker.command("arm", spec_with_image(store))
    old = worker.commands.get_nowait()
    worker.command("stop")
    worker._apply_command(*old)
    assert not worker.running
    assert worker.engine is None
    worker.handler.close()


def test_bounded_queue_never_replays_old_start(tmp_path):
    worker = Worker(Store(tmp_path), None)
    for _ in range(50):
        worker.command("pause")
    worker.command("stop")
    assert worker.commands.qsize() <= 8
    while not worker.commands.empty():
        worker._apply_command(*worker.commands.get_nowait())
    assert worker.latest["state"] == "Berhenti"
    worker.handler.close()


def test_live_refuses_offline_image(tmp_path):
    store = Store(tmp_path)
    worker = Worker(store, None)
    worker.start()
    try:
        worker.command("arm", replace(spec_with_image(store), live=True))
        wait_until(lambda: worker.latest.get("state") == "Dijeda")
        assert not worker.running
    finally:
        worker.close()
        worker.join(3)


def test_snapshot_error_is_correlated_and_preserves_reason(tmp_path):
    worker = Worker(Store(tmp_path), None)
    try:
        request = worker.command("snapshot", RunSpec(Profile()))
        worker._apply_command(*worker.commands.get_nowait())
        worker._failure(RuntimeError("test driver unavailable"))
        snap, _ = worker.read()
        assert snap["capture_epoch"] == request
        assert "test driver unavailable" in snap["capture_error"]
        assert not worker.running and worker.engine is None
    finally:
        worker.handler.close()


def test_focus_wait_is_bounded_but_not_fixed_four_second_deadline(tmp_path):
    from autofarmseal.windows import FocusError
    worker = Worker(Store(tmp_path), None)
    try:
        request = worker.command("snapshot", RunSpec(Profile()))
        worker._apply_command(*worker.commands.get_nowait())
        def not_focused():
            raise FocusError("waiting for user")
        worker._capture = not_focused
        worker.capture_at = time.monotonic()-1
        worker._step(request)
        assert worker.latest["capture_epoch"] == request
        assert worker.latest["state"] == "Menunggu game aktif"
        worker.capture_deadline = time.monotonic()-1
        import pytest
        with pytest.raises(RuntimeError, match="15 detik"):
            worker._step(request)
    finally:
        worker.handler.close()
