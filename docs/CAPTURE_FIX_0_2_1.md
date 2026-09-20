# Perbaikan pengambilan gambar dan tombol (0.2.1)

Laporan pengguna: Ambil gambar tidak menghasilkan gambar; sejumlah tombol terlihat tidak bekerja; Lanjut/Simpan tetap terkunci. Ini laporan nyata, bukan bukti bahwa semua mesin punya penyebab yang sama.

## Perubahan

- Panduan memakai dialog asinkron dengan masa hidup eksplisit. Menyembunyikan panduan saat capture tidak dianggap selesai/batal.
- Pengambilan gambar memakai ID permintaan hingga ke hasil/error. Status jeda lama tidak membatalkan capture baru, gambar terlambat tidak masuk ke panduan lain.
- Satu permintaan capture saja; klik ganda dan membuka file saat capture ditolak sementara. Tersedia pembatalan dan retry.
- Pemilihan/ganti game tersedia di panduan. Tidak perlu menutup panduan hanya karena belum memilih window.
- Sesudah klik capture, aplikasi meminta Windows menampilkan game secara normal. Jika OS menolak, tunggu klik pengguna sampai 15 detik. Tidak ada input palsu atau pemaksaan fokus. Capture tetap butuh window terlihat dan aktif.
- Error asli (termasuk dependency, window, ukuran, backend) muncul di panduan dan log; tidak lagi selalu diganti instruksi empat detik.
- Capture/observasi dapat membaca monitor sekunder dalam virtual desktop. Pengaman input hidup tetap mewajibkan monitor utama.
- Kegagalan inisialisasi input tidak menghilangkan kemampuan mengambil screenshot.
- Penyebab Lanjut/Simpan belum aktif dan kotak konfirmasi selalu berada di footer, bukan tersembunyi di area yang harus digulir.
- Simpan contoh dulu menyimpan referensi belum teruji, tidak mengaktifkan atau menandai input terverifikasi.
- Perubahan ukuran screenshot meminta persetujuan reset draft; Batal mempertahankan profil asli di disk. Tidak ada penghapusan diam-diam.

## Pengujian

Tes UI mengklik tombol dan menyeret kanvas hingga penyimpanan, memakai worker serta capture palsu yang diketahui hasilnya. Pengujian tambahan Windows source dan EXE memakai adapter Win32 dan MSS yang sesungguhnya untuk mengambil gambar window Qt milik test sendiri, memeriksa piksel, masuk kembali ke panduan, memilih kotak, menjalankan deteksi, dan menyimpan. Pengiriman input OS dipasang perangkap gagal; tidak boleh dipanggil.

Ini lebih luas daripada startup/shutdown smoke test. Tetap bukan tes kompatibilitas Seal, driver GPU, mode fullscreen, atau pengaturan monitor pengguna. Batas deteksi monster dan persiapan farming tidak dilonggarkan.

## Mencoba perbaikannya

Ekstrak seluruh paket versi 0.2.1 ke folder baru; tutup EXE lama. Buka panduan, pilih/ganti game di dalam panduan, lalu Ambil gambar. Aplikasi mencoba menampilkan game; klik game bila belum aktif. Setelah gambar kembali, alasan berikutnya terlihat tepat di atas Lanjut. Bila ingin menyimpan contoh tanpa hasil deteksi yang bagus, gunakan Simpan contoh dulu, lalu tetap pada mode deteksi tanpa serangan.

Jika pengambilan gagal, kirim teks error yang sekarang terlihat di panduan. Tidak perlu mengirim seluruh profil, screenshot akun, atau folder data sebelum diminta.
