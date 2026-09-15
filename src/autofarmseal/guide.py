"""Input-free, transactional setup guides. Captures are requested from the owner.

No native input is available to this module. A detector test uses a bounded,
independent background task; finishing a guide never marks a client verified.
"""
from __future__ import annotations

import queue
import threading
import time
from uuid import uuid4

import cv2
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .dialogs import Canvas, load_image
from .model import Profile, Rect
from .vision import Detector, fill_ratio

GUIDES = {
    "monster": (
        ("source", "Ambil gambar game", "Buka game di lokasi farming. Ambil gambar saat monster terlihat. "
         "Ini hanya mengambil gambar, tidak mengeklik atau menyerang."),
        ("world", "Tandai tempat mencari monster", "Tekan dan tahan tombol kiri mouse, lalu tarik kotak "
         "di area tempat monster berada. Jangan masukkan chat, peta kecil, atau tombol game."),
        ("monster", "Tunjukkan satu monster", "Tarik kotak rapat mengelilingi SATU monster yang ingin dicari. "
         "Pilih yang terlihat jelas, jangan ikutkan monster lain. Ulangi tarikan untuk memperbaiki."),
        ("review", "Cek hasil sebelum menyimpan", "Tekan Coba cari monster. Kotak hasil seharusnya mengelilingi "
         "monster yang kamu maksud, bukan pohon atau batu. Tidak ada klik ke game."),
    ),
    "hp": (
        ("source", "Ambil gambar darah karakter", "Ambil gambar saat batang darah (HP) karakter terlihat jelas. "
         "Tidak harus penuh. Jangan ubah ukuran jendela game."),
        ("hp", "Tandai batang darah", "Tarik kotak sepanjang bagian DALAM batang HP, dari ujung kiri sampai "
         "ujung kanan, termasuk bagian kosong. Hindari angka, tulisan, dan bingkainya."),
        ("sample:hp", "Klik warna isi darah", "Klik satu titik pada isi batang HP yang berwarna. "
         "Aplikasi mengatur warna pembacaan untukmu; tidak perlu mengetik angka warna."),
        ("review", "Periksa pembacaan darah", "Bandingkan perkiraan di bawah dengan isi batang darah di gambar. "
         "Jika berbeda jauh, tekan Kembali dan perbaiki kotak atau warna."),
    ),
    "ap": (
        ("source", "Ambil gambar energi karakter", "Ambil gambar saat batang energi (AP) terlihat jelas. "
         "Jangan ubah ukuran jendela game."),
        ("ap", "Tandai batang energi", "Tarik kotak sepanjang bagian DALAM batang AP, termasuk bagian kosong. "
         "Hindari angka, tulisan, dan bingkainya."),
        ("sample:ap", "Klik warna isi energi", "Klik isi AP yang berwarna. Jangan klik tulisan atau bagian kosong."),
        ("review", "Periksa pembacaan energi", "Bandingkan perkiraan dengan gambar. Pembacaan tetap perlu diuji "
         "pada beberapa tingkat energi sebelum mengaktifkan potion."),
    ),
    "combat": (
        ("source", "Ambil gambar SAAT menyerang", "Mulai satu pertarungan secara manual, lalu ambil gambarnya. "
         "Cari tanda di antarmuka yang hanya muncul ketika pertarungan benar-benar berlangsung."),
        ("combat", "Tandai bukti pertarungan", "Kotaki tanda yang stabil dan berbeda dari saat tidak bertarung. "
         "Gambar monster saja bukan bukti serangan berhasil. Jika belum tahu tanda yang cocok, batalkan dulu."),
        ("review", "Simpan contoh saat menyerang", "Ini hanya contoh visual, belum pengesahan. Pastikan tanda ini "
         "tidak terbaca saat berjalan atau hanya memilih target. Jangan aktifkan farming sebelum diuji."),
    ),
    "defeat": (
        ("source", "Ambil gambar SETELAH monster kalah", "Selesaikan satu pertarungan manual dan ambil gambar "
         "tanda hasilnya. Gunakan bukti yang terkait pertarungan itu, bukan hanya monster menghilang."),
        ("defeat", "Tandai bukti monster kalah", "Kotaki tanda hasil yang jelas dan konsisten posisinya. Jangan "
         "kotaki tanah kosong, monster yang hilang, atau barang dari pertarungan lain. Belum tahu? Batalkan dulu."),
        ("review", "Simpan contoh hasil pertarungan", "Kalau game tidak menyediakan tanda yang bisa dibedakan "
         "secara andal, tetap gunakan uji deteksi. Jangan membuat contoh sembarang agar tombol Mulai terbuka."),
    ),
}


def hint_for(profile: Profile) -> str:
    if "world" not in profile.regions or not profile.templates["monster"]:
        return "Langkah pertama: tekan Mulai pengaturan mudah."
    return "Contoh monster tersimpan. Coba deteksi dulu; gambar yang cocok belum membuktikan farming siap."


class SetupGuide(QDialog):
    capture_requested = Signal()
    capture_cancelled = Signal()
    choose_window_requested = Signal()

    def __init__(self, profile, store, *, mode="monster", can_capture=False, parent=None):
        super().__init__(parent)
        self.p = profile.clone()
        self.store = store
        self.mode = mode
        self.steps = GUIDES[mode]
        self.index = 0
        self.pending = {}
        self.template_path = None
        self.chosen = None
        self.sampled_ok = False
        self.capture_pending = False
        self.can_capture = can_capture
        self.test_started = 0.0
        self.test_thread = None
        self.test_cancel = threading.Event()
        self.results = queue.Queue(maxsize=1)
        self.test_done = False
        self.testing = False
        self.closed = False
        self.saved = False
        self.setWindowTitle("Panduan mudah | AutoFarmSeal")
        self.resize(920, 700)
        if self.screen():
            area = self.screen().availableGeometry()
            self.resize(min(920, area.width()-40), min(700, area.height()-60))
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        root.addWidget(self.progress)
        self.heading = QLabel()
        self.heading.setObjectName("title")
        root.addWidget(self.heading)
        self.instruction = QLabel()
        self.instruction.setWordWrap(True)
        root.addWidget(self.instruction)
        self.name_row = QFormLayout()
        self.name = QLineEdit(self.p.name)
        self.name.setMaxLength(80)
        self.name.textChanged.connect(self.update_buttons)
        self.name_row.addRow("Nama monster", self.name)
        root.addLayout(self.name_row)
        self.source_row = QHBoxLayout()
        self.capture_button = QPushButton("Ambil gambar dari game")
        self.capture_button.setEnabled(True)
        self.capture_button.setToolTip("Pilih jendela game di menu utama terlebih dahulu.")
        self.capture_button.clicked.connect(self.request_capture)
        self.source_row.addWidget(self.capture_button)
        self.file_button = QPushButton("Pakai gambar yang sudah ada")
        self.file_button.clicked.connect(self.open_file)
        self.source_row.addWidget(self.file_button)
        root.addLayout(self.source_row)
        self.window_hint = QLabel("Game dipilih dari menu utama." if can_capture
                                  else "Belum ada game dipilih. Pilih game di sini atau buka screenshot.")
        self.window_hint.setWordWrap(True)
        root.addWidget(self.window_hint)
        self.choose_window_button = QPushButton("Pilih / ganti jendela game...")
        self.choose_window_button.clicked.connect(lambda _checked=False: self.choose_window_requested.emit())
        root.addWidget(self.choose_window_button)
        self.abort_capture_button = QPushButton("Batalkan pengambilan gambar")
        self.abort_capture_button.clicked.connect(lambda _checked=False: self.capture_cancelled.emit())
        outer.addWidget(self.abort_capture_button)
        self.canvas = Canvas()
        self.canvas.setMinimumSize(440, 240)
        self.canvas.selected.connect(self.select)
        self.canvas.sampled.connect(self.sample)
        root.addWidget(self.canvas, 1)
        self.feedback = QLabel("Belum ada gambar. Pilih salah satu tombol di atas.")
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        self.test_button = QPushButton("Coba cari monster (tanpa klik)")
        self.test_button.clicked.connect(self.run_test)
        root.addWidget(self.test_button)
        self.other_button = QPushButton("Coba pada gambar lain...")
        self.other_button.clicked.connect(lambda: self.open_file(test_only=True))
        root.addWidget(self.other_button)
        self.ack = QCheckBox("Hasil sudah saya periksa (belum mengizinkan serangan otomatis).")
        self.ack.toggled.connect(self.update_buttons)
        outer.addWidget(self.ack)
        self.requirement = QLabel()
        self.requirement.setWordWrap(True)
        self.requirement.setObjectName("status")
        outer.addWidget(self.requirement)
        self.draft_button = QPushButton("Simpan contoh dulu (belum teruji)")
        self.draft_button.clicked.connect(self.save_draft)
        outer.addWidget(self.draft_button)
        row = QHBoxLayout()
        self.cancel_button = QPushButton("Batal, tidak menyimpan")
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.cancel_button)
        row.addStretch()
        self.back_button = QPushButton("Kembali")
        self.back_button.clicked.connect(self.back)
        row.addWidget(self.back_button)
        self.next_button = QPushButton("Lanjut")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self.advance)
        row.addWidget(self.next_button)
        outer.addLayout(row)
        self.test_timer = QTimer(self)
        self.test_timer.timeout.connect(self.poll_test)
        self.finished.connect(self.cleanup)
        self.render()

    @property
    def step(self):
        return self.steps[self.index][0]

    def render(self):
        step, title, instruction = self.steps[self.index]
        self.progress.setText(f"Langkah {self.index + 1} dari {len(self.steps)}  |  Tidak ada input ke game")
        self.heading.setText(title)
        self.instruction.setText(instruction)
        self.name_row.labelForField(self.name).setVisible(step == "source" and self.mode == "monster")
        self.name.setVisible(step == "source" and self.mode == "monster")
        self.capture_button.setVisible(step == "source")
        self.file_button.setVisible(step == "source")
        self.window_hint.setVisible(step == "source")
        self.choose_window_button.setVisible(step == "source")
        self.draft_button.setVisible(step == "review" and self.mode == "monster")
        self.test_button.setVisible(step == "review" and self.mode == "monster")
        self.other_button.setVisible(step == "review" and self.mode == "monster")
        self.ack.setVisible(step == "review")
        self.canvas.sample_mode = step.startswith("sample:")
        self.canvas.interactive = step not in {"source", "review"}
        self.canvas.boxes = []
        if self.canvas.frame is not None:
            if step == "world" and "world" in self.p.regions:
                self.canvas.boxes = [(self.p.regions["world"], "Area pencarian")]
            elif step in {"hp", "ap", "sample:hp", "sample:ap"}:
                region = self.p.regions.get(self.mode)
                if region:
                    self.canvas.boxes = [(region, "Bagian dalam batang")]
            elif step in {"monster", "combat", "defeat"} and self.chosen:
                self.canvas.boxes = [(self.chosen, "Contoh yang dipilih")]
        if step == "review":
            self.feedback.setText(self.review_text())
        elif self.canvas.frame is not None:
            self.feedback.setText("Gambar siap. Ikuti petunjuk di atas; tarikan kotak dapat diulang.")
        self.canvas.update()
        self.update_buttons()

    def review_text(self):
        if self.mode in {"hp", "ap"} and self.canvas.frame is not None:
            value = fill_ratio(self.canvas.frame, self.p.regions.get(self.mode),
                               getattr(self.p, f"{self.mode}_lower"), getattr(self.p, f"{self.mode}_upper"))
            if value is None:
                return "Belum terbaca. Tekan Kembali untuk memperbaiki warna dan kotak. Jangan aktifkan potion dulu."
            return f"Perkiraan {self.mode.upper()}: {value:.0%}. Cocokkan dengan gambar; ini bukan data langsung dari game."
        if self.mode == "monster":
            return "Belum diuji. Tekan Coba cari monster. Setelah itu, coba juga gambar lain dengan ukuran sama."
        return "Contoh tersimpan setelah Selesai ditekan. Tetap perlu pemeriksaan pada keadaan yang TIDAK cocok."

    def step_ready(self):
        step = self.step
        if self.canvas.frame is None:
            return False
        if step == "source":
            return bool(self.name.text().strip())
        if step == "world":
            return "world" in self.p.regions
        if step in {"monster", "combat", "defeat"}:
            return self.template_path is not None
        if step in {"hp", "ap"}:
            return step in self.p.regions
        if step.startswith("sample:"):
            return self.sampled_ok
        if step == "review":
            return self.ack.isChecked() and (self.mode != "monster" or self.test_done)
        return False

    def request_capture(self, _checked=False):
        if not self.capture_pending and not self.testing and not self.closed:
            self.capture_requested.emit()

    def blocking_reason(self):
        if self.capture_pending:
            return "Sedang mengambil gambar. Tunggu hasil atau tekan Batalkan pengambilan gambar."
        if self.testing:
            return "Sedang menguji gambar; tombol akan aktif setelah hasil muncul."
        if self.canvas.frame is None:
            return "Agar Lanjut aktif: ambil gambar game atau pilih file screenshot dahulu."
        if self.step == "source" and not self.name.text().strip():
            return "Agar Lanjut aktif: isi nama monster di atas."
        if self.step == "world" and "world" not in self.p.regions:
            return "Agar Lanjut aktif: tekan-tahan mouse kiri, tarik kotak area dunia, lalu lepaskan."
        if self.step in {"monster", "combat", "defeat"} and self.template_path is None:
            return "Agar Lanjut aktif: tarik kotak mengelilingi contoh pada gambar. Klik biasa belum memilih kotak."
        if self.step in {"hp", "ap"} and self.step not in self.p.regions:
            return "Agar Lanjut aktif: tarik kotak sepanjang bagian dalam batang."
        if self.step.startswith("sample:") and not self.sampled_ok:
            return "Agar Lanjut aktif: klik satu titik isi batang yang berwarna, di dalam kotak."
        if self.step == "review":
            if self.mode == "monster" and not self.test_done:
                return "Jalankan Coba cari monster dahulu, atau Simpan contoh dulu untuk melanjutkan lain waktu."
            if not self.ack.isChecked():
                return "Periksa hasil, lalu centang Hasil sudah saya periksa tepat di atas tombol ini."
        return "Siap. Tekan Simpan dan selesai." if self.step == "review" else "Siap. Tekan Lanjut."

    def update_buttons(self, *_):
        busy = self.capture_pending or self.testing
        self.next_button.setText("Simpan dan selesai" if self.step == "review" else "Lanjut")
        self.next_button.setEnabled(self.step_ready() and not busy)
        self.back_button.setEnabled(self.index > 0 and not busy)
        self.test_button.setEnabled(not busy)
        self.other_button.setEnabled(not busy)
        self.capture_button.setEnabled(not busy)
        self.file_button.setEnabled(not busy)
        self.choose_window_button.setEnabled(not busy)
        self.abort_capture_button.setVisible(self.capture_pending)
        self.ack.setEnabled(not busy)
        self.canvas.interactive = not busy and self.step not in {"source", "review"}
        self.draft_button.setEnabled(not busy and self.template_path is not None)
        self.requirement.setText(self.blocking_reason())
        self.next_button.setToolTip(self.blocking_reason())

    def set_frame(self, frame, *, test_only=False):
        size = (frame.shape[1], frame.shape[0])
        if size[0] < 100 or size[1] < 100 or max(size) > 7680 or size[1] > 4320:
            raise ValueError("Pakai gambar jendela game yang lengkap, bukan potongan kecil.")
        if self.p.width and size != (self.p.width, self.p.height):
            raise ValueError(f"Ukuran gambar berbeda: {size[0]} x {size[1]}; profil memakai "
                             f"{self.p.width} x {self.p.height}. Gunakan gambar tanpa bingkai judul, "
                             "atau setujui pengaturan ulang ukuran. Profil tersimpan belum berubah.")
        if float(frame[::8, ::8].std()) < 2:
            raise ValueError("Gambar tampak kosong. Pastikan game terlihat, lalu ambil ulang.")
        self.p.width, self.p.height = size
        self.canvas.set_frame(frame.copy())
        self.test_done = False
        self.ack.setChecked(False)
        self.render()
        if test_only:
            self.run_test()

    def receive_frame(self, frame, *, test_only=False):
        """An explicit, transactional reset instead of trapping an old-size profile."""
        size = (frame.shape[1], frame.shape[0])
        if self.p.width and size != (self.p.width, self.p.height):
            answer = QMessageBox.question(self, "Ukuran gambar berubah",
                f"Gambar baru {size[0]} x {size[1]}, profil lama {self.p.width} x {self.p.height}. "
                "Atur ulang contoh dan area untuk ukuran baru? Profil di disk tidak berubah "
                "sampai disimpan; Batal tetap mempertahankan profil lama.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.feedback.setText("Gambar belum dipakai: ukuran berbeda. Ambil ukuran lama atau setujui atur ulang.")
                return False
            self.p.regions.clear()
            self.p.exclusions.clear()
            self.p.templates = {"monster": [], "combat": [], "defeat": []}
            self.p.width = self.p.height = 0
            self.p.input_verified = False
            self.pending.clear()
            self.template_path = self.chosen = None
            self.sampled_ok = False
            self.index = 0
            test_only = False
        self.set_frame(frame, test_only=test_only)
        return True

    def open_file(self, _checked=False, *, test_only=False):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih gambar game tanpa bingkai judul", "",
                                            "Gambar (*.png *.jpg *.jpeg *.bmp)")
        if path:
            try:
                self.receive_frame(load_image(path), test_only=test_only)
            except (ValueError, OSError) as exc:
                self.feedback.setText(str(exc))
                self.update_buttons()

    def select(self, rect: Rect):
        if self.canvas.frame is None or not rect.valid_in((self.p.width, self.p.height)):
            return
        if min(rect.w, rect.h) < 2:
            self.feedback.setText("Tekan, tahan, lalu tarik untuk membuat kotak; jangan hanya klik.")
            return
        step = self.step
        try:
            if step in {"world", "hp", "ap"}:
                if step == "world" and min(rect.w, rect.h) < 30:
                    raise ValueError("Area pencarian terlalu kecil. Kotaki sebagian dunia game, bukan satu titik.")
                if step == "world" and self.template_path:
                    self.p.templates["monster"].remove(self.template_path)
                    self.pending.pop(self.template_path, None)
                    self.template_path = self.chosen = None
                self.p.regions[step] = rect
                self.sampled_ok = False
                self.canvas.boxes = [(rect, "Area dipilih")]
            elif step in {"monster", "combat", "defeat"}:
                crop = rect.crop(self.canvas.frame).copy()
                if min(crop.shape[:2]) < 6 or cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).std() < 3:
                    raise ValueError("Contoh terlalu kecil atau polos. Kotaki objek/tanda yang terlihat jelas.")
                if step == "monster":
                    world = self.p.regions["world"]
                    if not (world.contains(rect.x, rect.y) and world.contains(rect.right-1, rect.bottom-1)):
                        raise ValueError("Pilih monster di dalam area pencarian, atau Kembali untuk memperluas area.")
                    if any(rect.intersects(r) for r in self.p.exclusions):
                        raise ValueError("Monster berada di area yang sebelumnya dilarang. Pilih contoh lain.")
                limit = 12 if step == "monster" else 3
                if step == "monster" and self.template_path is None and len(self.p.templates[step]) >= limit:
                    raise ValueError("Contoh profil sudah penuh. Hapus contoh lama melalui Pengaturan lanjutan.")
                if self.template_path is None:
                    self.template_path = f"templates/{uuid4().hex}.png"
                    # Fixed-position signals need a consistent search region.
                    if step != "monster":
                        self.p.templates[step] = []
                    self.p.templates[step].append(self.template_path)
                self.pending[self.template_path] = crop
                if step != "monster":
                    self.p.regions[step] = rect
                self.chosen = rect
                self.canvas.boxes = [(rect, "Contoh yang dipilih")]
            else:
                return
            self.p.input_verified = False
            self.test_done = False
            self.ack.setChecked(False)
            self.feedback.setText("Pilihan diterima. Tekan Lanjut, atau tarik ulang untuk memperbaiki.")
            self.canvas.update()
            self.update_buttons()
        except (ValueError, KeyError) as exc:
            self.feedback.setText(str(exc))

    def sample(self, point):
        if not self.step.startswith("sample:") or self.canvas.frame is None:
            return
        region = self.p.regions.get(self.mode)
        if region is None or not region.contains(*point):
            self.feedback.setText("Klik warna di DALAM kotak batang yang sudah kamu tandai.")
            return
        x, y = point
        h, s, v = map(int, cv2.cvtColor(self.canvas.frame[y:y+1, x:x+1], cv2.COLOR_BGR2HSV)[0, 0])
        if s < 40 or v < 40:
            self.feedback.setText("Warna belum jelas. Klik bagian isi yang berwarna, bukan angka atau latarnya.")
            return
        setattr(self.p, f"{self.mode}_lower", [(h-10) % 180, max(40, s-80), max(35, v-100)])
        setattr(self.p, f"{self.mode}_upper", [(h+10) % 180, 255, 255])
        self.p.input_verified = False
        self.sampled_ok = True
        self.feedback.setText("Warna berhasil diambil. Tekan Lanjut untuk melihat perkiraan isinya.")
        self.update_buttons()

    def back(self):
        if self.index:
            self.index -= 1
            self.render()

    def advance(self):
        if not self.step_ready() or self.capture_pending or self.testing:
            self.update_buttons()
            return
        if self.step == "review":
            self.accept()
        else:
            self.index += 1
            self.render()

    def run_test(self):
        if self.step != "review" or self.mode != "monster" or self.canvas.frame is None:
            return
        if self.test_thread and self.test_thread.is_alive():
            return
        self.test_done = False
        self.testing = True
        self.test_started = time.monotonic()
        self.ack.setChecked(False)
        profile, frame, pending = self.p.clone(), self.canvas.frame.copy(), dict(self.pending)
        self.feedback.setText("Sedang mencari pada gambar. Tidak ada input ke game...")
        self.test_cancel.clear()
        def work():
            try:
                def read(path):
                    return pending[path] if path in pending else self.store.read_image(path)
                detector = Detector(profile, read)
                result = detector.observe(frame, time.monotonic(), cancelled=self.test_cancel.is_set)
            except Exception as exc:
                result = str(exc)
            if not self.test_cancel.is_set():
                self.results.put_nowait(result)
        self.test_thread = threading.Thread(target=work, name="guide-image-test", daemon=True)
        self.test_thread.start()
        self.test_timer.start(100)
        self.update_buttons()

    def poll_test(self):
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            if self.testing and time.monotonic() - self.test_started > 15:
                self.test_cancel.set()
                self.testing = False
                self.test_timer.stop()
                self.feedback.setText("Pengujian terlalu lama. Kurangi area pencarian atau simpan contoh dulu. "
                                      "Tidak ada klik ke game.")
                self.update_buttons()
            return
        self.test_timer.stop()
        self.testing = False
        if self.closed:
            return
        if isinstance(result, str):
            self.feedback.setText("Gambar belum bisa diuji: " + result)
        else:
            self.test_done = True
            self.canvas.boxes = [(d.box, "Kandidat monster") for d in result.detections]
            self.canvas.update()
            count = len(result.detections)
            self.feedback.setText(
                f"Ditemukan {count} kandidat pada gambar ini. "
                + ("Periksa apakah kotaknya tepat. " if count else "Kembali dan pilih contoh yang lebih jelas. ")
                + "Hasil pada gambar contoh sendiri belum membuktikan akurasi; coba gambar lain juga.")
        self.update_buttons()

    def accept(self):
        if self.saved or self.step != "review" or not self.step_ready() or self.capture_pending:
            return
        if self.test_thread and self.test_thread.is_alive():
            return
        self.save_profile()

    def save_draft(self, _checked=False):
        if (self.mode != "monster" or self.step != "review" or not self.template_path
                or self.testing or self.capture_pending or self.saved):
            return
        # Saving reference data is not enabling or verifying game input.
        self.save_profile()

    def save_profile(self):
        candidate = self.p.clone()
        if self.mode == "monster":
            candidate.name = self.name.text().strip()
        candidate.input_verified = False
        created = []
        try:
            for temporary, image in self.pending.items():
                path = self.store.image(image)
                created.append(path)
                for kind in candidate.templates:
                    candidate.templates[kind] = [path if x == temporary else x for x in candidate.templates[kind]]
            self.store.save(candidate)
        except (ValueError, OSError) as exc:
            for path in created:
                self.store.asset(path).unlink(missing_ok=True)
            self.feedback.setText("Belum tersimpan: " + str(exc))
            return
        self.p = candidate
        self.saved = True
        super().accept()

    def cleanup(self, _result=0):
        self.closed = True
        self.testing = False
        self.test_cancel.set()
        self.test_timer.stop()


class FarmingPreparation(QDialog):
    """Actionable prerequisites; this dialog cannot grant permission or send input."""
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.task = None
        self.setWindowTitle("Persiapan farming | AutoFarmSeal")
        self.resize(650, 470)
        root = QVBoxLayout(self)
        label = QLabel("Siapkan satu per satu")
        label.setObjectName("title")
        root.addWidget(label)
        note = QLabel("Uji deteksi boleh dicoba lebih dulu. Untuk farming, aplikasi juga perlu tahu kondisi "
                      "darah dan tanda pertarungan. Tersimpan tidak sama dengan sudah teruji di game.")
        note.setWordWrap(True)
        root.addWidget(note)
        tasks = [
            ("monster", "Contoh monster dan area pencarian", bool(profile.templates["monster"] and "world" in profile.regions)),
            ("hp", "Posisi dan warna darah karakter", "hp" in profile.regions),
            ("combat", "Tanda saat pertarungan berlangsung", bool(profile.templates["combat"] and "combat" in profile.regions)),
            ("defeat", "Tanda monster sudah kalah", bool(profile.templates["defeat"] and "defeat" in profile.regions)),
            ("controls", "Tombol serangan, potion, dan pemeriksaan", profile.input_verified),
        ]
        if profile.ap_enabled:
            tasks.insert(2, ("ap", "Posisi dan warna energi karakter", "ap" in profile.regions))
        for task, text, present in tasks:
            row = QHBoxLayout()
            row.addWidget(QLabel(("Tersimpan  -  " if present else "Belum  -  ") + text), 1)
            button = QPushButton("Periksa" if present else "Atur langkah demi langkah")
            button.clicked.connect(lambda _checked=False, t=task: self.choose(t))
            row.addWidget(button)
            root.addLayout(row)
        help_text = QLabel("Belum tahu tanda saat menyerang/kalah? Jangan isi sembarang gambar. "
                           "Tetap di uji deteksi, lalu minta bantuan dengan rekaman singkat satu pertarungan.")
        help_text.setWordWrap(True)
        root.addWidget(help_text)
        close = QPushButton("Kembali ke menu utama")
        close.clicked.connect(self.reject)
        root.addWidget(close)

    def choose(self, task):
        self.task = task
        self.accept()


class SimpleControls(QDialog):
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.p = profile.clone()
        self.setWindowTitle("Tombol dan pemeriksaan | AutoFarmSeal")
        root = QVBoxLayout(self)
        note = QLabel("Potion dan tombol ambil barang diatur di menu utama. Isi di bawah sesuai yang "
                      "sudah kamu coba secara manual, bukan tebakan. F8, F9, F10 khusus kontrol bot.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.ctrl = QCheckBox("Memulai serangan dengan Ctrl + klik monster")
        self.ctrl.setChecked(profile.ctrl_click)
        root.addWidget(self.ctrl)
        form = QFormLayout()
        self.attack = QLineEdit(profile.attack_key)
        self.attack.setPlaceholderText("Kosongkan jika klik sudah cukup")
        form.addRow("Tombol tambahan setelah klik", self.attack)
        root.addLayout(form)
        self.verified = QCheckBox("Saya sudah menguji tombol, darah, tanda menyerang, dan tanda kalah di game ini.")
        # Never carry a previous verification into changed controls automatically.
        self.verified.setChecked(False)
        root.addWidget(self.verified)
        warn = QLabel("Kotak ini bukan hasil tes otomatis. Jangan centang sebelum pemeriksaan manual selesai. "
                      "Mode klik tetap perlu diizinkan terpisah di menu utama.")
        warn.setWordWrap(True)
        root.addWidget(warn)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        root.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Batal")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def save(self):
        candidate = self.p.clone()
        candidate.ctrl_click = self.ctrl.isChecked()
        candidate.attack_key = self.attack.text().strip().lower()
        candidate.input_verified = self.verified.isChecked()
        errors = candidate.validate()
        if errors:
            self.feedback.setText("\n".join(errors))
            return
        self.p = candidate
        self.accept()
