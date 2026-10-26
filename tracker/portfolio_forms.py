"""Streamlit screens for entering portfolio data: manual forms, CSV upload and a table editor.

All writes go through portfolio_io (validation + backup to data/archive); a successful write sets a one-shot message and
reruns the app so the recommendation, portfolio tab and PDF immediately use the new data.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from . import portfolio_io as pio
from .ui import CATEGORY_NAMES, fmt_idr

AUTO = "Otomatis dari katalog"
KIND_LABEL = {"holdings": "Posisi (nilai sekarang)", "transactions": "Transaksi"}


def _cat_label(cat: str) -> str:
    return CATEGORY_NAMES.get(cat, cat)


def _done(message: str) -> None:
    st.session_state["pf_flash"] = message
    st.session_state["pf_gen"] = st.session_state.get("pf_gen", 0) + 1  # resets editors and uploader
    st.rerun()


def _product_options(catalog: pd.DataFrame, holdings: pd.DataFrame) -> list[str]:
    owned = holdings["product"].dropna().astype(str).tolist()
    return list(dict.fromkeys([*owned, *sorted(catalog["name"].dropna().astype(str).unique())]))


def _resolve_category(choice: str, product: str, catalog: pd.DataFrame) -> str | None:
    return pio.infer_category(product, catalog) if choice == AUTO else choice


def _category_picker(key: str) -> str:
    return st.selectbox("Jenis", [AUTO, *pio.CATEGORIES], format_func=lambda c: c if c == AUTO else _cat_label(c), key=key,
                        help="Otomatis bekerja bila nama produk ada di katalog Bibit. Untuk SBN, Obligasi FR, atau saham "
                             "individu, pilih jenisnya sendiri.")


def _transaction_form(catalog: pd.DataFrame, holdings: pd.DataFrame, tx: pd.DataFrame, gen: int) -> None:
    with st.form(f"pf_tx_form_{gen}", border=True):
        c1, c2 = st.columns(2)
        when = c1.date_input("Tanggal", value=date.today(), max_value=date.today(), format="YYYY-MM-DD")
        kind = c2.radio("Jenis transaksi", ["Beli", "Jual"], horizontal=True)
        product = st.selectbox("Produk", _product_options(catalog, holdings), index=None, accept_new_options=True,
                               placeholder="Pilih dari katalog atau ketik nama produk")
        c3, c4 = st.columns(2)
        with c3:
            choice = _category_picker("pf_tx_cat")
        amount = c4.number_input("Nominal (Rp)", min_value=0, value=0, step=100_000)
        also = st.checkbox("Perbarui nilai posisi juga (beli menambah, jual mengurangi)", value=True)
        if st.form_submit_button("Simpan transaksi", type="primary", icon=":material/add:"):
            name = (product or "").strip()
            cat = _resolve_category(choice, name, catalog) if name else None
            if not name:
                st.error("Pilih atau ketik nama produk.")
            elif cat is None:
                st.error("Jenis produk tidak dikenali dari katalog. Pilih jenisnya secara manual.")
            elif amount <= 0:
                st.error("Nominal harus lebih dari 0.")
            else:
                row = pd.DataFrame([(when.isoformat(), name, cat, "BUY" if kind == "Beli" else "SELL", float(amount))],
                                   columns=pio.TX_COLS)
                new_tx = pio.merge(tx, row, "transactions")
                new_holdings = pio.apply_transaction_to_holdings(holdings, name, cat, row.iloc[0]["type"], float(amount)) \
                    if also else None
                pio.save(new_holdings, new_tx)
                _done(f"Transaksi {kind.lower()} {name} sebesar {fmt_idr(amount)} tersimpan.")


def _holding_form(catalog: pd.DataFrame, holdings: pd.DataFrame, gen: int) -> None:
    st.caption("Isi nilai terbaru produk dari aplikasi Bibit (bukan modal). Nilai lama produk yang sama diganti.")
    with st.form(f"pf_hold_form_{gen}", border=True):
        product = st.selectbox("Produk", _product_options(catalog, holdings), index=None, accept_new_options=True,
                               placeholder="Pilih dari katalog atau ketik nama produk", key="pf_hold_prod")
        c1, c2 = st.columns(2)
        with c1:
            choice = _category_picker("pf_hold_cat")
        value = c2.number_input("Nilai sekarang (Rp)", min_value=0, value=0, step=100_000)
        if st.form_submit_button("Simpan nilai", type="primary", icon=":material/save:"):
            name = (product or "").strip()
            cat = _resolve_category(choice, name, catalog) if name else None
            if not name:
                st.error("Pilih atau ketik nama produk.")
            elif cat is None:
                st.error("Jenis produk tidak dikenali dari katalog. Pilih jenisnya secara manual.")
            elif value <= 0:
                st.error("Nilai harus lebih dari 0. Untuk menghapus produk, pakai tab Edit tabel.")
            else:
                pio.save(pio.set_holding(holdings, name, cat, float(value)), None)
                _done(f"Nilai {name} tersimpan: {fmt_idr(value)}.")


def _upload(holdings: pd.DataFrame, tx: pd.DataFrame, gen: int) -> None:
    st.caption("Unggah file CSV posisi dan/atau transaksi. Pemisah koma atau titik koma diterima; nominal boleh ditulis "
               "'Rp1.500.000'. Jenis dikenali dari kolomnya.")
    t1, t2 = st.columns(2)
    t1.download_button("Unduh contoh posisi", pio.HOLDINGS_TEMPLATE, "contoh_holdings.csv", "text/csv",
                       icon=":material/download:", width="stretch")
    t2.download_button("Unduh contoh transaksi", pio.TX_TEMPLATE, "contoh_transactions.csv", "text/csv",
                       icon=":material/download:", width="stretch")
    d1, d2 = st.columns(2)
    d1.download_button("Cadangkan posisi saat ini (CSV)", holdings.to_csv(index=False), "holdings.csv", "text/csv",
                       icon=":material/backup:", width="stretch", disabled=holdings.empty, key=f"pf_dl_h_{gen}")
    d2.download_button("Cadangkan transaksi saat ini (CSV)", tx.to_csv(index=False), "transactions.csv", "text/csv",
                       icon=":material/backup:", width="stretch", disabled=tx.empty, key=f"pf_dl_t_{gen}")
    files = st.file_uploader("Pilih file CSV", type=["csv"], accept_multiple_files=True, key=f"pf_upload_{gen}")
    if not files:
        return
    parsed: dict[str, pd.DataFrame] = {}
    problems = False
    for f in files:
        try:
            df = pio.read_csv_bytes(f.getvalue())
        except Exception as e:  # unreadable or empty file
            st.error(f"{f.name}: file tidak bisa dibaca ({e}).")
            problems = True
            continue
        kind = pio.detect_kind(df)
        if kind is None:
            st.error(f"{f.name}: kolom tidak dikenali. Posisi butuh product, category, current_value; "
                     "transaksi butuh date, product, category, type, amount.")
            problems = True
            continue
        clean, errors = (pio.clean_holdings if kind == "holdings" else pio.clean_transactions)(df)
        st.markdown(f"**{f.name}** · {KIND_LABEL[kind]} · {len(clean)} baris valid")
        if errors:
            problems = True
            st.error("\n".join(f"- {e}" for e in errors[:15]) + (f"\n- ...dan {len(errors) - 15} lainnya." if len(errors) > 15 else ""))
        elif kind in parsed:
            st.warning(f"Ada lebih dari satu file {KIND_LABEL[kind].lower()}; hanya yang terakhir dipakai.")
        if not errors:
            parsed[kind] = clean
            st.dataframe(clean.head(8), hide_index=True, width="stretch")
    if problems or not parsed:
        st.info("Perbaiki file di atas lalu unggah ulang. Tidak ada data yang diubah.")
        return
    mode = st.radio("Cara memasukkan", ["Gabungkan dengan data sekarang", "Ganti semua data"], horizontal=True,
                    help="Gabungkan: posisi dengan nama produk sama diganti nilainya, transaksi baru ditambahkan tanpa duplikat. "
                         "Ganti semua: isi file lama diarsipkan di data/archive lalu diganti.")
    if st.button("Impor data", type="primary", icon=":material/upload:"):
        replace = mode == "Ganti semua data"
        new_h = new_t = None
        if "holdings" in parsed:
            new_h = parsed["holdings"] if replace else pio.merge(holdings, parsed["holdings"], "holdings")
        if "transactions" in parsed:
            new_t = parsed["transactions"] if replace else pio.merge(tx, parsed["transactions"], "transactions")
        pio.save(new_h, new_t)
        _done("Data diimpor: " + ", ".join(f"{len(v)} baris {KIND_LABEL[k].lower()}" for k, v in parsed.items()) + ".")


def _editor(holdings: pd.DataFrame, tx: pd.DataFrame, gen: int) -> None:
    st.caption("Ubah angka langsung di tabel, tambah baris dengan baris kosong di bawah, atau hapus dengan memilih baris "
               "lalu menekan ikon tempat sampah. Tekan Simpan untuk menerapkan.")
    st.markdown("**Posisi**")
    edited_h = st.data_editor(
        holdings, num_rows="dynamic", hide_index=True, width="stretch", key=f"pf_edit_h_{gen}",
        column_config={
            "product": st.column_config.TextColumn("Produk", required=True),
            "category": st.column_config.SelectboxColumn("Jenis", options=pio.CATEGORIES, required=True),
            "current_value": st.column_config.NumberColumn("Nilai sekarang (Rp)", min_value=0, step=100_000, format="localized", required=True),
        })
    if st.button("Simpan posisi", icon=":material/save:", key=f"pf_save_h_{gen}"):
        clean, errors = pio.clean_holdings(edited_h)
        if errors:
            st.error("\n".join(f"- {e}" for e in errors))
        else:
            pio.save(clean, None)
            _done(f"Posisi tersimpan ({len(clean)} produk).")

    st.markdown("**Transaksi**")
    tx_view = tx.copy()
    tx_view["date"] = pd.to_datetime(tx_view["date"], errors="coerce").dt.date
    edited_t = st.data_editor(
        tx_view, num_rows="dynamic", hide_index=True, width="stretch", key=f"pf_edit_t_{gen}",
        column_config={
            "date": st.column_config.DateColumn("Tanggal", format="YYYY-MM-DD", required=True),
            "product": st.column_config.TextColumn("Produk", required=True),
            "category": st.column_config.SelectboxColumn("Jenis", options=pio.CATEGORIES, required=True),
            "type": st.column_config.SelectboxColumn("Tipe", options=pio.TX_TYPES, required=True),
            "amount": st.column_config.NumberColumn("Nominal (Rp)", min_value=0, step=100_000, format="localized", required=True),
        })
    if st.button("Simpan transaksi", icon=":material/save:", key=f"pf_save_t_{gen}"):
        clean, errors = pio.clean_transactions(edited_t.astype({"date": str}))
        if errors:
            st.error("\n".join(f"- {e}" for e in errors))
        else:
            pio.save(None, clean)
            _done(f"Transaksi tersimpan ({len(clean)} baris).")


def render(catalog: pd.DataFrame, expanded: bool = False) -> None:
    """The 'Kelola data portofolio' panel. Reads the CSVs fresh so it is never stale after a write."""
    gen = st.session_state.get("pf_gen", 0)
    flash = st.session_state.pop("pf_flash", None)
    if flash:
        st.success(flash, icon=":material/check_circle:")
    holdings, tx = pio.read_current()
    with st.expander("Kelola data portofolio: input manual, unggah CSV, edit tabel", expanded=expanded or bool(flash)):
        t_tx, t_val, t_up, t_edit = st.tabs(["Tambah transaksi", "Perbarui nilai produk", "Unggah CSV", "Edit tabel"])
        with t_tx:
            _transaction_form(catalog, holdings, tx, gen)
        with t_val:
            _holding_form(catalog, holdings, gen)
        with t_up:
            _upload(holdings, tx, gen)
        with t_edit:
            _editor(holdings, tx, gen)
        st.caption("Setiap perubahan menyimpan file lama ke data/archive lebih dulu. Rekomendasi langsung memakai data baru.")
