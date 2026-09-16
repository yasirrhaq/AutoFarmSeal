"""Opt-in native desktop fixture test; never captures a game or emits OS inputs.

Unlike --smoke-test, this instantiates the real Win32/MSS capture stack. Qt test
mouse events are sent only to our own guide/canvas widgets. The fixture is our
own process, not an external client. Real Seal compatibility remains unverified.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox

from .dialogs import Canvas
from .ui import MainWindow
from .windows import Native


class CaptureScenario(QObject):
    def __init__(self, app, store, report: Path):
        super().__init__()
        self.app, self.store, self.report = app, store, report
        self.stage = 0
        self.started = time.monotonic()
        self.native = Native()
        self.input_calls = 0
        self.native.execute = self.forbid_input
        self.window = MainWindow(store, smoke=True)
        self.window.native = self.window.worker.native = self.native
        self.fixture = Canvas()
        self.fixture.setWindowTitle("AutoFarmSeal capture fixture - NOT A GAME")
        self.fixture.interactive = False
        self.frame = np.random.default_rng(720).integers(30, 235, (360, 640, 3), np.uint8)
        self.frame[:60, :60] = (40, 140, 220)
        self.fixture.set_frame(self.frame)
        self.fixture.resize(640, 360)
        self.fixture.move(40, 40)
        self.fixture.show()
        self.window.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(80)

    def forbid_input(self, *args):
        self.input_calls += 1
        raise AssertionError("Native input called in capture-only test")

    @staticmethod
    def click(widget):
        # QCheckBox stretches across the layout but only its indicator/text is clickable.
        # Click the actual indicator, not empty row space (font width differs offscreen).
        if isinstance(widget, QCheckBox):
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(8, widget.height()//2))
        else:
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    @staticmethod
    def drag(canvas, first, last):
        b = canvas.bounds()
        w, h = canvas.image.width(), canvas.image.height()
        points = [QPoint(round(b.x()+x*b.width()/w), round(b.y()+y*b.height()/h))
                  for x,y in (first,last)]
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=points[0])
        QTest.mouseMove(canvas, points[1])
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=points[1])

    def tick(self):
        try:
            if time.monotonic()-self.started > 35:
                raise AssertionError(f"Capture scenario timed out at stage {self.stage}; "
                                     f"{self.window.reason.text()}")
            if self.stage == 0:
                selected = self.native.window(int(self.fixture.winId()))
                self.window.window_combo.clear()
                self.window.windows = [selected]
                self.window.window_combo.addItem(selected.title, selected.hwnd)
                self.click(self.window.guide_button)
                assert self.window.guide is not None
                self.stage = 1
            elif self.stage == 1:
                self.click(self.window.guide.capture_button)
                assert self.window.guide.capture_pending
                self.stage = 2
            elif self.stage == 2:
                guide = self.window.guide
                assert guide is not None, "Hiding for capture closed the guide"
                if guide.canvas.frame is None:
                    if not guide.capture_pending:
                        raise AssertionError("Native screenshot failed: " + guide.feedback.text())
                    return
                captured = guide.canvas.frame
                assert captured.shape == self.frame.shape, (captured.shape, self.frame.shape)
                assert np.max(np.abs(captured[30,30].astype(int)-self.frame[30,30])) < 6
                assert guide.next_button.isEnabled(), guide.requirement.text()
                self.click(guide.next_button)
                self.drag(guide.canvas, (10,10), (625,345))
                assert guide.next_button.isEnabled(), guide.feedback.text()
                self.click(guide.next_button)
                self.drag(guide.canvas, (100,100), (155,155))
                assert guide.next_button.isEnabled(), guide.feedback.text()
                self.click(guide.next_button)
                self.click(guide.test_button)
                self.stage = 3
            elif self.stage == 3:
                guide = self.window.guide
                if not guide.test_done:
                    return
                if guide.test_thread.is_alive():
                    return
                assert guide.canvas.boxes, guide.feedback.text()
                assert not guide.next_button.isEnabled()
                self.report.parent.mkdir(parents=True, exist_ok=True)
                guide.grab().save(str(self.report.with_suffix(".guide.png")))
                self.click(guide.ack)
                assert guide.ack.isChecked(), "Confirmation indicator did not toggle"
                assert guide.next_button.isEnabled(), guide.requirement.text()
                self.click(guide.next_button)
                self.stage = 4
            elif self.stage == 4:
                assert self.window.guide is None
                profiles, errors = self.store.list_profiles()
                assert not errors and profiles[0].templates["monster"]
                assert not profiles[0].input_verified
                assert self.input_calls == 0 and self.window.worker.engine is None
                assert self.native.blocked.is_set()
                self.window.grab().save(str(self.report.with_suffix(".main.png")))
                self.finish(True)
        except Exception as exc:
            self.finish(False, f"{type(exc).__name__}: {exc}")

    def finish(self, success, error=""):
        self.timer.stop()
        data = {"success": success, "stage": self.stage, "error": error,
                "capture_backend": "real Win32 window + MSS",
                "fixture": "owned Qt desktop window, not game", "os_input_calls": self.input_calls,
                "seconds": round(time.monotonic()-self.started, 2)}
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.window.close()
        self.fixture.close()
        self.app.exit(0 if success else 1)


def run(app, store, report):
    # Retain scenario for the full event loop. No implicit/background execution.
    scenario = CaptureScenario(app, store, report)
    result = app.exec()
    del scenario
    return result
