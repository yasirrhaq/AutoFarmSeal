# AutoFarmSeal

**v0.3.0 — belajar monster otomatis multi-pose.** Aplikasi desktop Windows untuk prototipe penelitian computer vision, Python + PySide6. Bukan bot Seal yang sudah terverifikasi untuk ditinggal tanpa pengawasan.

## Mulai tanpa mengedit kode

Ekstrak seluruh ZIP, lalu buka `AutoFarmSeal.exe`. Jangan memindahkan `.exe` sendirian: folder `_internal` harus tetap di sampingnya. Tidak perlu memasang Python untuk paket Windows.

1. Tekan **1. Mulai pengaturan mudah**. Pilih game melalui **Pilih / ganti jendela game...** bila belum dipilih. Tekan **Ambil gambar dari game**; aplikasi mencoba menampilkan game, atau menunggu kamu mengaktifkannya hingga 15 detik. Ikuti empat langkah: ambil gambar, kotaki area pencarian, kotaki satu monster, lalu coba hasilnya. Tidak perlu mengisi koordinat, angka warna HSV atau skor deteksi.
2. Tekan **2. Coba deteksi (tidak menyerang)** untuk melihat hasil pada satu gambar terbaru. Saat aplikasi mengecil, aktifkan game bila belum di depan; hasil otomatis muncul kembali. Mode ini tidak mengirim input game.
3. **3. Siapkan farming** menunjukkan kebutuhan berikutnya satu per satu. Ada panduan posisi/warna darah, tanda saat menyerang dan tanda saat monster kalah. Tombol potion dan opsi teknis ada di **Tampilkan potion dan pengaturan lanjutan**.

Alasan **Lanjut/Simpan** belum aktif selalu terlihat di footer. **Simpan contoh dulu (belum teruji)** menyimpan referensi tanpa harus mengesahkan hasil deteksi atau mengaktifkan input. Kegagalan capture menampilkan error asli dan dapat dicoba ulang. Ukuran gambar baru meminta persetujuan reset draft, bukan menghapus profil di disk diam-diam.

Selesai mengikuti panduan tidak otomatis mengizinkan klik atau membuktikan akurasi. Jangan membuat tanda pertarungan sembarang untuk melewati syarat. Bila belum tahu indikator yang cocok, tetap gunakan uji deteksi dan minta bantuan dengan rekaman satu pertarungan.

**[Panduan lengkap bahasa Indonesia](docs/MULAI_DI_SINI.md)**. Profil v0.1/v0.2 tetap terbaca; jangan menghapus folder data saat memperbarui aplikasi.

## Belajar monster otomatis

Untuk monster yang berubah arah/pose, tandai satu monster sekali pada panduan lalu tekan **Belajar otomatis 15 detik**. Selama proses ini aplikasi hanya membaca layar: optical-flow tracking mengikuti target, pencarian visual mencoba memperoleh kembali target bila tracking melemah, dan hanya crop nyata yang cukup berbeda yang ditambahkan sebagai contoh. Runtime juga dapat mencoba mirror kiri/kanan tanpa menyimpan file duplikat.

Learning mode tidak mengirim klik/tombol game dan tidak menandai input sebagai terverifikasi. Pertahankan ukuran window, biarkan target tetap terlihat, dan uji hasilnya pada frame baru. Occlusion, target yang sangat mirip, perubahan kamera ekstrem, atau perpindahan ke objek lain masih dapat menggagalkan tracking; bila itu terjadi, ulangi belajar atau tambahkan contoh manual. Ini belum SAM/YOLO/semantic recognition.

## What is implemented

Compact trainer UI, beginner setup and separate advanced editor; local profile CRUD; screenshot region selection and PNG templates; multi-scale OpenCV matching; calibrated HP/AP estimates; explicit input-free observation; guarded select/engage/combat/loot state machine; potion rules; bounded pickup requests; F8 start/resume, F9 pause, F10 stop; fresh-frame/window/foreground/identity/geometry guards; rotating logs; optional capped failure screenshots.

**Client capture/input, monster recognition, HP/AP readings, valid engagement/completion signals, actual pickup binding and game FPS impact still need supervised testing.** No pretrained model, client-calibrated profile or user gameplay screenshot is bundled. Template appearance can fail with changing camera, scale, pose, occlusion or similar monsters.

Default is observation without clicks. Live input requires verified bindings/calibration, explicit opt-in, an environment permitting automation, working hotkeys and a visible game wholly on the primary monitor. Screenshot-only capture can also use secondary monitors inside the Windows virtual desktop. No background/minimized gameplay or multi-client operation. A missing monster is not proof of defeat; a pickup key is not proof an item was acquired.

**Stop inhibits this application's future inputs and releases held inputs. It cannot guarantee cancellation of game-native auto-attack already activated.** Cancel that in the game manually as necessary. Do not use the keyboard/mouse for unrelated activities during a live session.

The program observes screen pixels and sends ordinary bounded mouse/keyboard actions. No memory access, DLL injection, packet manipulation, D3D hook, protection bypass or stat cheats. Use only an offline or explicitly permitted environment. Do not disable antivirus/client protection or grant administrator privileges merely to make input work.

## Develop from source

Python 3.12 x64, Windows. While the initial PR remains open:

```powershell
git clone --branch feat/windows-trainer-mvp https://github.com/yasirrhaq/AutoFarmSeal.git
cd AutoFarmSeal
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m autofarmseal
```

`scripts/run.ps1` is an alternative after reviewing it and allowing local scripts. Linux/macOS can use the offline screenshot interface and core tests, not live Windows adapters.

## Build and test

Run `scripts/build.ps1` on Windows, or:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AutoFarmSeal.spec
```

Output: `dist/AutoFarmSeal/AutoFarmSeal.exe`; distribute the entire folder. Profiles/templates/logs are in `%LOCALAPPDATA%/AutoFarmSeal`, not the application folder. There is no installer, signing certificate, updater or cloud account.

```powershell
python -m autofarmseal --self-check
python -m autofarmseal --smoke-test --data-dir .smoke-data --screenshot ui-smoke.png
python -m autofarmseal --smoke-test --guide-smoke --data-dir .guide-smoke --screenshot guide-ui.png
python -m autofarmseal --data-dir .capture-test --capture-self-test capture-report.json
```

`--self-check` only reads profiles. Smoke tests create no native adapters or hotkeys. `--data-dir` or `AUTOFARMSEAL_DATA_DIR` selects independent development data. Headless Qt tests use `QT_QPA_PLATFORM=offscreen`; native Windows tests use `windows`.

The last command is an explicit Windows-only integration test: it uses real Win32/MSS capture of an owned desktop fixture and Qt widget clicks to exercise the complete guide through saving. It does not target a game and traps any attempt to dispatch OS input. Source and packaged versions are tested in CI. This is stronger than startup/shutdown, but not a Seal-client compatibility test.

CI runs tests, native UI checks and fixture capture, builds a Windows one-folder package, checks the EXE, and uploads it with a dependency manifest. A matching source snapshot is retained. Inspect the actual run result before claiming a successful build. Fixture/widget tests are not game acceptance.

## Documents

- [Beginner instructions](docs/MULAI_DI_SINI.md)
- [Capture and button repair](docs/CAPTURE_FIX_0_2_1.md)
- [Usability changes and safeguards in 0.2](docs/USABILITY.md)
- [Product baseline and acceptance criteria](PRD.md)
- [Architecture baseline](TRD.md)
- [Real-client testing checklist](docs/TESTING.md)
- [Third-party notices](docs/THIRD_PARTY_NOTICES.md)

Still out of scope: whole-map navigation, town visits, potion purchasing, inventory selling, death recovery, adaptive combos, selective loot, OCR/YOLO/Roboflow, D3D overlay, background/minimized operation and multiple clients. No unmeasured FPS, accuracy or unattended-farming promises.
