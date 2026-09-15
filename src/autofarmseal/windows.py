"""Normal desktop APIs only. No process memory, injection or rendering hooks.

Live input supports a visible client wholly on the primary monitor. HWND + PID,
geometry, foreground, and capture age are checked again before each input down.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

from .engine import Action
from .model import Profile, Rect


class SafetyError(RuntimeError):
    pass


class FocusError(SafetyError):
    """Recoverable while waiting for an explicitly requested screenshot."""
    pass


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    rect: Rect


def enable_dpi_awareness():
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass


class Native:
    def __init__(self):
        if sys.platform != "win32":
            raise SafetyError("Kontrol game hanya didukung di Windows. Gunakan mode gambar offline.")
        import win32api
        import win32gui
        import win32process
        self.gui, self.api, self.proc = win32gui, win32api, win32process
        self.pg = None
        self.input_error = ""
        try:
            import pyautogui
            self.pg = pyautogui
            self.pg.FAILSAFE = True
            self.pg.PAUSE = 0.02
        except Exception as exc:
            # Screen observation remains available even if input cannot initialize.
            self.input_error = f"{type(exc).__name__}: {exc}"
        self.blocked = threading.Event()
        self.blocked.set()
        self.lock = threading.RLock()
        self.keys: set[str] = set()
        self.mouse = False

    def window(self, hwnd: int) -> Window:
        if not self.gui.IsWindow(hwnd) or not self.gui.IsWindowVisible(hwnd) or self.gui.IsIconic(hwnd):
            raise SafetyError("Window game ditutup, disembunyikan, atau diminimalkan.")
        _, pid = self.proc.GetWindowThreadProcessId(hwnd)
        left, top, right, bottom = self.gui.GetClientRect(hwnd)
        x, y = self.gui.ClientToScreen(hwnd, (left, top))
        rect = Rect(x, y, right-left, bottom-top)
        if rect.w < 100 or rect.h < 100:
            raise SafetyError("Area client terlalu kecil.")
        return Window(hwnd, pid, self.gui.GetWindowText(hwnd), rect)

    def list_windows(self) -> list[Window]:
        result = []
        def visit(hwnd, _):
            try:
                w = self.window(hwnd)
                if w.title and w.pid != os.getpid():
                    result.append(w)
            except (SafetyError, self.gui.error):
                pass
        self.gui.EnumWindows(visit, None)
        return sorted(result, key=lambda w: w.title.lower())

    def is_foreground(self, window: Window) -> bool:
        return self.gui.GetForegroundWindow() == window.hwnd

    @property
    def input_available(self) -> bool:
        return self.pg is not None

    def request_foreground(self, expected: Window) -> bool:
        """Best effort after a user capture click. Never simulate keys/force locks."""
        actual = self.window(expected.hwnd)
        if actual.pid != expected.pid:
            raise SafetyError("Identitas game berubah. Pilih game kembali.")
        try:
            self.gui.SetForegroundWindow(expected.hwnd)
        except self.gui.error:
            return False  # OS may deny; wait for the user to select the game.
        return self.is_foreground(actual)

    def check_capture_window(self, expected: Window) -> Window:
        actual = self.window(expected.hwnd)
        if actual.pid != expected.pid:
            raise SafetyError("Identitas proses berubah. Pilih game kembali.")
        if not self.is_foreground(actual):
            raise FocusError("Klik jendela game yang dipilih; aplikasi masih menunggu game aktif.")
        # Screenshot-only operations can use secondary monitors. Live guards below
        # deliberately retain the original primary-monitor requirement.
        desktop = Rect(self.api.GetSystemMetrics(76), self.api.GetSystemMetrics(77),
                       self.api.GetSystemMetrics(78), self.api.GetSystemMetrics(79))
        r = actual.rect
        if not (desktop.contains(r.x, r.y) and desktop.contains(r.right-1, r.bottom-1)):
            raise SafetyError("Jendela game sebagian di luar layar. Pindahkan agar terlihat seluruhnya.")
        return actual

    def check_window(self, expected: Window) -> Window:
        actual = self.window(expected.hwnd)
        if actual.pid != expected.pid:
            raise SafetyError("Identitas proses game berubah. Pilih window kembali.")
        if not self.is_foreground(actual):
            raise SafetyError("Window game tidak aktif.")
        if not actual.rect.valid_in((self.api.GetSystemMetrics(0), self.api.GetSystemMetrics(1))):
            raise SafetyError("Mode input memerlukan game sepenuhnya pada monitor utama.")
        return actual

    def guard(self, expected: Window, captured_at: float, profile: Profile,
              point: tuple[int, int] | None = None):
        if self.pg is None:
            raise SafetyError("Input Windows belum tersedia: " + self.input_error)
        if self.blocked.is_set():
            raise SafetyError("Input diblokir oleh jeda/berhenti.")
        if not 0 <= time.monotonic() - captured_at <= profile.max_frame_age:
            raise SafetyError("Hasil deteksi terlalu lama untuk digunakan.")
        actual = self.check_window(expected)
        if actual.rect != expected.rect or (actual.rect.w, actual.rect.h) != (profile.width, profile.height):
            raise SafetyError("Window bergerak/berubah ukuran setelah capture.")
        if point is not None:
            world = profile.regions["world"]
            if not world.contains(*point) or any(r.contains(*point) for r in profile.exclusions):
                raise SafetyError("Titik klik berada di luar area yang diizinkan.")
        return actual

    def halt(self):
        self.blocked.set()
        self.release_all()

    def release_all(self):
        with self.lock:
            if self.pg is None:
                return
            # This bypass is ONLY for releasing our held inputs after a corner
            # fail-safe. All input-down operations keep FAILSAFE enabled.
            old = self.pg.FAILSAFE
            self.pg.FAILSAFE = False
            try:
                for key in list(self.keys):
                    try:
                        self.pg.keyUp(key)
                    finally:
                        self.keys.discard(key)
                if self.mouse:
                    self.pg.mouseUp(button="left")
                    self.mouse = False
            finally:
                self.pg.FAILSAFE = old

    def execute(self, action: Action, expected: Window, captured_at: float, p: Profile):
        with self.lock:
            self.guard(expected, captured_at, p, action.point)
            try:
                if action.kind == "attack":
                    if action.point is None:
                        raise SafetyError("Koordinatat target kosong.")
                    x, y = action.point
                    self.pg.moveTo(expected.rect.x+x, expected.rect.y+y, duration=0)
                    if p.ctrl_click:
                        self.guard(expected, captured_at, p, action.point)
                        self.keys.add("ctrl")
                        self.pg.keyDown("ctrl")
                    self.guard(expected, captured_at, p, action.point)
                    self.mouse = True
                    self.pg.mouseDown(button="left")
                    self.blocked.wait(0.04)
                    self.release_all()
                    if p.attack_key:
                        self._key(p.attack_key, expected, captured_at, p)
                elif action.kind in {"hp", "ap", "pickup"}:
                    key = getattr(p, {"hp": "hp_key", "ap": "ap_key", "pickup": "pickup_key"}[action.kind])
                    self._key(key, expected, captured_at, p)
                else:
                    raise SafetyError("Tindakan tidak dikenal.")
            finally:
                self.release_all()

    def _key(self, key, expected, captured_at, p):
        self.guard(expected, captured_at, p)
        if not key or key not in self.pg.KEYBOARD_KEYS:
            raise SafetyError("Tombol input tidak valid.")
        self.keys.add(key)
        self.pg.keyDown(key)
        self.blocked.wait(0.04)
        self.release_all()


class Hotkeys:
    """Only F8/F9/F10 commands are exposed; no text/key history is recorded."""
    def __init__(self, callback):
        self.listener = None
        self.error = ""
        if sys.platform != "win32":
            self.error = "Hotkey global hanya tersedia di Windows."
            return
        try:
            from pynput.keyboard import GlobalHotKeys
            self.listener = GlobalHotKeys({
                "<f8>": lambda: callback("arm"),
                "<f9>": lambda: callback("pause"),
                "<f10>": lambda: callback("stop"),
            })
            self.listener.start()
            self.listener.wait()
        except Exception as exc:
            self.error = f"Hotkey gagal: {exc}"
            self.close()

    @property
    def ready(self) -> bool:
        return self.listener is not None and self.listener.is_alive()

    def close(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
