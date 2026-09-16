# Build EXE dengan klik dua kali

Di Windows, pasang **Python 3.12 x64** beserta **Python Launcher (`py`)** sekali
untuk build pertama. Pastikan source lengkap tersedia pada branch implementasi
`feat/windows-trainer-mvp` selama PR awal belum digabungkan. Tutup EXE lama.

**Klik dua kali `build.bat` di folder utama repo**, sejajar dengan `pyproject.toml`.
File ini otomatis memanggil `scripts/build.ps1`: membuat `.venv` bila diperlukan,
memasang dependency, menjalankan tes, lalu membangun aplikasi. Internet diperlukan
untuk dependency yang belum tersedia. Tidak perlu membuka terminal, aktivasi venv,
atau mengetik perintah build.

Saat berhasil, buka `dist/AutoFarmSeal/AutoFarmSeal.exe`. Untuk memindahkan aplikasi,
ZIP **seluruh** folder `dist/AutoFarmSeal`, termasuk `_internal`. Saat gagal, jendela
menampilkan error dan tetap terbuka. File build lama tidak dianggap hasil baru
ketika skrip gagal. Profil pengguna tidak dihapus dan branch tidak diubah otomatis.

`build.bat` hanya menggunakan kebijakan eksekusi pada proses PowerShell yang
menjalankan skrip, tanpa mengubah kebijakan permanen atau meminta administrator.
Pada komputer dengan kebijakan organisasi yang memblokir skrip, minta bantuan
administrator; jangan mengubah kebijakan organisasi.

Untuk CI/terminal tanpa berhenti menunggu tombol: `build.bat --no-pause`.
Pilihan itu hanya menghilangkan `pause`, bukan melewati tes atau pemeriksaan error.

