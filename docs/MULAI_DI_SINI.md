# Mulai memakai AutoFarmSeal 0.3.1

## Buka aplikasinya

Ekstrak SELURUH ZIP, lalu klik dua kali AutoFarmSeal.exe. Biarkan folder _internal di sampingnya. Tidak perlu Python atau mengetik perintah. Tutup aplikasi lama sebelum membuka versi baru. Profil lama tetap disimpan di folder data pengguna; tidak perlu dihapus.

## Pertama: ajari bentuk monster

Pilih game pada daftar di bagian atas, lalu tekan **1. Mulai pengaturan mudah**. Ada empat langkah dengan tombol Lanjut/Kembali:

1. **Ambil gambar game.** Aplikasi mengecil dan mencoba menampilkan game. Klik game bila belum aktif; aplikasi menunggu hingga 15 detik. Setelah mengambil gambar, panduan muncul kembali. Alternatifnya, gunakan screenshot yang sudah ada (tanpa bingkai judul atau desktop).
2. **Tandai tempat mencari monster.** Tekan dan tahan mouse kiri, lalu tarik kotak pada sebagian dunia game. Hindari chat, minimap, dan tombol.
3. **Tunjukkan satu monster.** Tarik kotak rapat pada satu monster di dalam area tadi. Tarik ulang jika salah.
4. **Cek hasil.** Tekan Coba cari monster. Kotak hasil harus mengelilingi monster, bukan batu atau pohon. Coba gambar lain juga, periksa hasil, lalu Simpan dan selesai.

Panduan ini tidak mengeklik game. Batal tidak mengganti profil atau menyimpan gambar percobaan. Ukuran berbeda meminta persetujuan untuk mengatur ulang draft. Profil lama di disk tetap utuh sampai Simpan ditekan.

## Belajar otomatis untuk monster bergerak

Setelah satu monster dikotaki dan sampai halaman review, tekan **Belajar otomatis 15 detik**. Aplikasi akan mengecil; pastikan game yang dipilih aktif lalu biarkan monster tetap terlihat dan bergerak normal. Tidak ada input game yang dikirim selama belajar.

Aplikasi mengikuti target dan memilih beberapa crop nyata yang cukup berbeda secara otomatis. Kamu tidak perlu mengambil depan/kiri/kanan/belakang satu per satu. Mirror kiri/kanan juga dicoba saat deteksi tanpa membuat file contoh tambahan. Jika target tertutup, keluar dari area pencarian, atau tracking berpindah/kehilangan target, proses berhenti dengan pesan dan contoh parsial tidak otomatis dianggap benar. Setelah belajar selesai, **uji deteksi pada gambar terbaru** sebelum menyiapkan farming.

## Kedua: cek pada gambar terbaru

Tekan **2. Coba deteksi (tidak menyerang)**. Saat aplikasi mengecil, klik game bila belum aktif; pengambilan menunggu hingga 15 detik. Hasil satu gambar akan muncul otomatis; tidak perlu mengejar jendela pratinjau di atas game. Angka/kotak yang cocok pada gambar contoh sendiri bukan jaminan pada pose atau jarak lain.

## Ketiga: persiapan farming

Tekan **3. Siapkan farming**. Pilih kebutuhan yang belum tersimpan. Ada panduan terpisah untuk posisi darah, mengambil warnanya dengan satu klik, tanda saat menyerang, dan tanda saat monster kalah. Tombol serangan diatur tanpa harus mengubah angka warna atau skor deteksi.

**Belum tahu tanda saat menyerang atau kalah? Berhenti di uji deteksi.** Jangan membuat kotak pada objek sembarang untuk melewati syarat. Rekaman singkat satu pertarungan (sebelum serangan sampai hasilnya terlihat) membantu pengembang memilih pemeriksaan yang sesuai client. Saat ini game masih harus menyediakan tanda yang dapat dibedakan secara andal.

Setelah pengaturan benar-benar diuji secara manual, buka **Tampilkan potion dan pengaturan lanjutan**, atur tombol potion/pickup yang memang digunakan, lalu izinkan klik otomatis dan konfirmasikan lingkungan yang memperbolehkannya. F8 memulai/melanjutkan, F9 menjeda, dan F10 menghentikan input bot. Auto-attack bawaan game mungkin tetap perlu dihentikan manual. Mulai dari satu pertarungan dengan pengawasan.

## Masalah yang umum

**Game tidak muncul:** buka game terlebih dahulu, jangan diminimalkan, lalu tekan Cari ulang. Mode input hanya Windows dan satu window terlihat pada monitor utama.

**Gambar belum diambil:** setelah menekan Ambil gambar, klik game bila belum aktif (ditunggu hingga 15 detik). Jangan klik aplikasi bot selama pengambilan.

**Monster tidak ditemukan/salah sasaran:** ulangi pengaturan mudah untuk contoh yang lebih jelas; pertahankan ukuran, zoom, dan kamera. Jangan langsung mengaktifkan serangan.

**Darah belum terbaca:** kotaki bagian dalam batang dari kiri sampai kanan termasuk bagian kosong, lalu klik isi yang berwarna. Hindari angka/tulisan/bingkai.

**Aplikasi dijeda saat pindah jendela:** ini pengaman. Pengujian gambar hanya sekali akan otomatis kembali. Sesi farming membutuhkan game tetap aktif dan dilanjutkan secara manual.

Build dan tes UI tidak membuktikan kompatibilitas game, hasil farming, atau pengaruh pada FPS. Tidak ada navigasi map, pemulihan setelah mati, atau farming minimisasi di versi ini.

## Tombol capture atau Lanjut belum bekerja?

Pilih/ganti game sekarang bisa dilakukan di panduan. Lihat alasan tepat di atas tombol Lanjut/Simpan; konfirmasi hasil tidak lagi tersembunyi di bawah scroll. Capture yang gagal menampilkan error aslinya dan dapat dicoba ulang. Simpan contoh dulu hanya menyimpan referensi belum teruji, bukan mengizinkan farming. Lihat `CAPTURE_FIX_0_2_1.md`.
