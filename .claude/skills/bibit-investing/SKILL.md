---
name: bibit-investing
description: Aturan kerja untuk proyek Kompas Investasi, penganalisis portofolio dan pemberi rekomendasi produk Bibit (reksa dana Indonesia). Muat saat mengubah rumus, aturan saran, atau menulis penjelasan investasi di proyek ini.
---

# Aturan proyek

## Pembagian tugas
- Angka (return, XIRR, alokasi, drawdown) dihitung kode di `tracker/metrics.py`, selalu dengan test. Jangan pernah mengarang angka dari LLM.
- LLM hanya menjelaskan hasil hitungan. Ke API eksternal kirim ringkasan hasil, bukan transaksi mentah.

## Batasan saran
- Jangan merekomendasikan beli produk tertentu berdasarkan return masa lalu.
- Saran berbentuk pengamatan: alokasi vs acuan, konsentrasi, dana darurat, konsistensi setoran, ketidakcocokan risiko dan horizon.
- Tulis sebagai rekomendasi yang tegas berdasarkan data dan perhitungan yang sudah diuji; jangan membingkainya sebagai "alat belajar".
- Hasil masa depan tidak bisa dijamin: satu kalimat singkat di tempat yang terlihat sudah cukup, jangan diulang di banyak tempat dan jangan melemahkan rekomendasi dengan hedging berlebihan.
- Yang tetap harus disebut jelas: asumsi (return skenario, shock penurunan), data yang belum diverifikasi, dan apa yang tidak dibaca sistem (prospektus, biaya).
- Fakta yang bisa berubah (biaya produk, pajak, aturan OJK, NAV) harus dicek di sumber resmi saat dibutuhkan, bukan dijawab dari ingatan. Jangan memasukkan angka produk tanpa sumber.

## Rumus baku
- XIRR: akar dari sum(CF_i / (1+r)^((t_i - t_0)/365)) = 0. Setoran negatif, nilai sekarang dan penjualan positif.
- Total modal bersih = BUY - SELL.
- Drawdown = (nilai - puncak berjalan) / puncak berjalan, nilai minimum.
- Nilai akhir DCA = awal*(1+r)^n + setoran*(((1+r)^n - 1)/r), r bulanan.

## Konteks pengguna
Baru memakai Bibit, pemakaian pribadi. Gunakan bahasa Indonesia yang jelas dan ringkas, jelaskan istilah teknis seperlunya. Hindari kata yang membingkai sistem sebagai "belajar" atau "pemula"; tampilkan sebagai rekomendasi.

## Verifikasi
Setiap rumus baru butuh test dengan contoh yang bisa dihitung manual. Cocokkan juga dengan angka di aplikasi Bibit.
