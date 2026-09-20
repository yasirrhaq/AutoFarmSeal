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
from .learner import MultiPoseLearner
from .model import Profile, Rect
from .storage import Store
from .vision import Detector
from .windows import FocusError, Native, SafetyError, Window


@dataclass
class RunSpec:
    profile: Profile
    window: Window | None = None
    image: np.ndarray | None = None
    live: bool = False
    permitted: bool = False
    hotkeys_ready: bool = False
    learn_seed: np.ndarray | None = None
    learn_seed_rect: Rect | None = None


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
        self.capture_deadline = 0.0
        self.capture_epoch: int | None = None
        self.learn_epoch: int | None = None
        self.learn_deadline = 0.0
        self.learn_started = 0.0
        self.learner: MultiPoseLearner | None = None
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
                seed = spec.learn_seed.copy() if spec.learn_seed is not None else None
                spec = RunSpec(spec.profile.clone(), spec.window, spec.image, spec.live,
                               spec.permitted, spec.hotkeys_ready, seed, spec.learn_seed_rect)
            while self.commands.full():
                try:
                    self.commands.get_nowait()
                except queue.Empty:
                    break
            self.commands.put_nowait((epoch, kind, spec))
        self.wake.set()
        return epoch

    def read(self) -> tuple[dict, list[str]]:
        with self.lock:
            snapshot = self.latest.copy()
            self.latest.pop("captured", None)
            self.latest.pop("learned_crops", None)
            self.latest.pop("learning_done", None)
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
        if self.capture_epoch is not None or not self.spec.live:
            window = self.native.check_capture_window(self.spec.window)
        else:
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
        self.capture_epoch = None
        self.learn_epoch = None
        self.learner = None
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
            self.engine = None
            self.detector = None
            self.capture_epoch = epoch
            self.capture_at = now + 1.0
            self.capture_deadline = now + 15.0
            self.publish(state="Menunggu gambar", capture_epoch=epoch,
                         reason="Klik game yang dipilih. Menunggu hingga 15 detik; tidak ada input game.")
            return
        if kind == "learn":
            if not self.native or not spec.window:
                raise SafetyError("Belajar otomatis membutuhkan jendela game Windows yang terlihat.")
            if spec.learn_seed is None or spec.learn_seed_rect is None:
                raise ValueError("Pilih satu monster pada gambar sebelum Belajar otomatis.")
            if "world" not in spec.profile.regions:
                raise ValueError("Tandai area pencarian monster terlebih dahulu.")
            if (spec.profile.width, spec.profile.height) == (0, 0):
                raise ValueError("Ambil satu gambar game terlebih dahulu.")
            self.spec = spec
            self.running = True
            self.engine = None
            self.detector = None
            self.learn_epoch = epoch
            self.learn_deadline = now + 15.0
            self.learn_started = 0.0
            self.learner = None
            self.publish(state="Menunggu belajar", learn_epoch=epoch, learning=True,
                         reason="Aktifkan game yang dipilih. Belajar dimulai saat game terlihat; tidak ada input game.")
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
        message = f"{type(exc).__name__}: {exc}"
        if self.learn_epoch is not None:
            request_id, self.learn_epoch = self.learn_epoch, None
            partial = self.learner.finalize() if self.learner is not None else []
            self.learner = None
            self.publish(state="Belajar berhenti", reason=message, learn_epoch=request_id,
                         learning_error=message, learned_crops=partial, learning_done=True)
            self.event("Belajar monster berhenti: " + message, level="warning")
            return
        if self.capture_epoch is not None:
            request_id, self.capture_epoch = self.capture_epoch, None
            self.publish(state="Capture gagal", reason=message,
                         capture_epoch=request_id, capture_error=message)
            self.event("Gagal mengambil gambar: " + message, level="warning")
            return
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
        if self.learn_epoch is not None:
            request_id = self.learn_epoch
            try:
                frame, window, captured_at = self._capture()
                after = self.native.check_capture_window(window)
                if after.rect != window.rect:
                    raise SafetyError("Jendela berubah ukuran/posisi saat belajar. Coba lagi.")
            except FocusError:
                if now >= self.learn_deadline:
                    raise SafetyError("Game belum aktif setelah 15 detik. Tekan Belajar lagi lalu aktifkan game.")
                self.publish(state="Menunggu game aktif", learn_epoch=request_id, learning=True,
                             reason=f"Klik game yang dipilih. Sisa {max(1, int(self.learn_deadline-now))} detik.")
                return
            if (frame.shape[1], frame.shape[0]) != (spec.profile.width, spec.profile.height):
                raise SafetyError("Ukuran jendela game berbeda dari gambar contoh. Pertahankan ukuran window saat belajar.")
            if self.learner is None:
                self.learner = MultiPoseLearner(
                    frame, spec.learn_seed, spec.profile.regions["world"],
                    initial_box=spec.learn_seed_rect, max_samples=spec.profile.learn_samples)
                self.learn_started = now
                self.learn_deadline = now + spec.profile.learn_seconds
                self.event("Belajar monster dimulai", seconds=spec.profile.learn_seconds)
            progress = self.learner.update(frame, now)
            elapsed = max(0.0, now-self.learn_started)
            left = max(0.0, self.learn_deadline-now)
            done = now >= self.learn_deadline or len(self.learner.samples) >= spec.profile.learn_samples
            if done:
                crops = self.learner.finalize()
                self.learn_epoch = None
                self.learner = None
                self.running = False
                self.publish(state="Belajar selesai", reason=f"{len(crops)} contoh visual baru ditemukan.",
                             learn_epoch=request_id, learning=False, learning_done=True,
                             learned_crops=crops, learn_frames=progress.frames,
                             learn_samples=len(crops), learn_confidence=progress.confidence)
                self.event("Belajar monster selesai", frames=progress.frames, samples=len(crops))
            else:
                self.publish(state="Belajar monster", reason=f"Biarkan monster bergerak. Sisa {left:.0f} detik.",
                             learn_epoch=request_id, learning=True, learn_elapsed=elapsed,
                             learn_seconds=spec.profile.learn_seconds, learn_frames=progress.frames,
                             learn_samples=progress.samples, learn_confidence=progress.confidence,
                             learn_box=progress.box)
            return
        if self.capture_at is not None:
            if now >= self.capture_at:
                try:
                    image, window, captured_at = self._capture()
                    after = self.native.check_capture_window(window)
                    if after.rect != window.rect:
                        raise SafetyError("Jendela berubah saat gambar diambil. Coba lagi.")
                except FocusError:
                    if now >= self.capture_deadline:
                        raise SafetyError("Game belum aktif setelah 15 detik. Pilih game yang benar, "
                                          "tekan Ambil gambar, lalu klik game. Alternatif: Pakai gambar yang sudah ada.")
                    self.publish(state="Menunggu game aktif", capture_epoch=epoch,
                                 reason=f"Klik game yang dipilih. Sisa {max(1, int(self.capture_deadline-now))} detik.")
                    return
                self.capture_at = None
                self.capture_epoch = None
                if epoch == self.epoch:
                    self.publish(state="Capture selesai", reason="Gambar berhasil diambil.",
                                 captured=image, capture_epoch=epoch, captured_at=captured_at,
                                 captured_window=window.title)
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
        obs = detector.observe(
            frame, captured_at, search=search,
            cancelled=lambda: self.closing.is_set() or epoch != self.epoch,
            # Temporal smoothing is observation-only. Future live input must never
            # act on a held/weak frame without its own validated combat design.
            temporal=(self.engine is None and spec.image is None),
        )
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
                hz = (8 if self.learn_epoch is not None else
                      self.spec.profile.scan_hz if self.spec and self.running else 10)
                self.wake.wait(max(0.01, 1/hz - (time.monotonic()-start)))
                self.wake.clear()
        finally:
            if self.native:
                self.native.halt()
            if self.sct:
                self.sct.close()
            self.handler.close()
            self.logger.removeHandler(self.handler)
