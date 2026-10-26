# Deploy Kompas Investasi

Hasil akhirnya: aplikasi bisa dibuka dari browser (komputer atau ponsel) di alamat Streamlit Cloud, data pribadi Anda
(portofolio, transaksi, rekomendasi tersimpan, pilihan robo) tersimpan di database PostgreSQL, dan hanya email Anda yang
bisa membukanya.

Pembagian tugas:

| Data | Di mana | Cara berubah |
|---|---|---|
| Katalog produk (`data/products.csv`, `obligasi_fr.csv`, `sbn_ritel.csv`, dst.) | Repo GitHub | Jalankan refresh di komputer, lalu commit dan push |
| Data pribadi (portofolio, transaksi, rekomendasi tersimpan, robo) | Database | Lewat aplikasi (form, unggah CSV, edit tabel) |
| Rahasia (URL database, kata sandi) | Streamlit Secrets | Tidak pernah masuk repo |

Nama menu di Supabase, GitHub, dan Streamlit Cloud bisa sedikit berubah dari waktu ke waktu; ikuti istilahnya, bukan urutan kliknya.

## 1. Cek lokal dulu

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m streamlit run app.py
```

## 2. Buat database (Supabase, gratis)

1. Daftar di supabase.com, buat **New project**. Pilih region terdekat (Singapore) dan catat **Database Password**.
2. Buka **Project Settings > Database > Connection string**, pilih **Transaction pooler** (port 6543), salin string-nya.
   Ganti `[YOUR-PASSWORD]` dengan sandi database.
3. Tidak perlu membuat tabel. Aplikasi membuatnya sendiri saat pertama jalan, dan otomatis mengaktifkan Row Level Security
   tanpa policy, sehingga API publik Supabase tidak bisa membaca tabel Anda. Hanya koneksi dengan sandi database yang bisa.

Neon (neon.tech) juga bisa; pakai connection string-nya dengan cara yang sama.

## 3. Pindahkan data lokal ke database

Salin `.streamlit/secrets.toml.example` menjadi `.streamlit/secrets.toml`, isi bagian `[database] url`. File itu sudah ada di
`.gitignore`. Lalu:

```
python -m tracker.migrate --dry-run     # lihat jumlah data yang akan disalin
python -m tracker.migrate               # salin
python -m streamlit run app.py          # sidebar harus menulis "Database PostgreSQL"
```

Migrasi aman diulang: rekomendasi tersimpan diganti berdasarkan nama, entri robo tidak dobel. Portofolio yang sudah ada di
database tidak ditimpa kecuali dengan `--force`.

## 4. Repo GitHub privat

Repo git lokal sudah dibuat dan berisi satu commit awal. Buat repo **Private** kosong di GitHub, lalu:

```
git remote add origin https://github.com/<akun-anda>/<nama-repo>.git
git push -u origin main
```

Pastikan tidak ada data pribadi ikut: `git ls-files data` hanya boleh menampilkan CSV produk, `risk_profiles.json`,
`sbn_berikutnya.json`, dan `README.md`.

## 5. Streamlit Community Cloud

1. Masuk ke share.streamlit.io dengan akun GitHub, **Create app**, pilih repo privat tadi, branch `main`, file `app.py`.
2. Di **Advanced settings**: pilih Python 3.12 atau 3.13, dan tempel isi `secrets.toml` Anda ke kotak **Secrets**
   (`[database] url`, `[app] cloud = true`, dan bila mau `[app] password`).
3. Setelah jalan, buka **Settings > Sharing** dan batasi ke email Anda saja.
4. Di ponsel: buka alamatnya di Chrome, menu titik tiga, **Tambahkan ke layar utama**.

## 6. Memperbarui data produk (tetap dari komputer)

Server tidak punya browser, jadi tombol refresh diganti petunjuk. Seminggu sekali di komputer Anda:

```
python -m tracker.refresh
git add data && git commit -m "Perbarui data produk" && git push
```

Streamlit Cloud otomatis memuat ulang aplikasi setelah push. Setelah itu isi **Isi rekomendasi robo** di aplikasi.

## Keamanan (ringkas)

- Repo privat; `.streamlit/secrets.toml` dan data pribadi ada di `.gitignore`.
- Akses aplikasi: batasi email di Streamlit, plus kata sandi opsional di `[app] password`.
- Database: sandi kuat, Row Level Security aktif, hanya dipakai lewat koneksi dari aplikasi.
- Jangan membagikan alamat aplikasi sebelum pembatasan email aktif.

## Pemecahan masalah

- **"could not connect"**: pakai string **Transaction pooler**, bukan koneksi langsung; periksa sandi dan tanda kurung siku.
- **Aplikasi "tidur"** di paket gratis setelah lama tidak dibuka; klik tombol bangunkan, biasanya beberapa detik.
- **Sidebar masih menulis "File lokal"**: URL database belum terbaca; cek nama bagian `[database]` dan kunci `url`.
- **Cadangan**: di tab Portofolio, panel Kelola data portofolio, tab Unggah CSV, ada tombol Cadangkan posisi dan transaksi.
  Unduh sesekali dan simpan di komputer Anda. File yang sama bisa diunggah kembali bila perlu memulihkan.
