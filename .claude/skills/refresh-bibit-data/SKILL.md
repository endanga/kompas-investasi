---
name: refresh-bibit-data
description: Memperbarui snapshot produk Bibit (reksa dana, Obligasi FR, SBN) di data/ dan memeriksa hasilnya. Muat saat pengguna minta "perbarui/update data produk", data terasa usang (> 7 hari), atau rekomendasi lama perlu dibandingkan dengan produk terbaru.
---

# Perbarui data produk Bibit

## Siapa yang menjalankan
**Pengguna yang menjalankan pembaruan, bukan Claude.** Bibit memblokir browser tanpa tampilan, jadi pembaruan membuka
jendela Edge biasa selama sekitar 1 menit. Menjalankan itu dari sesi Claude ditolak oleh pemeriksa keamanan sebagai
penghindaran bot-check, dan pengguna memilih menjalankannya sendiri. Jangan mencoba menjalankannya, jangan mengubah
izin untuk melewatinya, dan jangan menyarankan trik penyamaran.

Dua cara bagi pengguna:
1. Tombol **"Perbarui data produk"** di sidebar dashboard (bagian "Data produk").
2. Terminal: `cd <folder proyek>` lalu `python -m tracker.refresh`
   (tambahkan `--dry-run` untuk hanya melihat perubahan tanpa menulis file).

Cukup seminggu sekali. Perbarui lebih sering menambah risiko Bibit membatasi akses.

## Yang dilakukan pembaruan
- Membaca tabel reksa dana (tradable, 100 baris per halaman), tabel Obligasi FR, SBN Ritel yang terbit, dan SBN berikutnya.
- Menulis `data/products.csv`, `obligasi_fr.csv`, `sbn_ritel.csv`, `sbn_berikutnya.json` (kolom `as_of` = tanggal).
- Memeriksa kelengkapan: kurang dari 50 reksa dana, atau kurang dari separuh snapshot lama, berarti halaman belum termuat
  sempurna dan **data lama dipertahankan**.
- Bila ada yang berubah, snapshot lama disalin ke `data/archive/<tanggal lama>_<jam>/` sebelum diganti.
- Tidak membongkar API Bibit (isinya diacak); hanya membaca yang tampil di halaman publik.

## Setelah pengguna menjalankannya, bantu periksa
1. Baca ringkasan yang ditampilkan: jumlah reksa dana (sekarang sekitar 147), produk baru, produk hilang, dataset berubah.
2. Jalankan `python -m pytest -q`. Test `test_recommend_real_data_smoke` dan `test_robo_level_4_5_matches_screenshot`
   harus tetap lolos; kalau gagal, data baru mengubah asumsi dan perlu dilihat.
3. Bandingkan dengan rekomendasi tersimpan (tab Rekomendasi > Riwayat rekomendasi): apakah produk utama berubah,
   apakah produk lama masih dijual.
4. Periksa produk robo Bibit di `tracker/products.py` (`ROBO_FUNDS`) masih ada di katalog; kalau hilang, beri tahu pengguna.
5. Laporkan temuan apa adanya, termasuk angka yang tampak janggal (drawdown, AUM berubah drastis).

## Bila gagal
- Pesan "bibit.id memblokir akses otomatis": tunggu, jangan diulang berkali-kali. Jangan menyamarkan browser atau user-agent.
- Pesan paket `playwright` belum terpasang: `python -m pip install playwright` (memakai Edge/Chrome yang sudah ada).
- Halaman berubah dan tabel tidak terbaca: perbaiki pembacaan di `tracker/refresh.py` (fungsi `parse_*` punya test),
  jangan menimpa data lama dengan data kosong.
- Alternatif resmi bila otomatis terus gagal: tombol "Download" di tabel produk bibit.id/reksadana, lalu buat impor dari file itu.
