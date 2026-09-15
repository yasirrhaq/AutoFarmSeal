"""One capture/vision worker, one latest-value mailbox, zero frame backlogs.

The UI owns widgets. This worker owns MSS/Detector/Engine. Emergency inhibition
is out-of-band and every mutating command has an epoch so an old queued Start
cannot undo a newer Stop. Offline observations never instantiate an input plan.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import cv2
import numpy as np

from .engine import Engine, State
from .model import Profile
from .storage import Store
from .vision import Detector
from .windows import Native, SafetyError, Window


@dataclass
class RunSpec:
    profile: Profile
    window: Window | None = None
    image: np.ndarray | None = None
    live: bool = False
    permitted: bool = False
    hotkeys_ready: bool = False


class Worker(threading.Thread):
    def __init__(self, store: Store, native: Native | None):
        super().__init__(name="capture-vision", daemon=False)
        self.store, self.native = store, native
        self.commands: queue.Queue = queue.Queue(maxsize=8)
        self.wake = threading.Event()
        self.closing = threading.Event()
        self.lock = threading.RLock()
        self.epoch = 0
        self.latest: dict = {"state": "Siap", "reason": "Pilih profil dan kalibrasikan layar."}
        self.logs: deque[str] = deque(maxlen=200)
        self.preview_visible = False
        self.spec: RunSpec | None = None
        self.detector: Detector | None = None
        self.engine: Engine | None = None
        self.running = False
        self.capture_at: float | None = None
        self.observe_until = 0.0
        self.sct = None
        self.last_frame = None
        self.last_state = None
        self.logger = logging.getLogger(f"autofarmseal.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = RotatingFileHandler(store.root / "logs" / "events.jsonl",
                                           maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        self.logger.addHandler(self.handler)

    def event(self, message: str, **extra):
        entry = {"time": datetime.now(timezone.utc).isoformat(), "message": message, **extra}
        self.logger.info(json.dumps(entry, ensure_ascii=False))
        with self.lock:
            self.logs.append(f"{datetime.now():%H:%M:%S}  {message}")

    def command(self, kind: str, spec: RunSpec | None = None):
        with self.lock:
            self.epoch += 1
            epoch = self.epoch
            if self.native:
                self.native.halt()
            if spec:
                spec = RunSpec(spec.profile.clone(), spec.window, spec.image, spec.live,
                               spec.permitted, spec.hotkeys_ready)
            while self.commands.full():
                try:
                    self.commands.get_nowait()
                except queue.Empty:
                    break
            self.commands.put_nowait((epoch, kind, spec))
        self.wake.set()

    def read(self) -> tuple[dict, list[str]]:
        with self.lock:
            snapshot = self.latest.copy()
            self.latest.pop("captured", None)
            logs = list(self.logs)
            self.logs.clear()
            return snapshot, logs

    def publish(self, **values):
        with self.lock:
            self.latest = values

    def close(self):
        self.closing.set()
        if self.native:
            self.native.halt()
        self.wake.set()

    def _capture(self) -> tuple[np.ndarray, Window, float]:
        if not self.native or not self.spec or not self.spec.window:
            raise SafetyError("Pilih window game Windows terlebih dahulu.")
        window = self.native.check_window(self.spec.window)
        if self.sct is None:
            import mss
            self.sct = mss.mss()
        start = time.monotonic()
        r = window.rect
        shot = self.sct.grab({"left": r.x, "top": r.y, "width": r.w, "height": r.h})
        return np.asarray(shot)[:, :, :3].copy(), window, start

    def _apply_command(self, epoch: int, kind: str, spec: RunSpec | None):
        if epoch != self.epoch:
            return
        now = time.monotonic()
        self.capture_at = None
        if kind in {"pause", "stop"}:
            self.running = False
            if self.engine:
                if kind == "pause":
                    self.engine.pause(now, "Dijeda pengguna. F8 untuk lanjut setelah kembali ke game.")
                else:
                    self.engine.stop(now)
                self.publish(**self.engine.summary(now))
            else:
                self.publish(state="Dijeda" if kind == "pause" else "Berhenti",
                             reason="Tidak ada input otomatis yang berjalan.")
            self.event(self.latest["state"])
            return
        if spec is None:
            raise ValueError("Konfigurasi tidak tersedia.")
        if kind == "snapshot":
            self.spec = spec
            self.running = False
            self.capture_at = now + 4
            self.publish(state="Capture dalam 4 detik", reason="Aktifkan game sekarang.")
            return
        errors = spec.profile.validate(calibrated=True, live=spec.live)
        if errors:
            raise ValueError("\n".join(errors))
        if spec.live and (spec.image is not None or not self.native or not spec.window
                          or not spec.permitted or not spec.hotkeys_ready):
            raise SafetyError("Mode input membutuhkan Windows, izin lingkungan, dan hotkey darurat aktif.")
        detector = Detector(spec.profile, self.store.read_image)
        preserve = (self.engine is not None and self.engine.state == State.PAUSED
                    and self.spec is not None and self.spec.profile.to_dict() == spec.profile.to_dict()
                    and self.spec.window == spec.window and spec.live)
        self.spec, self.detector = spec, detector
        if spec.live:
            if not preserve:
                self.engine = Engine(spec.profile)
            self.engine.arm(now)
            with self.lock:
                if epoch == self.epoch and not self.closing.is_set():
                    self.native.blocked.clear()
        else:
            self.engine = None
        self.observe_until = now + 4 if spec.window and not spec.live else 0.0
        self.running = True
        self.event("Sesi input disiapkan" if spec.live else "Observasi tanpa input dimulai")

    def _failure(self, exc: Exception):
        if self.native:
            self.native.halt()
        self.running = False
        self.capture_at = None
        message = str(exc) or type(exc).__name__
        now = time.monotonic()
        if self.engine:
            self.engine.pause(now, message)
            self.publish(**self.engine.summary(now))
        else:
            self.publish(state="Dijeda", reason=message)
        self.event(message, level="warning")
        if self.spec and self.spec.profile.screenshot_failures and self.last_frame is not None:
            folder = self.store.root / "diagnostics"
            path = folder / f"failure-{time.time_ns()}.png"
            ok, data = cv2.imencode(".png", self.last_frame)
            if ok:
                path.write_bytes(data.tobytes())
            for old in sorted(folder.glob("failure-*.png"))[:-10]:
                old.unlink(missing_ok=True)

    def _step(self, epoch: int):
        spec, detector = self.spec, self.detector
        now = time.monotonic()
        if self.capture_at is not None:
            if now >= self.capture_at:
                image, _, _ = self._capture()
                self.capture_at = None
                if epoch == self.epoch:
                    self.publish(state="Capture selesai", reason="Kalibrasikan gambar client game.",
                                 captured=image)
            return
        if not self.running or spec is None or detector is None:
            return
        if not self.engine and now < self.observe_until:
            self.publish(state="Observasi disiapkan", reason="Kembali ke game; mulai dalam 4 detik.")
            return
        if self.engine and self.engine.state == State.ARMED and now < self.engine.arm_until:
            self.publish(**self.engine.summary(now))
            return
        if spec.image is not None:
            frame, window, captured_at = spec.image, None, time.monotonic()
        else:
            frame, window, captured_at = self._capture()
        self.last_frame = frame
        search = not self.engine or self.engine.state in {State.ARMED, State.SEARCH}
        obs = detector.observe(frame, captured_at, search=search,
                               cancelled=lambda: self.closing.is_set() or epoch != self.epoch)
        if epoch != self.epoch or self.closing.is_set():
            return
        now = time.monotonic()
        if self.engine:
            action = self.engine.tick(obs, now)
            if action:
                self.native.execute(action, window, captured_at, spec.profile)
                self.engine.ack(action, time.monotonic())
                self.event(f"Input {action.kind} dikirim", kind=action.kind)
            summary = self.engine.summary(now)
            state_key = (summary["state"], summary["reason"])
            if state_key != self.last_state:
                self.event(summary["reason"], state=summary["state"])
                self.last_state = state_key
            if self.engine.state in {State.PAUSED, State.STOPPED}:
                self.native.halt()
                self.running = False
        else:
            summary = {"state": "Observasi / TANPA INPUT",
                       "reason": "Hasil visual saja; tidak ada klik atau tombol dikirim."}
        self.publish(**summary, obs=obs, image=frame if self.preview_visible else None,
                     frame_age_ms=(now-captured_at)*1000)
        if spec.image is not None:
            self.running = False

    def run(self):
        cv2.setNumThreads(1)
        try:
            while not self.closing.is_set():
                start = time.monotonic()
                epoch = self.epoch
                try:
                    while True:
                        try:
                            item = self.commands.get_nowait()
                        except queue.Empty:
                            break
                        self._apply_command(*item)
                    epoch = self.epoch
                    self._step(epoch)
                except Exception as exc:
                    try:
                        self._failure(exc)
                    except Exception:
                        self.running = False
                        if self.native:
                            self.native.blocked.set()
                hz = self.spec.profile.scan_hz if self.spec and self.running else 10
                self.wake.wait(max(0.01, 1/hz - (time.monotonic()-start)))
                self.wake.clear()
        finally:
            if self.native:
                self.native.halt()
            if self.sct:
                self.sct.close()
            self.handler.close()
            self.logger.removeHandler(self.handler)
