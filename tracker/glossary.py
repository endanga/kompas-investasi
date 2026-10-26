"""Glossary for the 'Istilah' tab: plain-language definitions grouped by topic.

Each entry is (term, meaning, example or ""). Meanings stay general (no tax rates, fees or limits that change over time);
anything specific to Bibit is worded as "di Bibit" only where the app itself already states it.
"""
from __future__ import annotations

GROUPS: dict[str, list[tuple[str, str, str]]] = {
    "Dasar": [
        ("Reksa dana", "Wadah yang mengumpulkan uang banyak investor, lalu dikelola manajer investasi untuk dibelikan ke kumpulan "
                       "efek seperti obligasi atau saham. Anda membeli bagian dari wadah itu, bukan efeknya satu per satu.",
         "Dengan Rp100.000 Anda sudah bisa memiliki bagian dari ratusan efek sekaligus."),
        ("Manajer investasi", "Perusahaan berizin OJK yang memilih dan mengelola isi reksa dana. Kinerja dan biaya produk "
                              "berbeda-beda antar manajer investasi.", ""),
        ("Bank kustodian", "Bank yang menyimpan aset reksa dana, terpisah dari manajer investasi. Uang Anda tidak dipegang "
                           "langsung oleh manajer investasi.", ""),
        ("OJK", "Otoritas Jasa Keuangan, lembaga yang mengawasi reksa dana, manajer investasi, dan penyelenggara investasi.", ""),
        ("Return", "Perubahan nilai investasi dalam persen. Di aplikasi ini 'return 1 tahun' dan 'return 3 tahun' adalah "
                   "total selama periode itu, bukan rata-rata per tahun.",
         "Return 3 tahun 15% berarti Rp100 juta menjadi sekitar Rp115 juta setelah 3 tahun."),
        ("Inflasi", "Kenaikan harga barang dan jasa dari waktu ke waktu. Uang yang sama membeli lebih sedikit di masa depan, "
                    "jadi return perlu dibandingkan dengan inflasi.",
         "Inflasi 3% per tahun: barang Rp100.000 hari ini menjadi sekitar Rp134.000 setelah 10 tahun."),
        ("Daya beli", "Berapa banyak barang yang bisa dibeli dengan sejumlah uang. 'Nilai akhir (daya beli sekarang)' adalah "
                      "nilai masa depan yang dihitung ulang dengan harga hari ini.", ""),
        ("Bunga majemuk", "Hasil investasi yang ikut menghasilkan lagi di periode berikutnya. Makin lama ditahan, makin besar "
                          "pengaruhnya; itu sebabnya waktu adalah faktor terpenting dalam investasi jangka panjang.", ""),
        ("DCA (dollar cost averaging)", "Menyetor nominal tetap secara rutin, tanpa mencoba menebak waktu pasar. Saat harga "
                                        "turun Anda mendapat lebih banyak unit, saat naik lebih sedikit.", ""),
        ("Diversifikasi", "Menyebar dana ke beberapa jenis aset atau produk supaya satu kejadian buruk tidak menghabiskan "
                          "seluruh portofolio.", ""),
        ("Likuiditas", "Seberapa cepat dan mudah investasi dicairkan menjadi uang tunai tanpa rugi besar. Pasar uang paling "
                       "likuid; SBN ritel hanya bisa dibeli saat masa penawaran.", ""),
        ("Horizon investasi", "Lama waktu sampai uangnya dipakai. Makin pendek horizon, makin kecil bagian saham yang pantas.",
         "Dana pensiun 25 tahun lagi: horizon 25 tahun."),
        ("Dana darurat", "Simpanan tunai untuk kebutuhan mendadak, umumnya beberapa bulan pengeluaran, disimpan di tempat yang "
                         "mudah dicairkan dan tidak naik-turun. Sebaiknya di luar investasi berisiko.", ""),
    ],
    "Produk": [
        ("Reksa dana pasar uang", "Dananya ditaruh di deposito dan surat utang jangka pendek. Naik-turunnya sangat kecil dan "
                                  "paling mudah dicairkan, tapi return-nya juga paling rendah.", ""),
        ("Reksa dana pendapatan tetap", "Sebagian besar (minimal 80%) dananya di obligasi. Return biasanya di atas pasar uang, "
                                        "tapi nilainya bisa turun saat suku bunga naik atau penerbit bermasalah.", ""),
        ("Reksa dana saham", "Sebagian besar (minimal 80%) dananya di saham. Potensi return paling besar, juga turun paling "
                             "dalam; cocok untuk dana yang tidak dipakai dalam waktu lama.", ""),
        ("Reksa dana campuran", "Gabungan saham, obligasi, dan pasar uang tanpa satu jenis yang melebihi 79%.", ""),
        ("Reksa dana indeks", "Mengikuti sebuah indeks saham atau obligasi, bukan memilih-milih sendiri. Isinya transparan dan "
                              "biayanya cenderung lebih rendah.", "Contoh indeks: IDX30, LQ45, KEHATI."),
        ("Reksa dana syariah", "Dikelola sesuai prinsip syariah dan diawasi Dewan Syariah Nasional. Di aplikasi ini status "
                               "syariah hanya ditebak dari kata 'syariah' pada nama produk, jadi cek prospektusnya.", ""),
        ("SBN ritel", "Surat Berharga Negara untuk individu, seperti ORI, SBR, SR, dan ST. Diterbitkan dan dijamin pemerintah. "
                      "Hanya bisa dibeli saat masa penawaran (pasar perdana).", ""),
        ("Obligasi FR", "Obligasi negara dengan kupon tetap (Fixed Rate) yang bisa diperjualbelikan kapan saja. Harganya naik-turun "
                        "mengikuti suku bunga, jadi nilai jualnya bisa berbeda dari modal.", ""),
        ("Saham", "Bukti kepemilikan sebagian perusahaan. Harganya bisa berubah besar dalam waktu singkat. Berbeda dari reksa "
                  "dana saham, risikonya terpusat pada perusahaan yang Anda pilih.", ""),
        ("Robo-advisor", "Layanan yang membagi dana ke beberapa produk secara otomatis sesuai profil risiko Anda. Robo Bibit "
                         "memakai profil risiko 1 sampai 10.", ""),
        ("Bibit Plus", "Tingkat akun Bibit yang diperlukan untuk SBN, Obligasi FR, dan saham, menurut halaman produk Bibit.", ""),
    ],
    "Risiko": [
        ("Profil risiko", "Tingkat keberanian menanggung naik-turun, dari 1 (paling konservatif) sampai 10 (paling agresif) di "
                          "Bibit. Setiap profil punya pembagian pasar uang, obligasi, dan saham tertentu.",
         "Profil 4,5: pasar uang 12%, obligasi 70%, saham 18%."),
        ("Toleransi risiko", "Seberapa besar penurunan yang masih bisa Anda terima tanpa panik menjual. Di sidebar ini diisi "
                             "sebagai 'batas penurunan'.", ""),
        ("Volatilitas", "Seberapa besar harga naik-turun dari hari ke hari. Volatilitas tinggi berarti perjalanan lebih "
                        "bergejolak, bukan otomatis rugi.", ""),
        ("Drawdown", "Penurunan dari titik tertinggi ke titik terendah berikutnya. Di aplikasi ini angkanya diambil dari 1 tahun "
                     "terakhir, jadi penurunan yang lebih lama atau lebih dalam di masa lalu belum terlihat.",
         "Naik ke Rp120, turun ke Rp90: drawdown 25%."),
        ("Stress test", "Simulasi 'bagaimana kalau terjadi hal buruk': tiap jenis aset diberi penurunan lalu dihitung kerugian total. "
                        "Di sini ada dua: 'tahun buruk' dari data 1 tahun terakhir, dan 'krisis berat' dari asumsi yang bisa Anda ubah.",
         "Saham -40% dan obligasi -8% pada komposisi 18% saham dan 70% obligasi: kerugian sekitar 12,8%."),
        ("Risiko pasar", "Risiko nilai turun karena kondisi pasar secara umum, bukan karena kesalahan satu produk.", ""),
        ("Risiko suku bunga", "Saat suku bunga naik, harga obligasi yang sudah ada cenderung turun, dan sebaliknya. Makin "
                              "panjang jatuh temponya, makin besar pengaruhnya.", ""),
        ("Risiko kredit", "Risiko penerbit obligasi gagal membayar kupon atau pokok. Obligasi pemerintah risikonya paling kecil.", ""),
        ("Return per risiko", "Perbandingan return dengan penurunan terdalamnya. Dipakai di aplikasi ini untuk meranking reksa "
                              "dana pendapatan tetap, supaya yang return-nya besar tapi turunnya dalam tidak otomatis menang.", ""),
        ("Kinerja masa lalu", "Return dan penurunan yang sudah terjadi. Berguna untuk melihat sifat produk, tetapi tidak "
                              "menjamin hal yang sama di masa depan.", ""),
        ("Rebalancing", "Mengembalikan komposisi portofolio ke target. Di aplikasi ini dilakukan lewat setoran baru ke jenis "
                        "yang kurang, tanpa menjual yang sudah ada.", ""),
        ("Konsentrasi", "Terlalu banyak dana di satu produk atau satu jenis aset. Aplikasi ini memberi peringatan bila satu "
                        "produk lebih dari 50% portofolio.", ""),
    ],
    "Obligasi & SBN": [
        ("Kupon", "Bunga tetap yang dibayar penerbit obligasi secara berkala, dihitung dari nilai pokok.",
         "Kupon 6,5% pada Rp10 juta: Rp650.000 per tahun."),
        ("Yield", "Imbal hasil tahunan obligasi bila dibeli di harga sekarang dan ditahan sampai jatuh tempo. Berbeda dari "
                  "kupon bila harga belinya bukan 100%.", ""),
        ("Jatuh tempo", "Tanggal penerbit mengembalikan nilai pokok obligasi. Menahan sampai jatuh tempo menghindarkan Anda "
                        "dari harga pasar yang naik-turun.", ""),
        ("Harga beli dan jual", "Obligasi FR punya dua harga. Selisihnya (spread) adalah biaya Anda, sehingga membeli lalu "
                                "langsung menjual hampir selalu rugi kecil.", ""),
        ("Pasar perdana dan sekunder", "Perdana: membeli langsung dari penerbit saat masa penawaran. Sekunder: membeli dari "
                                       "investor lain kapan saja, dengan harga pasar.", ""),
        ("Durasi", "Ukuran seberapa sensitif harga obligasi terhadap perubahan suku bunga. Durasi 5 kira-kira berarti harga "
                   "turun sekitar 5% bila suku bunga naik 1 poin.", ""),
    ],
    "Biaya": [
        ("NAV", "Nilai aktiva bersih per unit reksa dana, dihitung setiap hari bursa. Harga beli dan jual reksa dana mengikuti NAV.", ""),
        ("Unit penyertaan", "Jumlah 'lembar' reksa dana yang Anda miliki. Nilai investasi = unit x NAV.",
         "100 unit x NAV Rp1.500 = Rp150.000."),
        ("Dana kelolaan (AUM)", "Total dana yang dikelola sebuah reksa dana. Dana yang terlalu kecil berisiko ditutup atau sulit "
                                "dicairkan, sehingga aplikasi ini hanya mempertimbangkan yang di atas Rp100 miliar.", ""),
        ("Biaya pengelolaan", "Biaya tahunan untuk manajer investasi, sudah dipotong dari NAV sehingga tidak muncul sebagai "
                              "tagihan. Biaya kecil yang berjalan puluhan tahun berdampak besar pada hasil akhir. Aplikasi ini "
                              "belum membaca biaya tiap produk.", ""),
        ("Pencairan", "Menjual unit reksa dana menjadi uang. Uang masuk biasanya setelah beberapa hari bursa, dan lamanya "
                      "berbeda antar jenis produk.", ""),
        ("Prospektus", "Dokumen resmi produk: isi portofolio, biaya, risiko, dan kebijakan investasi. Bacalah sebelum membeli, "
                       "terutama bagian risiko dan biaya.", ""),
        ("Fund fact sheet", "Ringkasan bulanan satu halaman tentang kinerja, komposisi, dan biaya sebuah reksa dana.", ""),
    ],
    "Di aplikasi ini": [
        ("Batas penurunan", "Angka yang Anda isi di sidebar. Sistem memilih profil risiko tertinggi yang perkiraan turunnya "
                            "tidak melewati batas ini.", ""),
        ("Perkiraan turun di tahun buruk", "Hasil stress test untuk komposisi rekomendasi, atau untuk total portofolio bila Anda "
                                           "sudah punya isi. Bukan batas kerugian yang dijamin.", ""),
        ("Dalam batas / Melewati batas", "Status perbandingan perkiraan turun dengan batas penurunan Anda. Selalu disertai "
                                         "ikon dan tulisan, bukan warna saja.", ""),
        ("Pesimis, Dasar, Optimis", "Tiga asumsi return untuk proyeksi. Pesimis = kondisi kurang bagus (saham nyaris impas), "
                                    "Dasar = kondisi biasa, Optimis = kondisi cukup baik. Ketiganya asumsi, bukan ramalan.",
         "Jadikan Pesimis sebagai rencana; bila target tercapai di situ, rencananya tangguh."),
        ("Setoran menutup selisih", "Dengan portofolio terisi, setoran bulanan diarahkan ke jenis yang di bawah target dan tidak "
                                    "ke yang sudah berlebih. Tidak ada yang perlu dijual.", ""),
        ("Skor produk", "Nilai 0-100 dari peringkat persentil produk di kategorinya menurut kriteria yang berbeda tiap jenis. "
                        "Alasan pemilihan ditulis di tiap kartu produk.", ""),
        ("XIRR", "Return tahunan yang memperhitungkan tanggal tiap setoran dan penarikan. Kurang andal bila data baru beberapa bulan.", ""),
        ("Snapshot data", "Data produk diambil pada tanggal tertentu dan cepat usang. Perbarui sekitar seminggu sekali dan "
                          "selalu cek halaman produk di Bibit sebelum membeli.", ""),
    ],
}

ALL = "Semua"


def all_terms() -> list[tuple[str, str, str, str]]:
    """Flat list of (group, term, meaning, example)."""
    return [(g, t, m, e) for g, rows in GROUPS.items() for t, m, e in rows]


def search(query: str = "", group: str = ALL) -> list[tuple[str, str, str, str]]:
    """Entries of `group` whose term or meaning contains every word of `query` (case-insensitive)."""
    words = query.lower().split()
    out = []
    for g, term, meaning, example in all_terms():
        if group != ALL and g != group:
            continue
        haystack = f"{term} {meaning} {example}".lower()
        if all(w in haystack for w in words):
            out.append((g, term, meaning, example))
    return out
