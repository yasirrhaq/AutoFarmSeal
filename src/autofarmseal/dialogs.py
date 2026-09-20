"""Compact settings and pixel-accurate screenshot calibration dialogs."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .model import Profile, Rect
from .storage import Store


def load_image(path: str) -> np.ndarray:
    from pathlib import Path
    p = Path(path)
    if p.stat().st_size > 40_000_000:
        raise ValueError("Gambar terlalu besar (maksimal 40 MB).")
    frame = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0 or frame.shape[1] > 7680 or frame.shape[0] > 4320:
        raise ValueError("Format/ukuran gambar tidak didukung.")
    return frame


class Canvas(QWidget):
    selected = Signal(object)
    sampled = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(540, 300)
        self.frame = None
        self.image = None
        self.boxes: list[tuple[Rect, str]] = []
        self.start: QPoint | None = None
        self.end: QPoint | None = None
        self.sample_mode = False
        self.interactive = True
        self.setMouseTracking(True)

    def set_frame(self, frame):
        self.frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                            QImage.Format.Format_RGB888).copy()
        self.update()

    def bounds(self) -> QRectF:
        if self.image is None:
            return QRectF()
        scale = min(self.width()/self.image.width(), self.height()/self.image.height())
        w, h = self.image.width()*scale, self.image.height()*scale
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def point(self, position, clamp=False) -> QPoint | None:
        b = self.bounds()
        if b.isEmpty() or not clamp and not b.contains(position):
            return None
        x = int((position.x()-b.x()) / b.width() * self.image.width())
        y = int((position.y()-b.y()) / b.height() * self.image.height())
        return QPoint(max(0, min(x, self.image.width()-1)),
                      max(0, min(y, self.image.height()-1)))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11151c"))
        if self.image is None:
            painter.setPen(QColor("#a7b0bf"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Belum ada gambar")
            return
        b = self.bounds()
        painter.drawImage(b, self.image)
        sx, sy = b.width()/self.image.width(), b.height()/self.image.height()
        painter.setPen(QPen(QColor("#59b6ee"), 1.5))
        boxes = list(self.boxes)
        if self.start is not None and self.end is not None:
            x, y = min(self.start.x(), self.end.x()), min(self.start.y(), self.end.y())
            boxes.append((Rect(x, y, abs(self.end.x()-self.start.x())+1,
                               abs(self.end.y()-self.start.y())+1), "seleksi"))
        for r, label in boxes:
            target = QRectF(b.x()+r.x*sx, b.y()+r.y*sy, r.w*sx, r.h*sy)
            painter.drawRect(target)
            painter.drawText(target.topLeft()+QPointF(2, 13), label)

    def mousePressEvent(self, event):
        if self.interactive and event.button() == Qt.MouseButton.LeftButton:
            self.start = self.point(event.position())
            self.end = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = self.point(event.position(), clamp=True)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is None or not self.interactive:
            return
        end = self.point(event.position(), clamp=True)
        start = self.start
        self.start = self.end = None
        if self.sample_mode:
            self.sampled.emit((start.x(), start.y()))
        elif end is not None:
            self.selected.emit(Rect(min(start.x(), end.x()), min(start.y(), end.y()),
                                    abs(end.x()-start.x())+1, abs(end.y()-start.y())+1))
        self.update()


class CalibrationDialog(QDialog):
    def __init__(self, profile: Profile, store: Store, frame=None, parent=None):
        super().__init__(parent)
        self.p, self.store = profile.clone(), store
        self.setWindowTitle("Kalibrasi dan template | AutoFarmSeal")
        self.resize(980, 780)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Tarik kotak pada gambar. Semua koordinat disimpan dalam piksel client asli."))
        row = QHBoxLayout()
        self.mode = QComboBox()
        for text, data in [
            ("Area dunia (boleh diklik)", "world"), ("Area terlarang (tambah)", "exclude"),
            ("Bar HP karakter", "hp"), ("Bar AP karakter", "ap"),
            ("Bar HP target (opsional)", "target_hp"),
            ("Template monster (tambah)", "template:monster"),
            ("Indikator pertarungan aktif", "template:combat"),
            ("Indikator kalah/selesai yang eksplisit", "template:defeat"),
            ("Ambil warna isi bar HP (klik)", "sample:hp"),
            ("Ambil warna isi bar AP (klik)", "sample:ap"),
            ("Ambil warna isi bar target (klik)", "sample:target"),
        ]:
            self.mode.addItem(text, data)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        row.addWidget(self.mode, 1)
        load = QPushButton("Buka screenshot...")
        load.clicked.connect(self.open_image)
        row.addWidget(load)
        clear = QPushButton("Hapus pengecualian")
        clear.clicked.connect(self.clear_exclusions)
        row.addWidget(clear)
        root.addLayout(row)
        self.canvas = Canvas()
        self.canvas.selected.connect(self.select)
        self.canvas.sampled.connect(self.sample)
        root.addWidget(self.canvas, 1)
        self.info = QLabel("Pilih area bar bagian dalam; hindari teks dan bingkai. Warna perlu dikalibrasi.")
        self.info.setWordWrap(True)
        root.addWidget(self.info)
        self.templates = QListWidget()
        self.templates.setMaximumHeight(105)
        root.addWidget(self.templates)
        buttons = QHBoxLayout()
        remove = QPushButton("Hapus template terpilih")
        remove.clicked.connect(self.remove_template)
        buttons.addWidget(remove)
        buttons.addStretch()
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        root.addLayout(buttons)
        self.refresh()
        if frame is not None:
            self.set_frame(frame)

    def _mode_changed(self):
        self.canvas.sample_mode = self.mode.currentData().startswith("sample:")

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih screenshot client game", "", "Gambar (*.png *.jpg *.jpeg *.bmp)")
        if path:
            try:
                self.set_frame(load_image(path))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Gambar tidak valid", str(exc))

    def set_frame(self, frame):
        w, h = frame.shape[1], frame.shape[0]
        if self.p.width and (w, h) != (self.p.width, self.p.height):
            result = QMessageBox.question(self, "Ukuran berubah",
                "Ukuran berbeda. Reset area dan referensi profil ini? Profil lain tidak diubah.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if result != QMessageBox.StandardButton.Yes:
                return
            self.p.regions.clear()
            self.p.exclusions.clear()
            self.p.templates = {"monster": [], "combat": [], "defeat": []}
            self.p.input_verified = False
        self.p.width, self.p.height = w, h
        self.canvas.set_frame(frame)
        self.refresh()

    def select(self, rect: Rect):
        if self.canvas.frame is None or min(rect.w, rect.h) < 2:
            return
        mode = self.mode.currentData()
        try:
            if mode.startswith("template:"):
                kind = mode.split(":")[1]
                limit = 12 if kind == "monster" else 3
                if len(self.p.templates[kind]) >= limit:
                    raise ValueError(f"Maksimal {limit} template {kind}.")
                path = self.store.image(rect.crop(self.canvas.frame))
                self.p.templates[kind].append(path)
                if kind != "monster":
                    self.p.regions[kind] = rect
                self.p.input_verified = False
            elif mode == "exclude":
                if len(self.p.exclusions) >= 20:
                    raise ValueError("Maksimal 20 area pengecualian.")
                self.p.exclusions.append(rect)
                self.p.input_verified = False
            elif not mode.startswith("sample:"):
                self.p.regions[mode] = rect
                self.p.input_verified = False
            self.info.setText(f"Tersimpan: {mode} | x={rect.x}, y={rect.y}, {rect.w} × {rect.h} px")
            self.refresh()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Seleksi gagal", str(exc))

    def sample(self, point):
        mode = self.mode.currentData()
        if not mode.startswith("sample:") or self.canvas.frame is None:
            return
        name = mode.split(":")[1]
        x, y = point
        h, s, v = (int(a) for a in cv2.cvtColor(self.canvas.frame[y:y+1, x:x+1], cv2.COLOR_BGR2HSV)[0, 0])
        if s < 40 or v < 40:
            QMessageBox.warning(self, "Warna tidak jelas", "Klik bagian berwarna dari isi bar, bukan teks/latar.")
            return
        setattr(self.p, f"{name}_lower", [(h-10) % 180, max(40, s-80), max(35, v-100)])
        setattr(self.p, f"{name}_upper", [(h+10) % 180, 255, 255])
        self.p.input_verified = False
        self.info.setText(f"Warna {name} diambil. Uji pembacaan pada beberapa tingkat isi bar sebelum mode input.")

    def clear_exclusions(self):
        self.p.exclusions.clear()
        self.p.input_verified = False
        self.refresh()

    def remove_template(self):
        item = self.templates.currentItem()
        if item:
            kind, path = item.data(Qt.ItemDataRole.UserRole)
            self.p.templates[kind].remove(path)
            self.p.input_verified = False
            self.refresh()

    def refresh(self):
        self.canvas.boxes = [(r, name) for name, r in self.p.regions.items()] + [
            (r, "jangan klik") for r in self.p.exclusions]
        self.canvas.update()
        self.templates.clear()
        for kind, paths in self.p.templates.items():
            for path in paths:
                self.templates.addItem(f"{kind}  |  {path}")
                self.templates.item(self.templates.count()-1).setData(Qt.ItemDataRole.UserRole, (kind, path))


class SettingsDialog(QDialog):
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.p = profile.clone()
        self.fields = {}
        self.setWindowTitle("Pengaturan profil | AutoFarmSeal")
        self.resize(620, 650)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        definitions = [
            ("Deteksi", [
                ("name", "Nama profil", "text"),
                ("threshold", "Skor template monster", (0.5, 0.999, 3)),
                ("signal_threshold", "Skor indikator pertarungan", (0.5, 0.999, 3)),
                ("scales", "Skala (pisahkan dengan koma)", "list_float"),
                ("click_x", "Titik klik X relatif", (0.05, 0.95, 2)),
                ("click_y", "Titik klik Y relatif", (0.05, 0.95, 2)),
                ("scan_hz", "Pemeriksaan per detik", (1, 12, 0)),
                ("max_search_width", "Lebar pencarian maksimum (px)", (320, 1280, 0)),
                ("max_frame_age", "Batas usia frame (detik)", (0.1, 1.0, 2)),
            ]),
            ("Input & warna bar", [
                ("ctrl_click", "Gunakan Ctrl + klik untuk serangan", "bool"),
                ("attack_key", "Tombol setelah klik (boleh kosong)", "text"),
                ("potion_cooldown", "Jeda potion minimum (detik)", (1, 60, 1)),
                ("potion_response_timeout", "Batas menunggu pemulihan (detik)", (1, 30, 1)),
                ("hp_lower", "HSV HP minimum", "list_int"),
                ("hp_upper", "HSV HP maksimum", "list_int"),
                ("ap_lower", "HSV AP minimum", "list_int"),
                ("ap_upper", "HSV AP maksimum", "list_int"),
                ("target_lower", "HSV target minimum", "list_int"),
                ("target_upper", "HSV target maksimum", "list_int"),
                ("input_verified", "Saya sudah menguji input, bar, dan indikator pada client ini", "bool"),
            ]),
            ("Batas & pengaman", [
                ("engage_timeout", "Menunggu serangan dimulai (detik)", (1, 20, 1)),
                ("combat_timeout", "Batas pertarungan (detik)", (5, 180, 1)),
                ("progress_timeout", "Tanpa kemajuan HP target (detik)", (2, 60, 1)),
                ("search_timeout", "Tanpa target ditemukan (detik)", (3, 120, 1)),
                ("max_attempts", "Maksimum kegagalan serangan", (1, 5, 0)),
                ("max_ineffective_potions", "Maksimum potion tidak efektif", (1, 5, 0)),
                ("loot_attempts", "Maksimum input pickup per encounter", (1, 5, 0)),
                ("session_minutes", "Batas sesi (menit)", (1, 120, 0)),
                ("screenshot_failures", "Simpan screenshot kegagalan lokal (maks. 10)", "bool"),
            ]),
        ]
        for title, rows in definitions:
            page = QWidget()
            form = QFormLayout(page)
            form.setVerticalSpacing(13)
            for name, label, kind in rows:
                value = getattr(self.p, name)
                if kind == "bool":
                    widget = QCheckBox(label)
                    widget.setChecked(value)
                    form.addRow(widget)
                elif isinstance(kind, tuple):
                    lo, hi, decimals = kind
                    widget = QDoubleSpinBox() if decimals else QSpinBox()
                    if decimals:
                        widget.setDecimals(decimals)
                        widget.setSingleStep(0.01 if hi <= 1 else 0.5)
                    widget.setRange(lo, hi)
                    widget.setValue(value)
                    form.addRow(label, widget)
                else:
                    widget = QLineEdit(", ".join(map(str, value)) if kind.startswith("list_") else value)
                    form.addRow(label, widget)
                self.fields[name] = (widget, kind)
            tabs.addTab(page, title)
        note = QLabel("F8 mulai/lanjut | F9 jeda | F10 berhenti. Jangan gunakan tombol ini sebagai binding game.\n"
                      "Indikator selesai harus bukti eksplisit, bukan gambar monster yang menghilang.")
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def save(self):
        try:
            candidate = self.p.clone()
            for name, (widget, kind) in self.fields.items():
                if kind == "bool":
                    value = widget.isChecked()
                elif isinstance(kind, tuple):
                    value = widget.value()
                elif kind.startswith("list_"):
                    cast = float if kind == "list_float" else int
                    value = [cast(x.strip()) for x in widget.text().split(",") if x.strip()]
                else:
                    value = widget.text().strip()
                    if name.endswith("_key"):
                        value = value.lower()
                setattr(candidate, name, value)
            errors = candidate.validate()
            if errors:
                raise ValueError("\n".join(errors))
            self.p = candidate
            self.accept()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Pengaturan tidak valid", str(exc))
