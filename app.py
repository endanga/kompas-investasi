import hmac
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from tracker import (glossary, history, metrics, portfolio_forms, portfolio_io, portfolio_plan, products, recommend, refresh, report,
                     robo, rules, settings, storage, ui)

DATA = Path(__file__).parent / "data"
TODAY = date.today()
SCENARIO_KEY = "Dasar"

st.set_page_config(page_title="Kompas Investasi", page_icon=":material/trending_up:", layout="wide")
ui.inject_css()
mode = ui.theme_mode()
CLOUD = settings.cloud_mode()
REFRESH_HOWTO = ("Pembaruan data produk memerlukan browser di komputer, jadi tidak bisa dijalankan di sini. Di komputer Anda: "
                 "jalankan `python -m tracker.refresh`, lalu commit dan push file di folder `data/` (CSV produk).")


def require_password() -> None:
    """Optional shared-secret gate for a hosted deployment (set app.password in secrets). Does nothing when unset."""
    secret = settings.app_password()
    if not secret or st.session_state.get("authed"):
        return
    st.markdown(ui.hero("Kompas Investasi", "Masukkan kata sandi untuk melanjutkan.", []), unsafe_allow_html=True)
    entered = st.text_input("Kata sandi", type="password", key="app_pw")
    if entered and hmac.compare_digest(entered.encode(), secret.encode()):
        st.session_state["authed"] = True
        st.rerun()
    if entered:
        st.error("Kata sandi salah.")
    st.stop()


require_password()

@st.dialog("Perbarui data produk?")
def confirm_refresh(current_date: str) -> None:
    st.write(f"Data saat ini per **{current_date}**. Sistem akan membuka jendela Edge sekitar 1 menit untuk membaca "
             "halaman produk Bibit, lalu menutupnya sendiri.")
    st.caption("Data lama diarsipkan di data/archive. Jangan tutup jendela Edge yang terbuka dan jangan "
               "pakai aplikasi ini sampai selesai.")
    yes, no = st.columns(2)
    if no.button("Batal", width="stretch"):
        st.rerun()
    if yes.button("Ya, perbarui", type="primary", icon=":material/sync:", width="stretch"):
        with st.spinner("Membaca halaman produk Bibit... jendela Edge akan terbuka sebentar."):
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "tracker.refresh"], cwd=Path(__file__).parent, capture_output=True,
                    text=True, encoding="utf-8", timeout=300, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                st.session_state["refresh_result"] = (
                    proc.returncode == 0, refresh.format_markdown(proc.stdout + "\n" + proc.stderr))
                if proc.returncode == 0:
                    st.session_state["robo_prompt"] = True  # ask for the robo's picks right after new data arrives
            except subprocess.TimeoutExpired:
                st.session_state["refresh_result"] = (False, "Waktu habis (5 menit). Data lama tetap dipakai.")
        st.rerun()


def recovery_screen(reason: str) -> None:
    """Shown instead of the app when the fund catalog is missing or unusable; offers the two ways out, then stops."""
    st.markdown(ui.hero("Kompas Investasi", "Data produk Bibit belum bisa dipakai.", ["Perlu dipulihkan"]), unsafe_allow_html=True)
    st.markdown(ui.empty_state("Data produk belum tersedia", reason, ["data/products.csv"]), unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    flash = st.session_state.pop("refresh_result", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])
    st.markdown(ui.section("Cara memulihkan"), unsafe_allow_html=True)
    a, b = st.columns(2, gap="medium")
    with a, st.container(border=True):
        st.markdown("**1. Ambil data baru dari Bibit**")
        if CLOUD:
            st.caption(REFRESH_HOWTO)
        else:
            st.caption("Membuka jendela Edge sekitar 1 menit untuk membaca halaman produk Bibit.")
            if st.button("Perbarui data produk", icon=":material/sync:", type="primary", width="stretch", key="rec_refresh"):
                confirm_refresh("belum ada")
    with b, st.container(border=True):
        st.markdown("**2. Pulihkan dari arsip**")
        archives = products.list_archives()
        if not archives:
            st.caption("Belum ada arsip data produk yang bisa dipakai.")
        else:
            st.caption("Snapshot lama disimpan otomatis setiap kali data diperbarui.")
            pick = st.selectbox("Arsip", archives, format_func=lambda a: f"Data per {a['as_of']} · {a['funds']} reksa dana ({a['name']})",
                                key="rec_archive")
            if st.button("Pulihkan arsip ini", icon=":material/history:", width="stretch", key="rec_restore"):
                restored = products.restore_archive(pick["path"])
                st.session_state["refresh_result"] = (True, f"**Data dipulihkan** dari arsip {pick['name']}: " + ", ".join(f"`{n}`" for n in restored))
                st.rerun()
    st.stop()


portfolio_io.ensure_files()
catalog, catalog_problem = products.try_load_products()
if catalog_problem:
    recovery_screen(catalog_problem)
data_date = str(catalog["as_of"].iloc[0])
data_age = (TODAY - date.fromisoformat(data_date)).days
all_profiles = rules.load_profiles()
level_keys = sorted((k for k in all_profiles if recommend.level_of(k) is not None), key=recommend.level_of)
profile_by_level = {recommend.level_of(k): k for k in level_keys}
RISK_TITLE = "Profil risiko"


def profile_name(key: str) -> str:
    return key.split("_", 2)[-1].capitalize()


def level_label(key: str) -> str:
    return f"{ui.fmt_level(recommend.level_of(key))} ({profile_name(key)})"


def alloc_text(alloc: dict[str, float]) -> str:
    return " · ".join(f"{ui.CATEGORY_NAMES.get(c, c)} {s:.0%}" for c, s in alloc.items() if s > 0)


@st.dialog("Rekomendasi robo Bibit", width="large")
def robo_dialog(default_key: str) -> None:
    st.write("Buka robo di aplikasi Bibit, lalu pilih produk yang robo rekomendasikan untuk profil risiko ini. "
             "Isiannya dipakai untuk membandingkan pilihan sistem dengan robo di tab Rekomendasi.")
    key = st.selectbox(f"{RISK_TITLE} robo", level_keys, index=level_keys.index(default_key), format_func=level_label,
                       key="robo_level_pick")
    level, alloc = recommend.level_of(key), all_profiles[key]
    current, meta = robo.resolve(level, robo.load())
    if meta["source"] == "input":
        st.caption(f"Terakhir diisi {meta['saved_at'].replace('T', ' ')} untuk data produk per {meta['data_as_of']}.")
    elif meta["source"] == "screenshot":
        st.caption("Belum pernah diisi di sini; isian awal berasal dari screenshot robo Anda.")
    else:
        st.caption("Belum ada data robo untuk profil ini; isian awal hanya perkiraan dan belum dicocokkan dengan aplikasi Bibit.")
    with st.form(f"robo_form_{key}", border=True):
        chosen = {}
        for cat, share in alloc.items():
            if share <= 0:
                continue
            names = sorted(catalog.loc[catalog["category"] == cat, "name"].astype(str))
            options = [*names, robo.SKIP]
            start = options.index(current[cat]) if current.get(cat) in options else None
            chosen[cat] = st.selectbox(f"{ui.CATEGORY_NAMES.get(cat, cat)} ({share:.0%})", options, index=start,
                                       placeholder="Pilih produk", key=f"robo_{key}_{cat}")
        if st.form_submit_button("Simpan rekomendasi robo", type="primary", icon=":material/save:"):
            if any(v is None for v in chosen.values()):
                st.error("Pilih produk untuk tiap jenis, atau pilih '(tidak ada / lewati)'.")
            else:
                robo.save_entry(level, chosen, data_date)
                st.session_state["robo_saved"] = f"Rekomendasi robo untuk profil risiko {ui.fmt_level(level)} tersimpan."
                st.rerun()
    if st.button("Nanti saja", width="stretch"):
        st.rerun()


# ----------------------------------------------------------------------------- sidebar
N_SYARIAH = int((catalog["syariah_dari_nama"] == "ya").sum())
with st.sidebar:
    summary_slot = st.container()  # filled once every input below is known

    st.markdown(ui.side_title(1, "Tujuan dan dana", "Berapa lama dan berapa banyak Anda berinvestasi."), unsafe_allow_html=True)
    horizon = st.number_input(
        "Jangka waktu tujuan (tahun)", 0.5, 40.0, 25.0, 0.5,
        help="Kapan uangnya dipakai, misalnya pensiun. Makin pendek tujuannya, makin konservatif rekomendasinya: "
             "di bawah 3 tahun maksimal profil risiko 3, di bawah 5 tahun maksimal 5.")
    budget = st.number_input(
        "Dana per bulan (Rp)", 0, 1_000_000_000, 5_000_000, 500_000,
        help="Nominal yang Anda setor tiap bulan. Dana darurat sebaiknya tersimpan di luar Bibit.")
    st.caption(f"Total setoran selama tujuan: {ui.fmt_idr_short(budget * 12 * horizon)}")

    st.markdown(ui.side_title(2, "Toleransi risiko", "Seberapa besar penurunan yang masih bisa Anda terima."), unsafe_allow_html=True)
    max_drop_pct = st.slider(
        "Batas penurunan yang masih nyaman (%)", 3, 40, 10, key="rec_drop",
        help="Penurunan nilai terbesar di tahun yang buruk yang masih Anda terima tanpa panik menjual. "
             "Sistem memilih profil risiko tertinggi yang perkiraan turunnya tidak melewati batas ini.")
    st.caption(f"Artinya: dari tiap Rp100 juta, Anda siap melihatnya turun sampai Rp{max_drop_pct} juta sementara.")
    syariah_only = st.toggle(
        "Hanya produk syariah", value=False,
        help="Hanya mempertimbangkan reksa dana yang namanya mengandung kata 'syariah'. Cara ini menebak dari nama produk; "
             "daftar efek syariah resmi OJK tidak dicek, jadi cek prospektusnya bila status syariah penting bagi Anda. "
             "Pilihan produk lebih sedikit, dan profil dengan saham bisa kekurangan produk.")
    if syariah_only:
        counts = {ui.CATEGORY_NAMES[c].lower(): len(recommend.eligible(catalog, c, True)) for c in ("pasar_uang", "pendapatan_tetap", "saham")}
        st.caption(f"Terdeteksi {N_SYARIAH} dari {len(catalog)} reksa dana. Lolos saringan: "
                   + ", ".join(f"{n} {k}" for k, n in counts.items()) + ".")
    else:
        st.caption(f"Semua {len(catalog)} reksa dana dipertimbangkan, {N_SYARIAH} di antaranya terdeteksi syariah.")

    st.markdown(ui.side_title(3, RISK_TITLE, "Pembagian dana ke pasar uang, obligasi, dan saham."), unsafe_allow_html=True)
    is_auto = st.toggle(
        "Pilih otomatis", value=True,
        help="Sistem memilih profil risiko tertinggi yang masih dalam batas penurunan dan horizon Anda. "
             "Matikan untuk memilih sendiri, misalnya sama dengan robo di aplikasi Bibit.",
    )
    auto_rec = recommend.recommend(
        catalog, all_profiles, max_drop_pct / 100, horizon, float(budget), syariah_only,
        crisis=metrics.crisis_shocks(st.session_state.get("crisis_saham", 40), st.session_state.get("crisis_obl", 8),
                                     st.session_state.get("crisis_pu", 0)),
        strict=st.session_state.get("strict_rule", True))
    if is_auto:
        st.slider(RISK_TITLE, 1.0, 10.0, float(auto_rec.level), 0.5, format="%.1f",
                  disabled=True, key=f"risk_auto_{auto_rec.level}")
        risk_level = auto_rec.level
    else:
        risk_level = st.slider(RISK_TITLE, 1.0, 10.0, float(auto_rec.level), 0.5, format="%.1f", key="risk_manual")
    chosen_key = profile_by_level[risk_level]
    zone = "Konservatif" if risk_level <= 4 else "Moderat" if risk_level <= 7 else "Agresif"
    st.markdown(ui.alloc_bar(all_profiles[chosen_key], mode), unsafe_allow_html=True)
    st.markdown(f"**{RISK_TITLE} {ui.fmt_level(risk_level)}** · {zone}  \n{alloc_text(all_profiles[chosen_key])}")
    st.caption("Skala Bibit: 1 paling konservatif sampai 10 paling agresif.")

    st.markdown(ui.side_title("+", "Pengaturan lanjutan", "Boleh dibiarkan; sudah berisi nilai awal yang masuk akal."), unsafe_allow_html=True)
    with st.expander("Asumsi proyeksi: return dan inflasi"):
        st.caption("Dipakai untuk menghitung proyeksi nilai akhir. Ini asumsi, bukan ramalan.")
        scen_default = pd.DataFrame(recommend.DEFAULT_SCENARIOS).T[["pasar_uang", "pendapatan_tetap", "saham"]] * 100
        scen_edit = st.data_editor(
            scen_default.round(1), key="scenario_editor", width="stretch",
            column_config={c: st.column_config.NumberColumn(ui.CATEGORY_NAMES[c], format="%.1f", min_value=-20.0, max_value=30.0)
                           for c in scen_default.columns},
        )
        st.caption("Return per tahun (%) tiap jenis aset pada skenario Pesimis, Dasar, dan Optimis.")
        inflation = st.slider("Asumsi inflasi per tahun (%)", 0.0, 10.0, 3.0, 0.5,
                              help="Dipakai untuk menghitung nilai akhir dalam daya beli hari ini.") / 100

    strict_rule = st.toggle(
        "Aturan konservatif (disarankan)", value=True, key="strict_rule",
        help="Pilih otomatis hanya bila tahun buruk (data), krisis berat (asumsi Anda), dan skenario terpisah terburuk semuanya "
             "berada di bawah batas dengan ruang minimal 1 poin. Dimatikan: hanya tahun buruk dari data yang diperiksa, "
             "tanpa syarat ruang.")
    with st.expander("Skenario krisis (uji risiko)"):
        st.caption("Dipakai untuk bar 'Krisis berat' di tab Rekomendasi. Ini asumsi, bukan data: data produk hanya mencakup "
                   "1 tahun terakhir, sehingga krisis yang lebih dalam belum terlihat di sana.")
        crisis_saham = st.slider("Saham turun (%)", 10, 70, 40, 5, key="crisis_saham", help="Contoh kasar: pasar saham turun 35-50% di krisis besar.")
        crisis_obl = st.slider("Obligasi turun (%)", 0, 25, 8, 1, key="crisis_obl", help="Obligasi turun saat suku bunga naik cepat atau penerbit bermasalah.")
        crisis_pu = st.slider("Pasar uang turun (%)", 0, 5, 0, 1, key="crisis_pu")
        st.caption("Reksa dana campuran dihitung 60% saham dan 40% obligasi; SBN bergerak seperti obligasi.")
    crisis = metrics.crisis_shocks(crisis_saham, crisis_obl, crisis_pu)

    with st.expander("Dana darurat (untuk tab Portofolio)"):
        st.caption("Dipakai untuk memeriksa apakah dana darurat Anda sudah cukup di portofolio. Boleh dikosongkan.")
        expense = st.number_input("Pengeluaran bulanan (Rp)", 0, 1_000_000_000, 0, 500_000,
                                  help="Total kebutuhan hidup per bulan. Isi 0 untuk melewati pemeriksaan dana darurat.")
        ef_months = st.number_input("Target dana darurat (bulan)", 1, 24, 6,
                                    help="Umumnya 6 bulan pengeluaran; 3 bulan bila penghasilan sangat stabil, 12 bulan bila tidak.")

    st.markdown(ui.side_title("↻", "Data produk", "Harga dan return produk berasal dari snapshot halaman Bibit."), unsafe_allow_html=True)
    st.markdown(ui.data_status(data_date, data_age), unsafe_allow_html=True)
    if CLOUD:
        with st.expander("Cara memperbarui data produk"):
            st.markdown(REFRESH_HOWTO)
    elif st.button(
        "Perbarui data produk", icon=":material/sync:", width="stretch",
        help="Membuka jendela Edge sekitar 1 menit untuk membaca halaman produk Bibit, lalu menutupnya. "
             "Data lama diarsipkan di data/archive. Cukup seminggu sekali.",
    ):
        confirm_refresh(data_date)
    if st.button("Isi rekomendasi robo", icon=":material/smart_toy:", width="stretch",
                 help="Catat produk yang direkomendasikan robo Bibit untuk profil risiko Anda. Isi setiap kali data produk diperbarui."):
        robo_dialog(chosen_key)
    refresh_result = st.session_state.pop("refresh_result", None)
    if refresh_result:  # a toast leaves on its own; a success box in the sidebar used to stay until the browser was reloaded
        ok, detail = refresh_result
        st.toast(detail, icon=":material/check_circle:" if ok else ":material/error:", duration=15 if ok else "infinite")

    st.caption(f"Data pribadi (portofolio, rekomendasi tersimpan) disimpan di: {storage.describe()}.")
    summary_slot.markdown(ui.side_summary(risk_level, zone, budget, horizon, max_drop_pct, syariah_only), unsafe_allow_html=True)

if st.session_state.get("robo_saved"):
    st.toast(st.session_state.pop("robo_saved"), icon=":material/check_circle:")
if st.session_state.pop("robo_prompt", False):
    robo_dialog(chosen_key)

# ----------------------------------------------------------------------------- shared computations
if is_auto:
    rec = auto_rec
else:
    rec = recommend.for_level(catalog, all_profiles, chosen_key, float(budget), syariah_only, max_drop_pct / 100, crisis=crisis)
    if rec.level > recommend.horizon_level_cap(horizon):
        rec.notes.append(
            f"{RISK_TITLE} {ui.fmt_level(rec.level)} di atas batas umum untuk tujuan {horizon:g} tahun "
            f"(maks {ui.fmt_level(recommend.horizon_level_cap(horizon))})."
        )
holdings, tx = portfolio_io.read_current()
tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
rec = portfolio_plan.apply(rec, holdings, float(budget), max_drop_pct / 100)  # fit the deposit to what is already held
plan = rec.plan
profile = rules.Profile(level_key=rec.profile_key, horizon_years=horizon, monthly_expense=expense,
                        emergency_fund_months_target=ef_months)

rates = {name: (row / 100).to_dict() for name, row in scen_edit.iterrows()}
# Long-run mix is the risk level's own target; the existing portfolio is the starting balance of the projection.
scen_rate = {name: metrics.blended_rate(rec.target_allocation, r) for name, r in rates.items()}
initial_value = plan.total_now


def proj_fv(rate: float, years: float) -> float:
    return metrics.future_value_dca(budget, rate, years, initial=initial_value)


level_values = [recommend.level_of(k) for k in level_keys]
level_losses = [metrics.stress_loss(all_profiles[k], rec.shocks) for k in level_keys]
default_fv = proj_fv(scen_rate[SCENARIO_KEY], horizon)


def load(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(DATA / name, **kw)



# ----------------------------------------------------------------------------- header
st.markdown(ui.hero(
    "Kompas Investasi",
    "Rekomendasi produk Bibit sesuai profil risiko, batas penurunan, dan tujuan Anda.",
    [f"Data produk per {data_date}", f"{len(catalog)} reksa dana", f"{RISK_TITLE} {ui.fmt_level(rec.level)} · {profile_name(rec.profile_key)}",
     f"Tujuan {horizon:g} tahun"],
), unsafe_allow_html=True)
st.markdown('<div class="it-mobilehint">Ubah dana, tujuan, dan profil risiko lewat tombol <b>&raquo;</b> di kiri atas.</div>',
            unsafe_allow_html=True)
st.markdown('<div class="it-fine">Rekomendasi berdasarkan data produk Bibit dan perhitungan sistem. '
            "Hasil di masa depan tidak dapat dijamin: nilai reksa dana bisa naik maupun turun.</div>", unsafe_allow_html=True)

tab_rec, tab_port, tab_risk, tab_prod, tab_gov, tab_help = st.tabs([
    ":material/auto_awesome: Rekomendasi", ":material/account_balance_wallet: Portofolio", f":material/speed: {RISK_TITLE}",
    ":material/bar_chart: Reksa dana", ":material/account_balance: SBN, FR & Saham",
    ":material/menu_book: Istilah",
])

# ----------------------------------------------------------------------------- Rekomendasi
with tab_rec:
    for note in rec.notes:
        st.warning(note)

    # severe-crisis loss of what will actually be held: the whole portfolio after this month's deposit, else the recommended mix
    crisis_loss = portfolio_plan.stress(plan.after, crisis) if plan.has_portfolio else metrics.stress_loss(rec.allocation, crisis)
    k1, k2, k3, k4 = st.columns(4, gap="medium")
    k1.markdown(ui.kpi(RISK_TITLE, ui.fmt_level(rec.level), alloc_text(rec.target_allocation), profile_name(rec.profile_key)),
                unsafe_allow_html=True)
    k2.markdown(ui.kpi("Perkiraan turun total portofolio" if plan.has_portfolio else "Perkiraan turun di tahun buruk",
                       ui.fmt_pct(rec.stress_loss * 100),
                       f"batas Anda -{max_drop_pct}% · krisis berat {ui.fmt_pct(crisis_loss * 100)}"), unsafe_allow_html=True)
    k3.markdown(ui.kpi("Dana per bulan", ui.fmt_idr_short(budget), f"{ui.fmt_idr_short(budget * 12 * horizon)} selama {horizon:g} tahun"),
                unsafe_allow_html=True)
    k4.markdown(ui.kpi(f"Proyeksi {horizon:g} tahun ({SCENARIO_KEY})", ui.fmt_idr_short(default_fv),
                       f"daya beli sekarang {ui.fmt_idr_short(metrics.deflate(default_fv, inflation, horizon))}"),
                unsafe_allow_html=True)

    st.markdown(ui.section(
        "Pembagian dana dan batas risiko",
        "Setoran bulan ini diarahkan ke jenis yang masih di bawah target portofolio Anda, dan seberapa jauh total portofolio bisa turun."
        if plan.has_portfolio else
        "Ke mana dana tiap bulan dibagi, dan seberapa jauh profil ini bisa turun di tahun yang buruk."),
        unsafe_allow_html=True)
    left, right = st.columns([5, 6], gap="medium")
    with left, st.container(border=True):
        st.plotly_chart(ui.donut(rec.allocation, ui.fmt_idr_short(budget), "per bulan", mode), width="stretch",
                        config={"displayModeBar": False})
        st.markdown(ui.legend_rows(rec.allocation, rec.monthly_amounts, mode), unsafe_allow_html=True)
    with right, st.container(border=True):
        st.markdown(f"**Posisi di skala {RISK_TITLE.lower()} Bibit**")
        st.markdown(ui.profile_scale(level_values, level_losses, max_drop_pct / 100, rec.level), unsafe_allow_html=True)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown(ui.risk_meter(rec.stress_loss, max_drop_pct / 100, mode, crisis_loss), unsafe_allow_html=True)
        margin_base, margin_label = (plan.total_now + budget, "nilai portofolio") if plan.has_portfolio else (budget * 12, "setoran 12 bulan")
        lower_levels = [(lv, ls) for lv, ls in zip(level_values, level_losses) if lv < rec.level]
        margin_text, margin_warn = ui.margin_note(rec.stress_loss, max_drop_pct / 100, margin_base, margin_label, rec.level,
                                                  max(lower_levels) if lower_levels else None)
        (st.warning if margin_warn else st.caption)(margin_text, **({"icon": ":material/warning:"} if margin_warn else {}))
        if rec.checks:
            with st.expander("Apakah level ini benar-benar memenuhi batas Anda? Pemeriksaan satu per satu"):
                for c in rec.checks:
                    tag = "melewati batas" if c["crossed"] else "ruang tipis (dianggap belum memenuhi)" if c["thin"] else "ada ruang"
                    st.markdown(f"- **{c['name']}** ({c['kind']}): {ui.fmt_pct(c['loss'] * 100)}, ruang {c['margin_points']:+.2f} poin, {tag}")
                st.caption("Level dianggap memenuhi batas hanya bila semua pemeriksaan lolos dengan ruang minimal "
                           f"{metrics.MARGIN_THIN * 100:g} poin. Ketiganya adalah sudut pandang berbeda pada risiko yang sama dan "
                           "tidak dijumlahkan. Semuanya simulasi, bukan batas kerugian aktual.")
        with st.expander("Empat angka yang sering tertukar"):
            st.markdown(
                "1. **Penurunan historis terdalam**: seberapa dalam harga satu dana pernah turun dalam 1 tahun terakhir. Fakta masa lalu, "
                "hanya 1 tahun.\n"
                "2. **Estimasi kerugian kondisi buruk**: gabungan penurunan historis dana-dana pilihan sesuai porsi alokasi (bar 'Tahun buruk'). "
                "Perkiraan dari data, bukan ramalan.\n"
                "3. **Stress test hipotetis**: kerugian bila saham/obligasi turun sebesar angka yang diasumsikan (bar 'Krisis berat' dan "
                "skenario terpisah). Angkanya asumsi, bukan data.\n"
                "4. **Toleransi kerugian Anda**: batas yang Anda pilih di sidebar. Itu preferensi Anda, **bukan jaminan** kerugian tidak "
                "akan lebih besar. Kerugian nyata bisa melewati semua angka di atas.")
        with st.expander("Bandingkan level di sekitarnya (asumsi sama)"):
            cmp_levels = sorted({3.5, 4.0, 4.5, rec.level})
            cmp_rows = recommend.compare_levels(catalog, all_profiles, cmp_levels, max_drop_pct / 100, crisis, rates, float(budget),
                                                horizon, syariah_only)
            st.markdown(ui.level_compare(cmp_rows, margin_base, margin_label, max_drop_pct / 100, rec.level), unsafe_allow_html=True)
        if -crisis_loss > max_drop_pct / 100:
            st.warning(f"Bila krisis berat terjadi, perkiraan turun bisa mencapai {ui.fmt_pct(-crisis_loss * 100)} "
                       f"dan melewati batas {max_drop_pct}% Anda. Pertimbangkan profil yang lebih konservatif, atau pastikan Anda "
                       "tidak menjual saat turun. Asumsi krisis bisa diubah di sidebar.", icon=":material/warning:")
        held = plan.after if plan.has_portfolio else rec.allocation
        with st.expander("Bagaimana kalau krisisnya lebih ringan atau lebih berat?"):
            st.markdown(ui.crisis_grid(metrics.crisis_grid(held, pasar_uang_pct=crisis_pu), metrics.CRISIS_GRID_SAHAM,
                                       metrics.CRISIS_GRID_OBLIGASI, max_drop_pct / 100), unsafe_allow_html=True)
            st.caption("Angka-angka ini asumsi, bukan ramalan. Dipakai untuk melihat seberapa sensitif komposisi Anda terhadap "
                       "dua hal: turunnya saham dan turunnya obligasi.")
        with st.expander("Skenario terpisah: apa yang bisa salah, satu per satu"):
            bond_pick = rec.picks.get("pendapatan_tetap")
            gov = bond_pick.iloc[0].get("gov_top10_pct") if bond_pick is not None and len(bond_pick) else None
            gov = None if gov is None or pd.isna(gov) else gov / 100
            base, base_label = (plan.total_now + budget, "nilai portofolio setelah setoran bulan ini") if plan.has_portfolio                 else (budget * 12, "setoran 12 bulan")
            if gov is not None:
                st.markdown(ui.scenario_table(metrics.scenario_losses(held, gov), base, base_label, max_drop_pct / 100),
                            unsafe_allow_html=True)
                st.caption(f"Porsi obligasi negara {gov:.0%} dihitung dari 10 besar isi dana pendapatan tetap pilihan utama, bukan "
                           "seluruh dana. Ini simulasi dengan asumsi, bukan batas kerugian maksimum dan bukan jaminan aman.")
            else:
                st.markdown(ui.scenario_table(metrics.scenario_range(held), base, base_label, max_drop_pct / 100,
                                              verified=False, exposures=metrics.CORPORATE_EXPOSURES), unsafe_allow_html=True)
                st.caption("Ini simulasi dengan asumsi, bukan batas kerugian maksimum dan bukan jaminan aman. "
                           "Cek fund fact sheet dana pendapatan tetap sebelum membeli.")
        st.caption("Tahun buruk dihitung dari data 1 tahun terakhir; krisis berat adalah asumsi. Dari fund fact sheet, sistem "
                   "hanya membaca porsi obligasi negara di 10 besar isi dana pendapatan tetap; rating penerbit dan durasi belum terbaca, jadi cek fund fact sheet.")
        if plan.has_portfolio:
            st.caption(f"Dihitung untuk seluruh portofolio setelah setoran bulan ini (nilai sekarang {ui.fmt_idr_short(plan.total_now)}). "
                       f"Sebelum setoran: {ui.fmt_pct(plan.stress_now * 100)}.")
        if is_auto and rec.within_limit:
            st.caption(f"Ini {RISK_TITLE.lower()} tertinggi yang lolos semua pemeriksaan simulasi terhadap batas {max_drop_pct}% dan tujuan "
                       f"{horizon:g} tahun. Lolos simulasi bukan jaminan kerugian tidak akan melewati {max_drop_pct}%.")
        if rec.level in (4.5, 5.0):
            st.caption("Komposisi sudah dicocokkan dengan screenshot robo Bibit.")
        else:
            st.caption("Komposisi dari catatan Anda, belum dicocokkan dengan aplikasi Bibit. Cek di aplikasi sebelum membeli.")

    if plan.has_portfolio:
        st.markdown(ui.section("Dari portofolio Anda menuju target",
                               "Rekomendasi sudah memperhitungkan isi portofolio. Tidak ada yang perlu dijual: setoran bulanan menutup selisihnya."),
                    unsafe_allow_html=True)
        plan_rows = []
        for cat in dict.fromkeys([*plan.target, *plan.current]):
            plan_rows.append({
                "Jenis": ui.CATEGORY_NAMES.get(cat, cat), "Sekarang": f"{plan.share_now(cat):.0%}",
                "Target": f"{plan.target.get(cat, 0):.0%}", "Setoran bulan ini": ui.fmt_idr(plan.contribution.get(cat, 0)),
                "Setelah setoran": f"{plan.share_after(cat):.0%}",
                "Status": ("Di bawah target, diisi dulu" if plan.contribution.get(cat, 0) > 0 and plan.share_now(cat) < plan.target.get(cat, 0) - 0.02
                           else "Sesuai target" if abs(plan.share_now(cat) - plan.target.get(cat, 0)) <= 0.05
                           else "Di atas target, tidak ditambah" if plan.contribution.get(cat, 0) == 0 else "Setoran sesuai porsi target"),
            })
        st.dataframe(pd.DataFrame(plan_rows), hide_index=True, width="stretch")
        if plan.months_to_target:
            st.caption(f"Dengan setoran {ui.fmt_idr_short(budget)} per bulan, komposisi mendekati target (selisih di bawah 5 poin) "
                       f"sekitar {plan.months_to_target} bulan lagi, belum menghitung kenaikan atau penurunan harga.")
        else:
            st.caption("Komposisi portofolio Anda sudah dekat dengan target; setoran mengikuti porsi target.")
    else:
        st.caption("Portofolio masih kosong, jadi pembagian dana mengikuti komposisi profil penuh. "
                   "Setelah Anda mencatat isi di tab Portofolio (form, unggah CSV, atau edit tabel), rekomendasi menyesuaikan diri.")

    st.markdown(ui.section("Produk pilihan", "Satu pilihan utama per jenis, lengkap dengan alternatif peringkat berikutnya."),
                unsafe_allow_html=True)
    pick_cols = st.columns(max(len(rec.picks), 1), gap="medium")
    for col, (cat, picks_df) in zip(pick_cols, rec.picks.items()):
        col.markdown(ui.product_card(cat, rec.allocation[cat], rec.monthly_amounts[cat], picks_df.to_dict("records"), mode),
                     unsafe_allow_html=True)

    with st.expander("Bagaimana skor produk dihitung (per kriteria, bobot, dan sumber data)"):
        st.caption("Skor ini menilai KUALITAS PRODUK dibanding produk sejenis (persentil 0-1, makin tinggi makin baik). "
                   "Risiko portofolio dihitung terpisah lewat uji penurunan dan skenario di atas. Peringkat yang stabil terhadap perubahan "
                   "bobot hanya berarti urutannya tidak rapuh, bukan bukti bahwa produknya aman.")
        for cat, picks_df in rec.picks.items():
            top_name = picks_df.iloc[0]["name"]
            ranked_all = recommend.rank_category(catalog, cat, syariah_only)
            br = recommend.score_breakdown(ranked_all, cat, top_name)
            st.markdown(f"**{ui.CATEGORY_NAMES.get(cat, cat)}: {top_name}** (skor {picks_df.iloc[0]['score']:.1f} dari 100)")
            st.dataframe(br, hide_index=True, width="stretch")

    st.markdown(ui.section("Pilihan sistem vs robo Bibit",
                           "Kinerja masa lalu satu produk per jenis dengan porsi yang sama (kasar). Bukan jaminan."),
                unsafe_allow_html=True)
    robo_names, robo_meta = robo.resolve(rec.level, robo.load())
    robo_picks = robo.fund_rows(robo_names, catalog)
    ours_picks = {cat: df.iloc[0] for cat, df in rec.picks.items()}
    robo_alloc = all_profiles.get(rec.profile_key, rec.allocation)
    cmp = {"Pilihan sistem": recommend.history_compare(rec.allocation, ours_picks),
           "Robo Bibit": recommend.history_compare(robo_alloc, robo_picks)}
    cc1, cc2 = st.columns([3, 2], gap="medium")
    with cc1, st.container(border=True):
        st.plotly_chart(ui.compare_chart(cmp, mode), width="stretch", config={"displayModeBar": False})
        st.caption("Cara membandingkan: rata-rata tertimbang return kumulatif satu produk per jenis, dengan porsi yang sama "
                   "(komposisi profil Bibit) dan periode serta tanggal data yang sama. Return berbasis NAV, jadi sudah setelah "
                   "biaya pengelolaan. Bukan simulasi setoran bulanan, tanpa rebalancing, dan tanpa biaya transaksi. "
                   "Bobotnya sama; yang berbeda hanya produknya.")
    with cc2, st.container(border=True):
        st.markdown("**Pilihan sistem**")
        for p in ours_picks.values():
            st.markdown(f"- {p['name']}")
        st.markdown(f"**Robo Bibit** (profil {ui.fmt_level(rec.level)})")
        for cat, name in robo_names.items():
            st.markdown(f"- {name}" + ("" if cat in robo_picks else "  \n  :red[tidak ada di katalog]"))
        if robo_meta["source"] == "input":
            st.caption(f"Diisi {robo_meta['saved_at'].replace('T', ' ')} untuk data produk per {robo_meta['data_as_of']}.")
        elif robo_meta["source"] == "screenshot":
            st.caption("Dari screenshot robo Anda; belum pernah diisi ulang setelah data diperbarui.")
        else:
            st.caption("Perkiraan: komposisi robo untuk profil ini belum pernah Anda isi dan belum dicocokkan dengan aplikasi Bibit.")
        if st.button("Isi rekomendasi robo", icon=":material/smart_toy:", key="robo_btn_cmp", width="stretch"):
            robo_dialog(rec.profile_key)
    if robo.is_stale(robo_meta, data_date):
        st.warning(f"Data produk sudah diperbarui ({data_date}) sejak rekomendasi robo terakhir diisi "
                   f"({robo_meta['data_as_of']}). Robo bisa saja mengganti produknya; cocokkan lagi di aplikasi Bibit.")
    if robo.missing_from(robo_names, catalog):
        st.warning("Ada produk robo yang tidak ada lagi di katalog: " + ", ".join(robo.missing_from(robo_names, catalog))
                   + ". Isi ulang rekomendasi robo.")

    st.markdown(ui.section("Proyeksi hasil dari dana per bulan",
                           "Skenario 'bagaimana kalau' dengan asumsi return tetap. Pakai skenario rekomendasi, atau atur sendiri "
                           "setoran, lama, dan return untuk mencoba angka lain."),
                unsafe_allow_html=True)
    MODE_REC, MODE_OWN = "Skenario rekomendasi", "Atur sendiri"
    proj_mode = st.segmented_control(
        "Mode", [MODE_REC, MODE_OWN], default=MODE_REC, key="proj_mode",
        help="Skenario rekomendasi: return diturunkan dari komposisi rekomendasi (asumsi di sidebar, Asumsi proyeksi). "
             "Atur sendiri: Anda menentukan setoran, lama, dan return; cocok untuk mencoba angka lain.") or MODE_REC
    if proj_mode == MODE_OWN:
        o1, o2, o3, o4 = st.columns(4, gap="medium")
        p_budget = float(o1.number_input("Setoran per bulan (Rp)", 0, 1_000_000_000, int(budget), 100_000))
        p_years = int(o2.number_input("Lama (tahun)", 1, 40, min(max(int(round(horizon)), 1), 40)))
        own_rate = o3.slider("Asumsi return per tahun (%)", 0.0, 20.0, round(scen_rate[SCENARIO_KEY] * 200) / 2, 0.5) / 100
        p_infl = o4.slider("Asumsi inflasi per tahun (%)", 0.0, 10.0, float(inflation * 100), 0.5) / 100
        p_initial = initial_value if plan.has_portfolio and st.checkbox(
            f"Sertakan portofolio sekarang ({ui.fmt_idr_short(initial_value)}) sebagai saldo awal", value=True) else 0.0
        scenario, proj_rates = "Atur sendiri", {"Atur sendiri": own_rate}
    else:
        p_budget, p_years, p_initial, proj_rates, p_infl = float(budget), horizon, initial_value, scen_rate, inflation
        scenario = st.segmented_control(
            "Skenario", list(rates), default=SCENARIO_KEY, key="scenario_pick",
            help="Pesimis = kondisi kurang bagus (saham impas). Dasar = kondisi biasa. Optimis = kondisi cukup baik. "
                 "Ketiganya asumsi, bukan ramalan.",
        ) or SCENARIO_KEY

    def fv_at(r: float, y: float) -> float:
        return metrics.future_value_dca(p_budget, r, y, initial=p_initial)

    rate = proj_rates[scenario]
    fv_end = fv_at(rate, p_years)
    deposits_end = p_budget * 12 * p_years
    p1, p2, p3, p4 = st.columns(4, gap="medium")
    p1.markdown(ui.kpi("Return portofolio / tahun", ui.fmt_pct(rate * 100), f"skenario {scenario}"), unsafe_allow_html=True)
    p2.markdown(ui.kpi(f"Total setoran {p_years:g} tahun", ui.fmt_idr_short(deposits_end),
                       f"+ saldo awal {ui.fmt_idr_short(p_initial)}" if p_initial else ""), unsafe_allow_html=True)
    p3.markdown(ui.kpi("Nilai akhir", ui.fmt_idr_short(fv_end), "nominal"), unsafe_allow_html=True)
    p4.markdown(ui.kpi("Nilai akhir (daya beli sekarang)", ui.fmt_idr_short(metrics.deflate(fv_end, p_infl, p_years)),
                       f"inflasi {p_infl:.1%} per tahun" + ("" if proj_mode == MODE_OWN else " (ubah di sidebar)")), unsafe_allow_html=True)
    years = list(range(0, int(p_years) + 1))
    series = {n: [fv_at(r, y) / 1e6 for y in years] for n, r in proj_rates.items()}
    real_sel = [metrics.deflate(fv_at(rate, y), p_infl, y) / 1e6 for y in years]
    with st.container(border=True):
        st.plotly_chart(ui.projection_chart(years, series, [(p_initial + p_budget * 12 * y) / 1e6 for y in years], real_sel,
                                            scenario, mode), width="stretch", config={"displayModeBar": False})
        if proj_mode == MODE_REC:
            st.caption(
                "**Pesimis**: kondisi kurang bagus jangka panjang, batas bawah perencanaan. **Dasar**: kondisi biasa. "
                "**Optimis**: kondisi cukup baik. Tips: jadikan Pesimis sebagai rencana; kalau target tercapai di situ, rencananya tangguh.")
        else:
            st.caption("Angka di atas memakai return tetap yang Anda tentukan; kenyataannya naik-turun tiap tahun. "
                       "Coba juga return rendah (misalnya 3-4%) untuk melihat batas bawahnya.")
    with st.expander("Lihat angkanya (tabel)"):
        st.dataframe(pd.DataFrame([{
            "Tahun": y, "Total setoran": ui.fmt_idr(p_budget * 12 * y),
            "Hasil investasi": ui.fmt_idr(fv_at(rate, y) - p_budget * 12 * y - p_initial),
            "Nilai akhir": ui.fmt_idr(fv_at(rate, y)),
            "Daya beli sekarang": ui.fmt_idr(metrics.deflate(fv_at(rate, y), p_infl, y)),
        } for y in sorted({y for y in (1, 3, 5, 10, int(p_years)) if y <= p_years})]), hide_index=True, width="stretch")

    st.markdown(ui.section("Cara memulai (bertahap)", "Setoran bertahap mengurangi risiko seluruh dana masuk di waktu yang kurang tepat."),
                unsafe_allow_html=True)
    for col, card in zip(st.columns(3, gap="medium"), ui.step_cards(recommend.start_plan(float(budget)))):
        col.markdown(card, unsafe_allow_html=True)

    st.markdown(ui.section("Simpan rekomendasi", "Catat rekomendasi hari ini untuk dibandingkan setelah data produk diperbarui."),
                unsafe_allow_html=True)
    note = st.text_input("Catatan (opsional)", placeholder="mis. mulai setor bulan depan", key="rec_note")
    snap_now = history.snapshot(
        rec,
        {"horizon_years": horizon, "monthly_budget": float(budget), "max_drop_pct": max_drop_pct,
         "syariah_only": syariah_only, "auto": is_auto},
        data_date, note, projection={"inflation": inflation, "rates": scen_rate},
        portfolio=portfolio_plan.snapshot_block(plan), crisis={"loss": crisis_loss, "shocks": crisis},
    )
    b_save, b_pdf, _ = st.columns([2, 2, 3], gap="small")
    if b_save.button("Simpan rekomendasi hari ini", icon=":material/bookmark_add:", width="stretch"):
        saved_path = history.save(snap_now)
        st.success(f"Tersimpan di data/recommendations/{saved_path.name}")
    b_pdf.download_button(
        "Unduh laporan (PDF)", data=lambda: report.build_pdf(snap_now, current=True),
        file_name=report.filename(snap_now, current=True), mime="application/pdf", icon=":material/picture_as_pdf:",
        width="stretch", key="pdf_current", help="Laporan rekomendasi saat ini, belum perlu disimpan.",
    )

    saved = history.list_saved()
    with st.expander(f"Riwayat rekomendasi ({len(saved)} tersimpan)", expanded=bool(saved)):
        if not saved:
            st.write("Belum ada rekomendasi yang disimpan.")
        else:
            st.dataframe(pd.DataFrame([{
                "Disimpan": s["saved_at"].replace("T", " "), "Data per": s["data_as_of"],
                RISK_TITLE: f"{ui.fmt_level(s['profile']['level'])} ({s['profile']['name']})",
                "Produk utama": " | ".join(p[0]["name"] for p in s["picks"].values() if p),
                "Catatan": s["note"],
            } for s in saved]), hide_index=True, width="stretch")
            labels = {s["_file"]: f"{s['saved_at'].replace('T', ' ')} · {RISK_TITLE.lower()} {ui.fmt_level(s['profile']['level'])}" for s in saved}
            chosen_file = st.selectbox("Bandingkan dengan rekomendasi sekarang", list(labels), format_func=labels.get)
            old_snap = next(s for s in saved if s["_file"] == chosen_file)
            st.download_button(
                "Unduh laporan tersimpan (PDF)", data=lambda: report.build_pdf(old_snap), file_name=report.filename(old_snap),
                mime="application/pdf", icon=":material/picture_as_pdf:", key="pdf_saved",
                help="Laporan dari rekomendasi tersimpan yang dipilih di atas.",
            )
            diff_rows = history.compare(old_snap, snap_now, catalog)
            for line in history.describe_changes(old_snap, snap_now, diff_rows):
                st.markdown(f"- {line}")
            st.dataframe(
                pd.DataFrame(diff_rows).rename(columns={
                    "kategori": "Kategori", "produk_utama_lama": "Produk utama (tersimpan)",
                    "produk_utama_sekarang": "Produk utama (sekarang)", "status": "Status",
                    "peringkat_lama_sekarang": "Peringkat produk lama kini", "masih_dijual": "Masih dijual"}),
                hide_index=True, width="stretch",
            )

    with st.expander("Cara sistem memilih (kriteria dan batasan)"):
        st.markdown(
            f"- **{RISK_TITLE}**: yang tertinggi dengan perkiraan penurunan di bawah batas Anda, dan tidak melebihi batas horizon "
            "(< 3 tahun maks 3, < 5 tahun maks 5).\n"
            f"- **Saringan produk**: bukan USD/dolar, dana kelolaan minimal Rp{recommend.MIN_AUM_IDR/1e9:.0f} miliar, "
            "punya riwayat 3 tahun (kecuali pasar uang).\n"
            "- **Peringkat**: persentil dalam kategori. Pasar uang: return 1 tahun, ukuran dana, penurunan kecil. "
            "Obligasi: return 3 tahun per risiko turun, penurunan kecil, ukuran. Saham: berbasis indeks, penurunan kecil, ukuran, return 3 tahun.\n"
            "- **Tidak ada** produk yang dipilih hanya karena return tertingginya tahun lalu.\n"
            "- **Uji risiko**: dua angka. *Tahun buruk* memakai penurunan terdalam 1 tahun terakhir dari data. *Krisis berat* memakai "
            "asumsi yang bisa Anda ubah (default saham -40%, obligasi -8%), karena data 1 tahun tidak memuat krisis besar.\n"
            "- **Keterbatasan**: data hanya snapshot; drawdown hanya mencakup 1 tahun terakhir; sistem tidak membaca prospektus "
            "(isi portofolio, biaya, expense ratio, durasi dan kualitas penerbit obligasi), dan klasifikasi jenis mengikuti Bibit. "
            "Cek halaman produk sebelum membeli."
        )

# ----------------------------------------------------------------------------- Portofolio
with tab_port:
    portfolio_forms.render(catalog, expanded=holdings.empty)
    if holdings.empty:
        st.markdown(ui.empty_state(
            "Belum ada investasi yang dicatat",
            "Setelah Anda membeli produk di Bibit, catat lewat panel di atas (form, unggah CSV, atau edit tabel) dan analisis portofolio akan muncul di sini.",
            ["data/transactions.csv  (tanggal, produk, jenis, BUY/SELL, nominal)", "data/holdings.csv  (produk, jenis, nilai sekarang)"]),
            unsafe_allow_html=True)
        st.caption("Format lengkap ada di data/README.md.")
    else:
        current = float(holdings["current_value"].sum())
        invested = metrics.total_invested(tx)
        irr = metrics.portfolio_xirr(tx, current, TODAY)
        a1, a2, a3, a4 = st.columns(4, gap="medium")
        a1.markdown(ui.kpi("Nilai sekarang", ui.fmt_idr_short(current)), unsafe_allow_html=True)
        a2.markdown(ui.kpi("Total modal bersih", ui.fmt_idr_short(invested)), unsafe_allow_html=True)
        a3.markdown(ui.kpi("Untung / rugi", ui.fmt_idr_short(current - invested), ui.fmt_pct((current / invested - 1) * 100, 1, True) if invested else ""),
                    unsafe_allow_html=True)
        a4.markdown(ui.kpi("XIRR per tahun", ui.fmt_pct(irr * 100) if irr is not None else "n/a", "kurang andal bila data < 3 bulan"),
                    unsafe_allow_html=True)
        by_cat = metrics.allocation_by(holdings, "category").to_dict()
        pl, pr = st.columns(2, gap="medium")
        with pl, st.container(border=True):
            st.markdown("**Alokasi saat ini**")
            st.plotly_chart(ui.donut(by_cat, ui.fmt_idr_short(current), "nilai sekarang", mode), width="stretch", config={"displayModeBar": False})
        with pr, st.container(border=True):
            st.markdown(f"**Acuan {RISK_TITLE.lower()} {level_label(rec.profile_key)}**")
            target = rules.target_allocation(profile)
            st.plotly_chart(ui.donut(target, "Acuan", level_label(rec.profile_key), mode), width="stretch", config={"displayModeBar": False})
        st.markdown(ui.section("Pengamatan"), unsafe_allow_html=True)
        for f in rules.evaluate(profile, tx, holdings, TODAY):
            {"penting": st.error, "perhatian": st.warning, "info": st.info}[f.level](f"**{f.title}** — {f.detail}")

# ----------------------------------------------------------------------------- Profil risiko
with tab_risk:
    st.markdown(ui.section(f"Semua {RISK_TITLE.lower()} Bibit (1–10)",
                           f"Perkiraan turun tiap profil di tahun buruk, dibandingkan dengan batas Anda ({max_drop_pct}%, diatur di sidebar). "
                           "Skenario hipotetis: semua jenis aset turun bersamaan."), unsafe_allow_html=True)
    max_drop = max_drop_pct / 100
    src_rec, src_robo, src_manual = "Sama dengan rekomendasi", "Produk robo Bibit", "Asumsi manual"
    src_crisis = "Krisis berat (asumsi)"
    source = st.segmented_control(
        "Asumsi penurunan", [src_rec, src_crisis, src_robo, src_manual], default=src_rec, key="shock_source",
        help="Sama dengan rekomendasi: skenario berat yang dipakai tab Rekomendasi. Produk robo Bibit: penurunan terdalam "
             "1 tahun dari Sucorinvest Money Market Fund, ABF Indonesia Bond Index Fund, dan BNI-AM Indeks IDX30.") or src_rec
    base = dict(metrics.DEFAULT_SHOCKS)
    if source == src_rec:
        base.update(rec.shocks)
        st.caption("Angka yang sama dengan tab Rekomendasi: yang lebih buruk antara produk teratas dan median jenisnya.")
    elif source == src_crisis:
        base.update(crisis)
        st.caption("Skenario krisis dari sidebar (Skenario krisis). Ini asumsi, bukan data; lihat profil mana yang melewati batas Anda.")
    elif source == src_robo:
        base.update(products.robo_shocks(catalog, robo.resolve(recommend.level_of(rec.profile_key), robo.load())[0]))
        st.caption("Penurunan terdalam 1 tahun produk robo Bibit. Tahun buruk berikutnya bisa lebih dalam, "
                   "dan hasilnya bisa sedikit berbeda dari tab Rekomendasi karena produknya berbeda.")
    with st.expander("Asumsi penurunan per jenis aset (bisa diubah)"):
        shocks = {c: st.slider(ui.CATEGORY_NAMES.get(c, c), -60.0, 0.0, round(v * 100, 2), key=f"shock_{c}_{source[:4]}") / 100
                  for c, v in base.items()}
    losses = [metrics.stress_loss(all_profiles[k], shocks) for k in level_keys]
    with st.container(border=True):
        st.plotly_chart(ui.level_chart(level_values, losses, max_drop, rec.level, mode), width="stretch", config={"displayModeBar": False})
        st.caption("Batang biru = masih dalam batas Anda, abu-abu = melewati batas. Garis tebal = profil yang sedang dipilih.")
    with st.expander("Lihat angkanya (tabel)"):
        st.dataframe(pd.DataFrame([{
            RISK_TITLE: level_label(k), "Komposisi": alloc_text(all_profiles[k]),
            "Perkiraan turun": ui.fmt_pct(loss * 100), "Dalam batas": "ya" if -loss <= max_drop else "TIDAK",
            "Dipilih": "◀" if k == rec.profile_key else "",
        } for k, loss in zip(level_keys, losses)]), hide_index=True, width="stretch", height=(len(level_keys) + 1) * 35 + 3)
    st.caption("Hanya profil 4,5 dan 5 yang sudah dicocokkan dengan screenshot Bibit; sisanya dari catatan Anda. "
               "Ubah angkanya di data/risk_profiles.json bila ada yang berbeda dari aplikasi.")

# ----------------------------------------------------------------------------- Reksa dana
with tab_prod:
    st.markdown(ui.section(f"{len(catalog)} reksa dana yang dijual di Bibit",
                           f"Snapshot {data_date}. Return masa lalu tidak menjamin hasil ke depan; urutan di sini bukan rekomendasi."),
                unsafe_allow_html=True)
    f1, f2, f3 = st.columns([3, 2, 2], gap="medium")
    cat_options = sorted(catalog["category"].unique())
    cats = f1.pills("Jenis", cat_options, selection_mode="multi", format_func=lambda c: ui.CATEGORY_NAMES.get(c, c))
    syariah = f2.toggle("Syariah saja (dari nama produk)")
    min_aum = f3.number_input("Dana kelolaan minimum (Rp miliar)", 0, 100_000, 0, 100)
    view = catalog
    if cats:
        view = view[view["category"].isin(cats)]
    if syariah:
        view = view[view["syariah_dari_nama"] == "ya"]
    view = view[view["aum_idr"].fillna(0) >= min_aum * 1e9]
    with st.container(border=True):
        st.plotly_chart(ui.product_scatter(view, [df.iloc[0]["name"] for df in rec.picks.values()], mode), width="stretch",
                        config={"displayModeBar": False})
        st.caption("Makin ke kanan = penurunan terdalam 1 tahun makin kecil; makin ke atas = return 3 tahun makin besar. "
                   "Berlian = pilihan utama sistem.")
    sort_labels = {"drawdown_1y_pct": "Penurunan terkecil", "return_1y_pct": "Return 1 th", "return_3y_pct": "Return 3 th",
                   "aum_idr": "Dana kelolaan", "name": "Nama"}
    sort_by = st.segmented_control("Urutkan", list(sort_labels), format_func=sort_labels.get, default="drawdown_1y_pct",
                                   key="prod_sort") or "drawdown_1y_pct"
    view = view.sort_values(sort_by, ascending=(sort_by == "name"), na_position="last")
    view = view.assign(category=view["category"].map(lambda c: ui.CATEGORY_NAMES.get(c, c)))
    st.dataframe(
        view[["name", "category", "return_1y_pct", "return_3y_pct", "return_5y_pct", "drawdown_1y_pct", "aum_idr", "last_nav", "url"]],
        hide_index=True, width="stretch",
        column_config={
            "name": "Produk", "category": "Jenis",
            "return_1y_pct": st.column_config.NumberColumn("Return 1 th", format="%.2f%%"),
            "return_3y_pct": st.column_config.NumberColumn("Return 3 th", format="%.2f%%"),
            "return_5y_pct": st.column_config.NumberColumn("Return 5 th", format="%.2f%%"),
            "drawdown_1y_pct": st.column_config.NumberColumn("Turun terdalam 1 th", format="%.2f%%"),
            "aum_idr": st.column_config.NumberColumn("Dana kelolaan (Rp)", format="localized"),
            "last_nav": st.column_config.NumberColumn("NAV terakhir", format="%.4f"),
            "url": st.column_config.LinkColumn("Bibit", display_text="buka"),
        },
    )

# ----------------------------------------------------------------------------- SBN, FR & saham
with tab_gov:
    fr_df, sbn_df, inst_df = products.load_fr(), products.load_sbn(), products.load_instruments()
    next_sbn = products.load_next_sbn()
    absent = [n for n, d in (("Obligasi FR", fr_df), ("SBN Ritel", sbn_df), ("jenis instrumen", inst_df)) if d.empty]
    if absent:
        st.warning("Data " + ", ".join(absent) + " belum tersedia, jadi bagian itu dikosongkan. Klik **Perbarui data produk** di sidebar "
                   "untuk mengambilnya.")
    if not fr_df.empty and not inst_df.empty:
        top_fr = fr_df.sort_values("yield_pct", ascending=False).iloc[0]
        g1, g2, g3 = st.columns(3, gap="medium")
        g1.markdown(ui.kpi("Yield Obligasi FR tertinggi", ui.fmt_pct(top_fr["yield_pct"], 2), f"{top_fr['seri']} · jatuh tempo {top_fr['jatuh_tempo']}"),
                    unsafe_allow_html=True)
        g2.markdown(ui.kpi("SBN berikutnya", next_sbn["kode"] if next_sbn else "n/a",
                           f"dibuka {next_sbn['mulai']}" if next_sbn else "klik Perbarui data produk"), unsafe_allow_html=True)
        g3.markdown(ui.kpi("Minimal pembelian", ui.fmt_idr_short(float(inst_df["minimal_beli_idr"].min())), "SBN dan Obligasi FR"),
                    unsafe_allow_html=True)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.info("SBN, Obligasi FR, dan Saham di Bibit memerlukan upgrade ke **Bibit Plus** (menurut halaman produk Bibit). "
            "Data di bawah adalah snapshot, cek ulang di aplikasi sebelum membeli.")

    if not inst_df.empty:
        st.markdown(ui.section("Jenis SBN dan Obligasi FR",
                               "SBN Ritel hanya bisa dibeli saat masa penawaran (pasar perdana). Obligasi FR bisa dijual kapan saja, tapi harganya naik-turun."),
                    unsafe_allow_html=True)
        st.dataframe(inst_df.drop(columns=["as_of"], errors="ignore"), hide_index=True, width="stretch", column_config={
            "kode": "Kode", "nama": "Nama", "jenis": "Jenis", "imbal_hasil": "Imbal hasil", "pencairan": "Pencairan",
            "jangka_waktu": "Jangka waktu", "minimal_beli_idr": st.column_config.NumberColumn("Minimal beli (Rp)", format="localized")})

    if not fr_df.empty:
        st.markdown(ui.section("Obligasi FR yang dijual di Bibit",
                               "Yield = imbal hasil bila dibeli di harga beli dan ditahan sampai jatuh tempo. Selisih harga beli dan jual (spread) adalah biaya Anda."),
                    unsafe_allow_html=True)
        st.dataframe(fr_df.drop(columns=["as_of"], errors="ignore").fillna({"label": ""}), hide_index=True, width="stretch", column_config={
            "seri": "Seri", "tipe": "Tipe", "label": "Label", "yield_pct": st.column_config.NumberColumn("Yield", format="%.2f%%"),
            "kupon_pct": st.column_config.NumberColumn("Kupon", format="%.3f%%"),
            "harga_beli_pct": st.column_config.NumberColumn("Harga beli", format="%.2f%%"),
            "harga_jual_pct": st.column_config.NumberColumn("Harga jual", format="%.2f%%"), "jatuh_tempo": "Jatuh tempo"})

    if not sbn_df.empty:
        st.markdown(ui.section("SBN Ritel yang pernah terbit di Bibit (2026)"), unsafe_allow_html=True)
        st.dataframe(sbn_df.drop(columns=["as_of"], errors="ignore"), hide_index=True, width="stretch", column_config={
            "kode": "Kode", "jenis": "Jenis", "kupon_pct": st.column_config.NumberColumn("Kupon", format="%.2f%%"),
            "periode_pembelian": "Periode pembelian", "jatuh_tempo": "Jatuh tempo"})
    if next_sbn:
        detail = f" ({next_sbn['keterangan']})" if next_sbn.get("keterangan") else ""
        st.caption(f"SBN berikutnya menurut halaman Bibit (data per {next_sbn['as_of']}): {next_sbn['kode']}{detail}, "
                   f"dibuka {next_sbn['mulai']}. Seri lain di atas masa penawarannya sudah lewat.")

    st.markdown(ui.section("Saham"), unsafe_allow_html=True)
    st.write("Saham individu dibeli lewat Bibit Plus (didukung Stockbit Sekuritas). Bibit tidak menampilkan katalog saham di halaman "
             "publiknya, jadi tidak ada daftar saham di sistem ini. Untuk eksposur saham tanpa memilih emiten sendiri, reksa dana "
             "saham/indeks lebih sederhana karena emitennya dipilih manajer investasi.")

# ----------------------------------------------------------------------------- Istilah
with tab_help:
    st.markdown(ui.section("Istilah investasi", f"{len(glossary.all_terms())} istilah dalam bahasa sederhana. Cari kata kunci "
                           "atau pilih topik."), unsafe_allow_html=True)
    q_col, g_col = st.columns([2, 3], gap="medium")
    query = q_col.text_input("Cari istilah", placeholder="mis. obligasi, risiko, NAV", key="glossary_q")
    topic = g_col.pills("Topik", [glossary.ALL, *glossary.GROUPS], default=glossary.ALL, key="glossary_topic") or glossary.ALL
    hits = glossary.search(query, topic)
    if not hits:
        st.info("Tidak ada istilah yang cocok. Coba kata kunci lain atau pilih 'Semua'.")
    else:
        st.caption(f"{len(hits)} istilah ditampilkan.")
    for row in range(0, len(hits), 2):
        for col, (g, t, d, ex) in zip(st.columns(2, gap="medium"), hits[row:row + 2]):
            col.markdown(ui.term_card(t, d, ex, g if topic == glossary.ALL else ""), unsafe_allow_html=True)
            col.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
