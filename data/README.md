# Format data

**products.csv** — snapshot 147 reksa dana yang dijual di Bibit, diambil dari halaman publik bibit.id/reksadana
(kolom `as_of` = tanggal pengambilan). Return = persen; `drawdown_1y_pct` = penurunan terdalam 1 tahun terakhir;
`aum_idr` = dana kelolaan dalam rupiah. Ini data masa lalu dan cepat usang, jadi perbarui berkala dan selalu cek
halaman produk di Bibit sebelum membeli. Kategori `global` (reksa dana global) belum dipakai di aturan alokasi.

Isi dua file ini sendiri dari aplikasi Bibit (kolom `product` diisi nama produk persis seperti di Bibit).

**sbn_ritel.csv, obligasi_fr.csv, instrumen_sbn_fr.csv** — snapshot dari bibit.id/sbn dan bibit.id/obligasifr
(`as_of` = tanggal pengambilan). Harga dan yield Obligasi FR berubah tiap hari. Saham individu tidak punya
katalog publik di Bibit sehingga tidak dicatat.

**recommendations/** — satu file JSON per rekomendasi yang Anda simpan lewat tombol "Simpan rekomendasi hari ini"
(profil risiko, pembagian dana, produk pilihan beserta angkanya, dan tanggal data). Dipakai untuk membandingkan
dengan rekomendasi sekarang bila data produk berubah. **archive/** menyimpan snapshot data produk yang lama.

**transactions.csv** — satu baris per transaksi
- `date`: `YYYY-MM-DD`
- `category`: salah satu dari `pasar_uang`, `pendapatan_tetap`, `campuran`, `saham`, `sbn`
- `type`: `BUY` atau `SELL`
- `amount`: nominal rupiah, angka saja (tanpa titik/koma), selalu positif

**holdings.csv** — nilai saat ini per produk (lihat halaman portofolio)
- `current_value`: nilai sekarang dalam rupiah

Contoh baris (jangan dianggap data nyata):

```
2026-09-05,Contoh Reksa Dana Pasar Uang,pasar_uang,BUY,500000
```

**Rekomendasi dan portofolio** — bila `holdings.csv` berisi, rekomendasi memakainya: setoran bulanan diarahkan ke jenis yang
di bawah target profil risiko (tanpa menjual apa pun), perkiraan turun dihitung untuk total portofolio setelah setoran, dan
produk yang sudah dimiliki ditandai. Kolom `product` harus sama persis dengan nama produk di Bibit agar dikenali.

**robo_picks.json** — produk yang direkomendasikan robo Bibit per profil risiko, diisi sendiri lewat tombol "Isi rekomendasi robo" (otomatis muncul setelah data produk diperbarui). Satu entri per pengisian, lengkap dengan tanggal; entri terbaru dipakai untuk perbandingan pilihan sistem vs robo.
