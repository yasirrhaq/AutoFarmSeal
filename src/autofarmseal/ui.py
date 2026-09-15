"""Trainer-style UI. No continuous animations and no CV work in Qt's UI thread."""
from __future__ import annotations

import sys
import time
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from . import __version__
from .dialogs import CalibrationDialog, Canvas, SettingsDialog, load_image
from .guide import FarmingPreparation, SetupGuide, SimpleControls, hint_for
from .model import Profile
from .runtime import RunSpec, Worker
from .storage import Store
from .windows import Hotkeys, Native

STYLE = """
QWidget { background:#181c24; color:#e0e5ed; font-family:'Segoe UI'; font-size:13px; }
QMainWindow, QDialog { background:#181c24; }
QScrollArea { border:0; }
QLabel#title { font-size:23px; font-weight:650; }
QLabel#muted { color:#98a5b8; }
QLabel#status { color:#7dc7f5; font-size:15px; font-weight:600; }
QPushButton { background:#292f3b; border:1px solid #3b4554; border-radius:4px;
              padding:7px 12px; min-height:20px; }
QPushButton:hover { background:#343f4f; }
QPushButton:pressed { background:#202833; }
QPushButton:disabled { color:#657081; border-color:#2c3340; background:#222732; }
QPushButton#primary { background:#275f87; border-color:#397da7; }
QPushButton#stop { background:#71313c; border-color:#974650; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QListWidget {
    background:#11151c; border:1px solid #394354; border-radius:3px; padding:5px;
    selection-background-color:#356789; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; }
QGroupBox { border:1px solid #343d4b; border-radius:5px; margin-top:10px; padding:16px 10px 10px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#aebcd0; }
QTabBar::tab { background:#252c37; padding:10px 14px; }
QTabBar::tab:selected { background:#354152; }
QToolTip { background:#293445; color:#e0e5ed; border:1px solid #52627a; }
"""


class Bridge(QObject):
    command = Signal(str, int)


class MainWindow(QMainWindow):
    def __init__(self, store: Store | None = None, *, smoke: bool = False):
        super().__init__()
        self.store = store or Store()
        self.smoke = smoke
        self.native = None
        self.guide = None
        self.capture_wait = None
        self.platform_error = ""
        if sys.platform == "win32" and not smoke:
            try:
                self.native = Native()
            except Exception as exc:
                self.platform_error = str(exc)
        self.worker = Worker(self.store, self.native)
        self.bridge = Bridge(self)
        self.bridge.command.connect(self.hotkey)
        self.hotkeys = None
        self.preview_dialog = None
        self.preview_canvas = None
        self.log_dialog = None
        self.last_image = None
        self.windows = []
        self._loading = False
        self.preview_boxes = []
        self.displayed_frame = None
        self.profiles, errors = self.store.list_profiles()
        if not self.profiles:
            if errors:
                self.worker.handler.close()
                raise ValueError("Profil rusak tidak ditimpa:\n" + "\n".join(errors))
            p = Profile()
            self.store.save(p)
            self.profiles = [p]
        self.setWindowTitle(f"AutoFarmSeal {__version__}")
        self.resize(790, 630)
        self.setMinimumWidth(730)
        self.setStyleSheet(STYLE)
        body = QWidget()
        self.body = body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setCentralWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel("AutoFarmSeal")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        version = QLabel(f"v{__version__}  |  Panduan mudah")
        version.setObjectName("muted")
        top.addWidget(version)
        root.addLayout(top)
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(390)
        row = QHBoxLayout()
        row.addWidget(QLabel("Game yang dibuka"))
        row.addWidget(self.window_combo, 1)
        refresh = QPushButton("Cari ulang")
        refresh.clicked.connect(self.refresh_windows)
        row.addWidget(refresh)
        root.addLayout(row)
        self.profile_combo = QComboBox()
        row = QHBoxLayout()
        row.addWidget(QLabel("Profil monster"))
        row.addWidget(self.profile_combo, 1)
        for label, callback in (("Baru", self.new_profile), ("Duplikat", self.duplicate_profile),
                                ("Hapus", self.delete_profile)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        root.addLayout(row)
        self.profile_combo.currentIndexChanged.connect(self.load_profile)
        welcome = QGroupBox("Mulai di sini")
        welcome_layout = QVBoxLayout(welcome)
        self.guide_hint = QLabel()
        self.guide_hint.setWordWrap(True)
        welcome_layout.addWidget(self.guide_hint)
        self.guide_button = QPushButton("1. Mulai pengaturan mudah")
        self.guide_button.setObjectName("primary")
        self.guide_button.clicked.connect(lambda: self.guided_setup())
        welcome_layout.addWidget(self.guide_button)
        step_buttons = QHBoxLayout()
        self.observe_button = QPushButton("2. Coba deteksi (tidak menyerang)")
        self.observe_button.clicked.connect(self.observe_once)
        step_buttons.addWidget(self.observe_button)
        self.prepare_button = QPushButton("3. Siapkan farming")
        self.prepare_button.clicked.connect(self.farming_setup)
        step_buttons.addWidget(self.prepare_button)
        welcome_layout.addLayout(step_buttons)
        safe_note = QLabel("Selesaikan satu langkah dulu. Tidak perlu mengisi angka warna, "
                           "koordinat, atau skor deteksi. Menguji gambar tidak menggerakkan karakter.")
        safe_note.setWordWrap(True)
        safe_note.setObjectName("muted")
        welcome_layout.addWidget(safe_note)
        root.addWidget(welcome)
        self.advanced_button = QPushButton("Tampilkan potion dan pengaturan lanjutan")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self.toggle_advanced)
        root.addWidget(self.advanced_button)
        self.advanced_panel = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.advanced_panel.hide()
        root.addWidget(self.advanced_panel)
        feature_box = QGroupBox("Potion dan tombol game")
        grid = QGridLayout(feature_box)
        grid.setVerticalSpacing(14)
        grid.addWidget(QLabel("Fitur"), 0, 0)
        grid.addWidget(QLabel("Gunakan saat di bawah"), 0, 1)
        grid.addWidget(QLabel("Tombol game"), 0, 2)
        grid.addWidget(QLabel("Serangan dasar"), 1, 0)
        grid.addWidget(QLabel("Target dari profil aktif"), 1, 1)
        options = QPushButton("Atur serangan...")
        options.clicked.connect(self.simple_controls)
        grid.addWidget(options, 1, 2)
        self.toggles, self.thresholds, self.keys = {}, {}, {}
        for row_index, (kind, label) in enumerate((("hp", "Potion darah (HP)"),
                                                  ("ap", "Potion energi (AP)"),
                                                  ("loot", "Ambil barang")), 2):
            toggle = QCheckBox(label)
            self.toggles[kind] = toggle
            grid.addWidget(toggle, row_index, 0)
            if kind != "loot":
                spin = QSpinBox()
                spin.setRange(5, 95)
                spin.setSuffix(" %")
                self.thresholds[kind] = spin
                grid.addWidget(spin, row_index, 1)
            else:
                grid.addWidget(QLabel("Isi tombol yang sudah dicoba"), row_index, 1)
            key = QLineEdit()
            key.setPlaceholderText("Contoh: 1 atau space")
            key.setMaximumWidth(180)
            self.keys[kind] = key
            grid.addWidget(key, row_index, 2)
        advanced_layout.addWidget(feature_box)
        setup = QHBoxLayout()
        for label, callback in (("Capture + Kalibrasi", self.capture),
                                ("Kalibrasi dari gambar", self.calibration),
                                ("Pengaturan", self.settings),
                                ("Pratinjau", self.preview)):
            b = QPushButton(label)
            b.clicked.connect(callback)
            setup.addWidget(b)
        advanced_layout.addLayout(setup)
        self.live = QCheckBox("Izinkan klik dan tombol otomatis (setelah persiapan teruji)")
        self.live.setEnabled(self.native is not None)
        advanced_layout.addWidget(self.live)
        self.permitted = QCheckBox("Saya menguji di lingkungan yang mengizinkan otomatisasi.")
        advanced_layout.addWidget(self.permitted)
        controls = QHBoxLayout()
        self.start_button = QPushButton("Mulai / Lanjut   F8")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_session)
        controls.addWidget(self.start_button, 2)
        pause = QPushButton("Jeda   F9")
        pause.clicked.connect(lambda: self.worker.command("pause"))
        controls.addWidget(pause, 1)
        stop = QPushButton("Berhenti   F10")
        stop.setObjectName("stop")
        stop.clicked.connect(lambda: self.worker.command("stop"))
        controls.addWidget(stop, 1)
        root.addLayout(controls)
        self.status = QLabel("Siap — mode observasi")
        self.status.setObjectName("status")
        root.addWidget(self.status)
        self.reason = QLabel("Mulai dari pengaturan mudah. Karakter belum digerakkan otomatis.")
        self.reason.setWordWrap(True)
        root.addWidget(self.reason)
        self.metrics = QLabel("HP —   AP —   Durasi 00:00   Konfirmasi 0   Hasil tidak diketahui 0")
        self.metrics.setObjectName("muted")
        root.addWidget(self.metrics)
        bottom = QHBoxLayout()
        self.last_log = QLabel("F10 menghentikan input; auto-attack bawaan game mungkin perlu dihentikan manual.")
        self.last_log.setWordWrap(True)
        self.last_log.setObjectName("muted")
        bottom.addWidget(self.last_log, 1)
        logs = QPushButton("Log")
        logs.clicked.connect(self.show_logs)
        bottom.addWidget(logs)
        data = QPushButton("Folder data")
        data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root))))
        bottom.addWidget(data)
        root.addLayout(bottom)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(1000)
        self.log_text.setParent(self)
        self.log_text.hide()
        self.refresh_profiles()
        self.refresh_windows()
        self.window_combo.currentIndexChanged.connect(lambda: self.worker.command("pause"))
        self.live.toggled.connect(lambda: self.worker.command("pause"))
        self.live.toggled.connect(self.refresh_guidance)
        self.permitted.toggled.connect(lambda: self.worker.command("pause"))
        for toggle in self.toggles.values():
            toggle.toggled.connect(self.controls_changed)
        for threshold in self.thresholds.values():
            threshold.valueChanged.connect(self.controls_changed)
        for key in self.keys.values():
            key.editingFinished.connect(self.controls_changed)
        self.hotkeys = Hotkeys(self.global_command) if not smoke else None
        self.worker.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)
        if errors:
            self.worker.event("Beberapa profil tidak dimuat: " + " | ".join(errors))
        if self.platform_error:
            self.reason.setText("Adapter Windows tidak tersedia: " + self.platform_error)
        elif self.native is None:
            self.reason.setText("Mode offline: kalibrasikan dan uji screenshot. Input game hanya tersedia di Windows.")

    def current(self) -> Profile:
        index = max(0, self.profile_combo.currentIndex())
        return self.profiles[index]

    def collect(self) -> Profile:
        p = self.current().clone()
        for kind in ("hp", "ap", "loot"):
            setattr(p, f"{kind}_enabled", self.toggles[kind].isChecked())
            key_name = "pickup_key" if kind == "loot" else f"{kind}_key"
            new_key = self.keys[kind].text().strip().lower()
            if new_key != getattr(p, key_name):
                p.input_verified = False
            setattr(p, key_name, new_key)
        for kind in ("hp", "ap"):
            setattr(p, f"{kind}_threshold", self.thresholds[kind].value()/100)
        self.store.save(p)
        self.profiles[max(0, self.profile_combo.currentIndex())] = p
        return p

    def spec(self, p: Profile, *, live=False, image=None) -> RunSpec:
        index = self.window_combo.currentIndex()
        window = self.windows[index] if 0 <= index < len(self.windows) else None
        return RunSpec(p, window, image, live, self.permitted.isChecked(),
                       bool(self.hotkeys and self.hotkeys.ready))

    def refresh_profiles(self, selected_id=None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(p.name, p.id)
        index = next((i for i, p in enumerate(self.profiles) if p.id == selected_id), 0)
        self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        self.load_profile()

    def load_profile(self):
        self.worker.command("pause")
        if not self.profiles:
            return
        p = self.current()
        self._loading = True
        for kind in ("hp", "ap", "loot"):
            self.toggles[kind].setChecked(getattr(p, f"{kind}_enabled"))
            self.keys[kind].setText(getattr(p, "pickup_key" if kind == "loot" else f"{kind}_key"))
        for kind in ("hp", "ap"):
            self.thresholds[kind].setValue(round(getattr(p, f"{kind}_threshold")*100))
        self.live.setChecked(False)
        self._loading = False
        self.refresh_guidance()

    def controls_changed(self, *_args):
        if not self._loading:
            self.worker.command("pause")
            try:
                self.collect()
            except (ValueError, OSError) as exc:
                self.reason.setText(str(exc))

    def refresh_windows(self):
        self.worker.command("pause")
        old = self.window_combo.currentData()
        self.window_combo.clear()
        try:
            available = self.native.list_windows() if self.native else []
        except Exception as exc:
            available = []
            self.reason.setText(str(exc))
        self.windows = [None, *available]
        self.window_combo.addItem("Pilih jendela game...", None)
        for w in available:
            self.window_combo.addItem(f"{w.title}  |  {w.rect.w} × {w.rect.h}", w.hwnd)
        previous = self.window_combo.findData(old) if old is not None else -1
        matches = [i for i, w in enumerate(self.windows) if w and "seal" in w.title.lower()]
        if previous >= 0:
            self.window_combo.setCurrentIndex(previous)
        elif len(matches) == 1:
            self.window_combo.setCurrentIndex(matches[0])
        self.refresh_guidance()

    def refresh_guidance(self, *_):
        if not hasattr(self, "guide_hint") or not self.profiles:
            return
        ready = not self.current().validate(calibrated=True)
        self.guide_hint.setText(hint_for(self.current()))
        self.observe_button.setEnabled(ready)
        self.prepare_button.setEnabled(ready)
        if hasattr(self, "start_button"):
            self.start_button.setText("Mulai farming   F8" if self.live.isChecked()
                                      else "Amati game (tanpa klik)   F8")

    def toggle_advanced(self, visible):
        self.advanced_panel.setVisible(visible)
        self.advanced_button.setText("Sembunyikan pengaturan lanjutan" if visible
                                    else "Tampilkan potion dan pengaturan lanjutan")
        QTimer.singleShot(0, self.fit_height)

    def fit_height(self):
        screen = self.screen()
        limit = screen.availableGeometry().height() - 60 if screen else 850
        self.resize(self.width(), min(max(580, self.body.sizeHint().height() + 25), max(400, limit)))

    def guided_setup(self, mode="monster"):
        self.worker.command("pause")
        self.live.setChecked(False)
        try:
            profile = self.collect()
            can_capture = self.native is not None and self.spec(profile).window is not None
            dialog = SetupGuide(profile, self.store, mode=mode, can_capture=can_capture, parent=self)
            self.guide = dialog
            dialog.capture_requested.connect(self.guide_capture)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                index = next(i for i, p in enumerate(self.profiles) if p.id == dialog.p.id)
                self.profiles[index] = dialog.p
                self.refresh_profiles(dialog.p.id)
        except (ValueError, OSError) as exc:
            self.error(exc)
        finally:
            self.worker.command("pause")
            self.capture_wait = None
            self.guide = None
            self.showNormal()
            self.refresh_guidance()

    def request_snapshot(self, purpose, profile):
        spec = self.spec(profile)
        if not self.native or not spec.window:
            raise ValueError("Pilih game pada daftar di atas dahulu. Untuk mencoba tanpa game, "
                             "gunakan tombol Pakai gambar yang sudah ada di panduan.")
        self.worker.command("snapshot", spec)
        self.capture_wait = (purpose, self.worker.epoch, time.monotonic())
        if purpose == "guide":
            self.guide.capture_pending = True
            self.guide.update_buttons()
            self.guide.showMinimized()
        self.showMinimized()

    def guide_capture(self):
        if self.guide:
            try:
                self.request_snapshot("guide", self.guide.p)
            except (ValueError, OSError) as exc:
                self.guide.feedback.setText(str(exc))

    def observe_once(self):
        self.worker.command("pause")
        self.live.setChecked(False)
        try:
            p = self.collect()
            if p.validate(calibrated=True):
                self.guided_setup()
                return
            if self.spec(p).window and self.native:
                self.reason.setText("Kembali ke game. Gambar diambil dalam 4 detik, lalu hasil otomatis dibuka.")
                self.request_snapshot("preview", p)
            else:
                from PySide6.QtWidgets import QFileDialog
                path, _ = QFileDialog.getOpenFileName(self, "Pilih gambar untuk uji tanpa klik", "",
                                                     "Gambar (*.png *.jpg *.jpeg)")
                if path:
                    self.test_snapshot(load_image(path))
        except (ValueError, OSError) as exc:
            self.error(exc)

    def test_snapshot(self, frame):
        # One saved-image observation: no native window, no engine, no input plan.
        self.open_preview()
        self.preview_canvas.boxes = []
        self.preview_canvas.set_frame(frame)
        self.worker.command("arm", RunSpec(self.collect(), image=frame, live=False))

    def simple_controls(self):
        self.worker.command("pause")
        try:
            self.save_dialog(SimpleControls(self.collect(), self))
        except (ValueError, OSError) as exc:
            self.error(exc)

    def farming_setup(self):
        self.worker.command("pause")
        self.live.setChecked(False)
        while not self.worker.closing.is_set():
            try:
                dialog = FarmingPreparation(self.collect(), self)
            except (ValueError, OSError) as exc:
                self.error(exc)
                return
            if dialog.exec() != QDialog.DialogCode.Accepted:
                break
            if dialog.task == "controls":
                self.advanced_button.setChecked(True)
                self.simple_controls()
            else:
                self.guided_setup(dialog.task)
        self.refresh_guidance()

    def new_profile(self):
        self.worker.command("pause")
        name, accepted = QInputDialog.getText(self, "Profil baru", "Nama monster:")
        if accepted and name.strip():
            try:
                p = Profile(name=name.strip())
                self.store.save(p)
                self.profiles.append(p)
                self.refresh_profiles(p.id)
            except ValueError as exc:
                self.error(exc)

    def duplicate_profile(self):
        self.worker.command("pause")
        try:
            p = self.collect()
            p.id = uuid4().hex
            p.name = p.name[:65] + " (salinan)"
            p.input_verified = False
            self.store.save(p)
            self.profiles.append(p)
            self.refresh_profiles(p.id)
        except (ValueError, OSError) as exc:
            self.error(exc)

    def delete_profile(self):
        self.worker.command("pause")
        if len(self.profiles) == 1:
            self.error("Buat profil pengganti sebelum menghapus profil terakhir.")
            return
        p = self.current()
        if QMessageBox.question(self, "Hapus profil", f"Hapus profil {p.name}?") == QMessageBox.StandardButton.Yes:
            try:
                self.store.delete(p)
                self.profiles.remove(p)
                self.refresh_profiles()
            except OSError as exc:
                self.error(exc)

    def save_dialog(self, dialog):
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.store.save(dialog.p)
                index = next(i for i, p in enumerate(self.profiles) if p.id == dialog.p.id)
                self.profiles[index] = dialog.p
                self.refresh_profiles(dialog.p.id)
            except (ValueError, OSError) as exc:
                self.error(exc)

    def settings(self):
        self.worker.command("pause")
        try:
            self.save_dialog(SettingsDialog(self.collect(), self))
        except (ValueError, OSError) as exc:
            self.error(exc)

    def calibration(self, _checked=False, frame=None):
        self.worker.command("pause")
        try:
            self.save_dialog(CalibrationDialog(self.collect(), self.store, frame, self))
        except (ValueError, OSError) as exc:
            self.error(exc)

    def capture(self):
        try:
            self.request_snapshot("calibration", self.collect())
        except (ValueError, OSError) as exc:
            self.error(exc)

    def start_session(self):
        try:
            p = self.collect()
            is_live = self.live.isChecked()
            errors = p.validate(calibrated=True, live=is_live)
            if errors:
                if p.validate(calibrated=True):
                    self.guided_setup()
                else:
                    self.farming_setup()
                return
            spec = self.spec(p, live=is_live)
            if not spec.window:
                if is_live:
                    raise ValueError("Mode input memerlukan window Windows.")
                from PySide6.QtWidgets import QFileDialog
                path, _ = QFileDialog.getOpenFileName(self, "Uji screenshot tanpa input", "", "Gambar (*.png *.jpg *.jpeg)")
                if not path:
                    return
                spec.image = load_image(path)
                self.open_preview()
            if is_live and (not spec.permitted or not spec.hotkeys_ready):
                raise ValueError("Konfirmasi izin lingkungan dan pastikan hotkey global aktif.")
            self.worker.command("arm", spec)
            if spec.window:
                self.showMinimized()
        except (ValueError, OSError) as exc:
            self.error(exc)

    def open_preview(self):
        if self.preview_dialog is None:
            self.preview_dialog = QDialog(self)
            self.preview_dialog.setWindowTitle("Pratinjau deteksi | bukan bukti keberhasilan farming")
            self.preview_dialog.resize(920, 590)
            layout = QVBoxLayout(self.preview_dialog)
            label = QLabel("Kotak biru = kemungkinan monster. Pastikan bukan pohon atau batu. "
                           "Ini hanya uji gambar, bukan bukti farming sudah siap. Jika hasil salah, "
                           "kembali ke Pengaturan mudah dan pilih contoh yang lebih jelas.")
            label.setWordWrap(True)
            layout.addWidget(label)
            self.preview_canvas = Canvas()
            self.preview_canvas.interactive = False
            layout.addWidget(self.preview_canvas, 1)
            self.preview_dialog.finished.connect(lambda _result: setattr(self.worker, "preview_visible", False))
        self.worker.preview_visible = True
        self.preview_dialog.show()
        if self.last_image is not None:
            self.preview_canvas.boxes = self.preview_boxes
            self.preview_canvas.set_frame(self.last_image)

    def preview(self):
        self.open_preview()

    def show_logs(self):
        if self.log_dialog is None:
            self.log_dialog = QDialog(self)
            self.log_dialog.setWindowTitle("Log lokal | AutoFarmSeal")
            self.log_dialog.resize(820, 450)
            layout = QVBoxLayout(self.log_dialog)
            layout.addWidget(self.log_text)
            self.log_text.show()
        self.log_dialog.show()

    def global_command(self, kind):
        if kind in {"pause", "stop"}:
            self.worker.command(kind)
        # The listener can enqueue F8 while Qt is busy. A later F10 changes this
        # epoch immediately; the stale Qt callback must not create a new Start.
        self.bridge.command.emit(kind, self.worker.epoch)

    @Slot(str, int)
    def hotkey(self, kind, epoch):
        if (kind == "arm" and epoch == self.worker.epoch
                and not self.worker.closing.is_set()
                and self.guide is None
                and QApplication.activeModalWidget() is None):
            self.start_session()

    def poll(self):
        snap, entries = self.worker.read()
        self.status.setText(snap.get("state", "Siap"))
        self.reason.setText(snap.get("reason", ""))
        obs = snap.get("obs")
        hp = f"{obs.hp:.0%}" if obs and obs.hp is not None else "—"
        ap = f"{obs.ap:.0%}" if obs and obs.ap is not None else "—"
        seconds = snap.get("seconds", 0)
        timing = f"  |  Deteksi {obs.elapsed_ms:.0f} ms" if obs else ""
        self.metrics.setText(f"HP {hp}   AP {ap}   {seconds//60:02}:{seconds%60:02}   "
                             f"Konfirmasi {snap.get('confirmed', 0)}   Tidak diketahui {snap.get('unknown', 0)}{timing}")
        for entry in entries:
            self.log_text.appendPlainText(entry)
        if entries:
            self.last_log.setText(entries[-1][:180])
        frame = snap.get("image")
        if frame is not None:
            self.last_image = frame
            self.preview_boxes = [(d.box, f"{d.score:.2f}") for d in obs.detections] if obs else []
            if (self.preview_dialog and self.preview_dialog.isVisible()
                    and obs and self.displayed_frame != obs.captured_at):
                self.displayed_frame = obs.captured_at
                self.preview_canvas.boxes = self.preview_boxes
                self.preview_canvas.set_frame(frame)
        captured = snap.get("captured")
        if self.capture_wait is not None:
            purpose, epoch, requested = self.capture_wait
            cancelled = epoch != self.worker.epoch or time.monotonic() - requested > 12
            failed = time.monotonic() - requested > 0.5 and snap.get("state") in {"Dijeda", "Berhenti"}
            if captured is not None or cancelled or failed:
                self.capture_wait = None
                self.showNormal()
                self.activateWindow()
                if purpose == "guide" and self.guide:
                    self.guide.capture_pending = False
                    self.guide.showNormal()
                    self.guide.activateWindow()
                    if captured is not None and not cancelled:
                        try:
                            self.guide.set_frame(captured)
                        except ValueError as exc:
                            self.guide.feedback.setText(str(exc))
                    else:
                        self.worker.command("pause")
                        self.guide.feedback.setText("Gambar belum diambil. Aktifkan game dalam 4 detik "
                                                    "setelah menekan Ambil gambar, lalu coba lagi.")
                    self.guide.update_buttons()
                elif captured is not None and not cancelled:
                    if purpose == "preview":
                        self.test_snapshot(captured)
                    else:
                        self.calibration(frame=captured)
                else:
                    self.worker.command("pause")
                    self.reason.setText("Gambar belum diambil. Pastikan game aktif, lalu coba lagi.")
        if self.live.isChecked() and self.worker.running and not (self.hotkeys and self.hotkeys.ready):
            self.worker.command("stop")
            self.reason.setText("Hotkey darurat tidak aktif; input dihentikan.")

    def error(self, exc):
        self.worker.command("pause")
        QMessageBox.warning(self, "Perlu diperiksa", str(exc))

    def closeEvent(self, event):
        if self.guide is not None:
            self.guide.reject()
        self.worker.close()
        if self.hotkeys:
            self.hotkeys.close()
        self.worker.join(timeout=1)
        if self.worker.is_alive():
            event.ignore()
            QTimer.singleShot(200, self.close)
            return
        self.timer.stop()
        event.accept()
