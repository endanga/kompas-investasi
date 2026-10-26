"""Presentation layer: number formats, theme colours, HTML components and Plotly charts.

Colour rules (see the dataviz skill): one fixed colour per entity (never by rank) from the validated categorical
palette (slots 1-3 pass the all-pairs gate), one-hue sequential ramp for ordered magnitude, reserved status colours
that always travel with an icon and a label. Components inherit text colour from Streamlit's theme so they work in
both light and dark mode.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------- colours
# Fixed per entity. Slots 1-3 (blue, orange, aqua) of the reference categorical palette, validated all-pairs.
CATEGORY_COLORS = {
    "light": {"pasar_uang": "#1baf7a", "pendapatan_tetap": "#2a78d6", "saham": "#eb6834", "other": "#898781"},
    "dark": {"pasar_uang": "#199e70", "pendapatan_tetap": "#3987e5", "saham": "#d95926", "other": "#898781"},
}
CATEGORY_NAMES = {"pasar_uang": "Pasar uang", "pendapatan_tetap": "Obligasi", "saham": "Saham",
                  "campuran": "Campuran", "sbn": "SBN", "global": "Global", "lainnya": "Lainnya"}
BLUE = {"light": "#2a78d6", "dark": "#3987e5"}
GOOD, CRITICAL = "#0ca30c", "#d03b3b"          # status palette (fixed, always with icon + label)
GOOD_TEXT = {"light": "#006300", "dark": "#0ca30c"}
SEQ_LIGHT, SEQ_DARK = (0x86, 0xB6, 0xEF), (0x18, 0x4F, 0x95)   # blue ramp steps 250 -> 600 (ordinal-safe)


def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # theme not available (older Streamlit, tests)
        return "light"


def ink(mode: str) -> str:
    """Primary text colour for chart marks that must contrast with the surface."""
    return "#f0efec" if mode == "dark" else "#0b0b0b"


def category_color(category: str, mode: str) -> str:
    colors = CATEGORY_COLORS[mode]
    return colors.get(category, colors["other"])


def sequential(i: int, n: int) -> str:
    """i-th of n steps on the one-hue blue ramp, light to dark."""
    t = 0 if n <= 1 else i / (n - 1)
    return "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(SEQ_LIGHT, SEQ_DARK))


# ----------------------------------------------------------------------------- number formats (Indonesian)
def _trim(value: float, decimals: int = 2) -> str:
    text = f"{value:.{decimals}f}"
    if "." in text:  # strip trailing zeros only after a decimal point ("200" must stay "200")
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def fmt_idr(value: float) -> str:
    return "Rp" + f"{value:,.0f}".replace(",", ".")


def fmt_idr_short(value: float) -> str:
    sign, a = ("-" if value < 0 else ""), abs(value)
    if a >= 1e12:
        return f"{sign}Rp{_trim(a / 1e12)} triliun"
    if a >= 1e9:
        return f"{sign}Rp{_trim(a / 1e9, 2 if a < 1e11 else 0)} miliar"
    if a >= 1e6:
        return f"{sign}Rp{_trim(a / 1e6, 1 if a < 1e8 else 0)} juta"
    return f"{sign}{fmt_idr(a)}"


def fmt_pct(value: float | None, decimals: int = 1, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    text = f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"
    return text.replace(".", ",") + "%"


def fmt_level(level: float) -> str:
    return _trim(level, 1)


# ----------------------------------------------------------------------------- CSS
CSS = """
<style>
.block-container{max-width:1240px;padding-top:2.4rem;padding-bottom:4rem}
[data-testid="stSidebar"] .block-container{padding-top:1.2rem}
button[role="tab"]{font-weight:600}
div[data-testid="stTabs"] [role="tablist"]{gap:.4rem}

.it-hero{position:relative;overflow:hidden;border-radius:22px;padding:30px 34px 26px;margin:0 0 6px;color:#fff;
  background:radial-gradient(900px 320px at 92% -30%,rgba(255,255,255,.22),transparent 60%),
             linear-gradient(120deg,#0a5c49 0%,#0f7f66 46%,#1d6fb8 100%);}
.it-hero .t{font-size:2rem;font-weight:800;letter-spacing:-.02em;line-height:1.15}
.it-hero .s{margin-top:6px;opacity:.9;max-width:64ch;font-size:1.02rem}
.it-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.it-chip{padding:5px 12px;border-radius:999px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.24);font-size:.8rem}
.it-fine{opacity:.62;font-size:.8rem;margin:2px 4px 18px}

.it-card{border:1px solid color-mix(in srgb,currentColor 15%,transparent);border-radius:16px;padding:18px 20px;
  background:color-mix(in srgb,currentColor 4%,transparent);height:100%}
.it-kpi{min-height:134px}
.it-kpi .l{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;opacity:.65;font-weight:600}
.it-kpi .v{font-size:clamp(1.25rem,1.9vw,1.95rem);font-weight:800;letter-spacing:-.02em;line-height:1.15;margin-top:4px;
  overflow-wrap:anywhere}
.it-kpi .v small{font-size:.9rem;font-weight:600;opacity:.7;margin-left:4px}
.it-kpi .d{margin-top:4px;font-size:.84rem;opacity:.72}
.it-h{font-size:1.2rem;font-weight:750;margin:26px 0 4px;letter-spacing:-.01em}
.it-sub{opacity:.68;font-size:.88rem;margin:0 0 12px}

.it-prod{border:1px solid color-mix(in srgb,currentColor 15%,transparent);border-top:5px solid var(--accent);
  border-radius:16px;padding:16px 20px 14px;background:color-mix(in srgb,currentColor 4%,transparent);height:100%}
.it-prod .tag{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;font-weight:700;opacity:.75}
.it-prod .name{font-size:1.18rem;font-weight:750;margin:6px 0 2px;line-height:1.25}
.it-prod .why{font-size:.8rem;opacity:.68}
.it-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0 10px}
.it-stat b{display:block;font-size:1.02rem;font-weight:750}
.it-stat>span{font-size:.7rem;opacity:.65}
.it-pos{color:var(--pos)}.it-neg{color:var(--neg)}
.it-prod a{font-size:.85rem;font-weight:650;text-decoration:none}
.it-prod details{margin-top:10px;font-size:.82rem;border-top:1px solid color-mix(in srgb,currentColor 12%,transparent);padding-top:8px}
.it-prod summary{cursor:pointer;opacity:.8;font-weight:600}
.it-prod li{margin:6px 0;opacity:.85}

.it-scale{display:grid;grid-template-columns:repeat(var(--n),1fr);gap:3px;margin-top:6px}
.it-scale .seg{height:18px;border-radius:5px}
.it-scale .off{background:repeating-linear-gradient(135deg,transparent 0 3px,color-mix(in srgb,currentColor 25%,transparent) 3px 4px);
  border:1px solid color-mix(in srgb,currentColor 22%,transparent)}
.it-scale .sel{height:26px;margin-top:-4px;outline:2px solid currentColor;outline-offset:2px}
.it-scale .ptr{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;line-height:1.1;white-space:nowrap;overflow:visible}
.it-scale .ptr b{font-size:1rem;font-weight:800}
.it-scale .ptr i{font-style:normal;font-size:.8rem}
.it-zones{display:flex;gap:3px;margin-top:8px;font-size:.74rem;opacity:.72}
.it-zones span{border-top:2px solid color-mix(in srgb,currentColor 35%,transparent);padding-top:3px;text-align:center}
.it-legend{font-size:.76rem;opacity:.7;margin-top:10px}

.it-meter .top{display:flex;justify-content:space-between;align-items:baseline;font-size:.9rem}
.it-meter .top b{font-size:1.4rem;letter-spacing:-.01em}
.it-meter .track{position:relative;height:12px;border-radius:99px;margin:12px 0 26px;
  background:color-mix(in srgb,currentColor 12%,transparent)}
.it-meter .fill{height:100%;border-radius:99px}
.it-meter .lim{position:absolute;top:-6px;bottom:-6px;width:2px;background:currentColor}
.it-meter .lim span{position:absolute;top:24px;left:50%;transform:translateX(-50%);font-size:.72rem;white-space:nowrap;opacity:.8}
.it-status{display:inline-block;font-weight:700;font-size:.85rem;padding:3px 12px;border-radius:99px;
  border:1px solid currentColor}

.it-legendrow{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 0;
  border-bottom:1px solid color-mix(in srgb,currentColor 10%,transparent);font-size:.92rem}
.it-legendrow:last-child{border-bottom:0}
.it-dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:9px}
.it-legendrow small{opacity:.65;margin-left:6px}

.it-step{text-align:left}
.it-step .n{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;opacity:.65;font-weight:700}
.it-step .a{font-size:1.5rem;font-weight:800;margin-top:4px}
.it-term b{display:block;margin-bottom:4px}
.it-term p{margin:0;opacity:.8;font-size:.9rem}
.it-empty{text-align:center;padding:34px 22px}
.it-empty .big{font-size:1.15rem;font-weight:750;margin-bottom:6px}
.it-empty code{font-size:.82rem}
</style>
"""


CSS_FILE = Path(__file__).with_name("app.css")


def inject_css() -> None:
    """Base styles (above) plus tracker/app.css, which is re-read on every render so style edits need no restart."""
    raw = CSS_FILE.read_text(encoding="utf-8") if CSS_FILE.exists() else ""
    # Markdown ends an HTML block at a blank line and treats indented lines as code, so compact the stylesheet.
    extra = "\n".join(line.strip() for line in raw.splitlines() if line.strip())
    st.markdown(CSS, unsafe_allow_html=True)
    if extra:
        st.markdown(f"<style>{extra}</style>", unsafe_allow_html=True)


def _e(text) -> str:
    return html.escape(str(text))


def _css_vars(mode: str) -> str:
    return f"--pos:{GOOD_TEXT[mode]};--neg:{CRITICAL}"


# ----------------------------------------------------------------------------- HTML components
def hero(title: str, subtitle: str, chips: list[str]) -> str:
    chip_html = "".join(f'<span class="it-chip">{_e(c)}</span>' for c in chips)
    return (f'<div class="it-hero"><div class="t">{_e(title)}</div><div class="s">{_e(subtitle)}</div>'
            f'<div class="it-chips">{chip_html}</div></div>')


def kpi(label: str, value: str, sub: str = "", unit: str = "") -> str:
    unit_html = f"<small>{_e(unit)}</small>" if unit else ""
    sub_html = f'<div class="d">{_e(sub)}</div>' if sub else ""
    return (f'<div class="it-card it-kpi"><div class="l">{_e(label)}</div>'
            f'<div class="v">{_e(value)}{unit_html}</div>{sub_html}</div>')


def section(title: str, subtitle: str = "") -> str:
    sub = f'<p class="it-sub">{_e(subtitle)}</p>' if subtitle else ""
    return f'<div class="it-h">{_e(title)}</div>{sub}'


def _delta(value: float | None, decimals: int = 1) -> str:
    """Signed percentage with an arrow, so direction never relies on colour alone."""
    if value is None or pd.isna(value):
        return "n/a"
    cls, arrow = ("it-pos", "▲") if value > 0 else (("it-neg", "▼") if value < 0 else ("", "■"))
    return f'<span class="{cls}">{arrow} {fmt_pct(abs(value), decimals)}</span>' if value != 0 else "0%"


def side_title(step, title: str, sub: str = "") -> str:
    """Numbered section heading for the sidebar; `step` is a number or a short symbol."""
    sub_html = f'<div class="s">{_e(sub)}</div>' if sub else ""
    return f'<div class="it-side"><span class="n">{_e(step)}</span><div><div class="t">{_e(title)}</div>{sub_html}</div></div>'


def side_summary(level: float, zone: str, budget: float, horizon: float, drop_pct: int, syariah: bool) -> str:
    """Compact recap at the top of the sidebar, so the current inputs stay visible while the sections scroll."""
    chips = [f"Profil {fmt_level(level)} · {zone}", f"{fmt_idr_short(budget)}/bulan", f"{horizon:g} tahun", f"maks turun {drop_pct}%"]
    if syariah:
        chips.append("Syariah")
    return ('<div class="it-sidesum"><div class="l">Pengaturan Anda</div><div class="c">'
            + "".join(f"<span>{_e(c)}</span>" for c in chips) + "</div></div>")


def alloc_bar(allocation: dict[str, float], mode: str) -> str:
    """One stacked bar of the category mix; the text next to it carries the identity, so colour is never the only cue."""
    parts = [(c, s) for c, s in allocation.items() if s > 0]
    segs = "".join(
        f'<div style="flex:{s};background:{category_color(c, mode)}" title="{_e(CATEGORY_NAMES.get(c, c))} {s:.0%}"></div>'
        for c, s in parts)
    return f'<div class="it-allocbar">{segs}</div>'


def data_status(as_of: str, age_days: int) -> str:
    fresh = age_days < 7
    icon, label = ("✓", "Data masih baru") if fresh else ("!", "Disarankan diperbarui")
    when = "hari ini" if age_days <= 0 else f"{age_days} hari lalu"
    return (f'<div class="it-datastat {"ok" if fresh else "old"}"><b>{icon} {label}</b>'
            f'<span>Snapshot per {_e(as_of)} ({when})</span></div>')


GOV_LOW_PCT = 30      # below this share of government bonds in the top holdings, the card warns about credit risk


def _holdings_line(p: dict, category: str = "pendapatan_tetap") -> str:
    """Bond funds: what the fact sheet's ten largest holdings show, or an explicit 'not verified' when it could not be read."""
    if category != "pendapatan_tetap":
        return ""
    style = 'font-size:.8rem;opacity:.85;margin-bottom:8px'
    share = p.get("gov_top10_pct")
    if share is None or pd.isna(share):
        return (f'<div style="{style}"><b>Komposisi belum terverifikasi</b>: fact sheet belum terbaca, jadi risiko kredit '
                'dana ini tidak diketahui. Cek sendiri di fund fact sheet.</div>')
    def known(key):
        v = p.get(key)
        return v if v is not None and pd.notna(v) else None

    unknown = known("unknown_top10_pct") or 0.0
    corporate = max(100.0 - share - unknown, 0.0)
    detail = ""
    if known("top10_sum_pct") is not None:
        detail += f' · 10 besar = {known("top10_sum_pct"):.0f}% dana'
    if known("top1_pct") is not None:
        detail += f' · satu efek terbesar {known("top1_pct"):.0f}%'
    if unknown >= 1:
        detail += f' · {unknown:.0f}% belum teridentifikasi jenisnya'
    if corporate >= 50:
        warn = ' · <b>mayoritas obligasi korporasi: risiko gagal bayar penerbit tidak terlihat di grafik harga</b>'
    elif share < GOV_LOW_PCT and unknown >= 30:
        warn = ' · <b>jenis banyak efek tidak teridentifikasi: risiko kredit belum bisa dinilai</b>'
    else:
        warn = ""
    when = f' · fact sheet {_e(str(known("factsheet_date")))}' if known("factsheet_date") else ""
    return f'<div style="{style}">Dari 10 besar isinya: {share:.0f}% obligasi negara{detail}{warn}{when}</div>'


def product_card(category: str, share: float, monthly: float, picks: list[dict], mode: str) -> str:
    """Main pick of a category with key numbers; the other ranked funds sit in a <details> block."""
    top, rest = picks[0], picks[1:]
    color = category_color(category, mode)
    link = f'<a href="{_e(top["url"])}" target="_blank" rel="noopener">Buka di Bibit ↗</a>' if top.get("url") else ""
    alts = ""
    if rest:
        items = "".join(
            f'<li><b>{_e(p["name"])}</b><br>1 th {_delta(p.get("return_1y_pct"))} · 3 th {_delta(p.get("return_3y_pct"))}'
            f' · turun terdalam {fmt_pct(abs(p["drawdown_1y_pct"]) if pd.notna(p.get("drawdown_1y_pct")) else None)}</li>'
            for p in rest)
        alts = f"<details><summary>{len(rest)} alternatif</summary><ul style='padding-left:18px;margin:6px 0 0'>{items}</ul></details>"
    dd = top.get("drawdown_1y_pct")
    held = top.get("held_idr")
    held_badge = (f' <span class="it-held">Sudah dimiliki · {_e(fmt_idr_short(held))}</span>'
                  if held is not None and pd.notna(held) else "")
    return (
        f'<div class="it-prod" style="--accent:{color};{_css_vars(mode)}">'
        f'<div class="top"><span class="tag" style="color:{color}">{_e(CATEGORY_NAMES.get(category, category))}</span>'
        f'<span class="pct">{share:.0%}</span></div>'
        f'<div class="amt">{_e(fmt_idr(monthly))}<small>per bulan</small></div>'
        f'<div class="name">{_e(top["name"])}{held_badge}</div><div class="why">Dipilih karena: {_e(top.get("alasan") or "skor seimbang")}</div>'
        f'<div class="it-stats">'
        f'<div class="it-stat"><b>{_delta(top.get("return_1y_pct"))}</b><span>return 1 th</span></div>'
        f'<div class="it-stat"><b>{_delta(top.get("return_3y_pct"))}</b><span>return 3 th</span></div>'
        f'<div class="it-stat"><b>{fmt_pct(abs(dd) if pd.notna(dd) else None)}</b><span>turun terdalam</span></div>'
        f'</div><div style="font-size:.8rem;opacity:.7;margin-bottom:8px">Dana kelolaan {_e(fmt_idr_short(top["aum_idr"]))}</div>'
        f'{_holdings_line(top, category)}{link}{alts}</div>'
    )


def profile_scale(levels: list[float], losses: list[float], limit: float, selected: float) -> str:
    """The 1-10 Bibit scale: segments inside the user's limit are solid (blue ramp), beyond it hatched."""
    n = len(levels)
    pointer = "".join(
        f'<div class="ptr">{"<b>" + fmt_level(lv) + "</b><i>▼</i>" if lv == selected else ""}</div>' for lv in levels)
    segs = []
    for i, (lv, loss) in enumerate(zip(levels, losses)):
        inside = -loss <= limit
        style = f"background:{sequential(i, n)}" if inside else ""
        cls = ("seg " + ("" if inside else "off ") + ("sel" if lv == selected else "")).strip()
        segs.append(f'<div class="{cls}" style="{style}" title="Profil {fmt_level(lv)}: turun {fmt_pct(-loss * 100)}"></div>')
    kon = sum(1 for lv in levels if lv <= 4)
    mod = sum(1 for lv in levels if 4 < lv <= 7)
    agr = n - kon - mod
    zones = (f'<div class="it-zones"><span style="flex:{kon}">Konservatif 1–4</span>'
             f'<span style="flex:{mod}">Moderat 4,5–7</span><span style="flex:{agr}">Agresif 7,5–10</span></div>')
    legend = (f'<div class="it-legend">Warna penuh = perkiraan turun masih dalam batas Anda ({limit:.0%}). '
              f'Garis miring = melewati batas.</div>')
    return (f'<div class="it-scale" style="--n:{n}">{pointer}{"".join(segs)}</div>{zones}{legend}')


def _meter_row(label: str, loss: float, limit: float, scale: float, mode: str, show_limit_label: bool) -> str:
    fall, ok = -loss, -loss <= limit
    color = GOOD if ok else CRITICAL
    status = "✓ Dalam batas Anda" if ok else "✕ Melewati batas Anda"
    limit_label = f"<span>batas -{limit:.0%}</span>" if show_limit_label else ""
    track_cls = "track" if show_limit_label else "track nolabel"
    return (
        f'<div class="top"><span>{_e(label)}</span><b>{_e(fmt_pct(-fall * 100))}</b></div>'
        f'<div class="{track_cls}"><div class="fill" style="width:{fall / scale * 100:.1f}%;background:{color}"></div>'
        f'<div class="lim" style="left:{limit / scale * 100:.1f}%">{limit_label}</div></div>'
        f'<span class="it-status" style="color:{GOOD_TEXT[mode] if ok else CRITICAL}">{status}</span>'
    )


def risk_meter(loss: float, limit: float, mode: str, crisis_loss: float | None = None) -> str:
    """Bad-year loss against the user's limit; with `crisis_loss` a second bar shows the assumed severe-crisis loss.

    Status is always icon + words, never colour alone.
    """
    losses = [loss] + ([crisis_loss] if crisis_loss is not None else [])
    scale = max(limit, *(-x for x in losses)) * 1.35 or 1
    first = _meter_row("Perkiraan turun di tahun buruk" if crisis_loss is None else "Tahun buruk (data 1 tahun)", loss, limit,
                       scale, mode, show_limit_label=crisis_loss is None)
    if crisis_loss is None:
        return f'<div class="it-meter">{first}</div>'
    second = _meter_row("Krisis berat (asumsi)", crisis_loss, limit, scale, mode, show_limit_label=True)
    return f'<div class="it-meter">{first}<div class="it-meter-gap"></div>{second}</div>'


def crisis_grid(grid: list[list[float]], saham: tuple, obligasi: tuple, limit: float) -> str:
    """Stock-fall x bond-fall table of portfolio loss; each cell has an icon and words' worth of mark, never colour alone."""
    head = "".join(f"<th>Obligasi -{o}%</th>" for o in obligasi)
    body = ""
    for s, row in zip(saham, grid):
        cells = "".join(
            f'<td class="{"ok" if -v <= limit else "bad"}"><b>{_e(fmt_pct(v * 100))}</b> {"✓" if -v <= limit else "✕"}</td>' for v in row)
        body += f"<tr><th>Saham -{s}%</th>{cells}</tr>"
    return (f'<table class="it-grid"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>'
            f'<div class="it-grid-key">✓ dalam batas -{limit:.0%} Anda · ✕ melewati batas</div>')


def _loss_cell(loss: float, base: float, limit: float) -> str:
    ok = -loss <= limit
    return (f'<td class="{"ok" if ok else "bad"}"><b>{_e(fmt_pct(loss * 100))}</b>'
            f'<br>{_e(fmt_idr_short(loss * base))} {"✓" if ok else "✕"}</td>')


def scenario_table(rows: list[dict], base: float, base_label: str, limit: float, verified: bool = True,
                   exposures: tuple = ()) -> str:
    """Hypothetical scenarios: loss in % and rupiah, with icon + words against the user's limit.

    `verified` True: one column, the bond mix comes from a read fact sheet. False: one column per assumed corporate share of
    the bond funds (rows come from metrics.scenario_range) and a banner says the composition is NOT verified.
    The size of every shock is an assumption in both cases; only the bond composition can be data.
    """
    if verified:
        head, cells = "<th>Perkiraan rugi</th>", lambda r: _loss_cell(r["loss"], base, limit)
        badge = ("Komposisi obligasi: <b>data fact sheet</b> (hanya 10 besar isi dana). "
                 "Besar guncangan: <b>asumsi</b>.")
    else:
        head = "".join(f"<th>Jika {e:.0%} korporasi</th>" for e in exposures)
        cells = lambda r: "".join(_loss_cell(r["losses"][e], base, limit) for e in exposures)  # noqa: E731
        badge = ("<b>Belum terverifikasi</b>: isi dana pendapatan tetap tidak terbaca, jadi porsi korporasi tidak diketahui. "
                 "Kolom di bawah adalah <b>simulasi dengan asumsi</b>, bukan data.")
    body = "".join(f'<tr><th>{_e(r["name"])}<small>{_e(r["note"])}</small></th>{cells(r)}</tr>' for r in rows)
    return (f'<div class="it-grid-key" style="margin:0 0 .5rem">{badge}</div>'
            f'<table class="it-grid it-scen"><thead><tr><th>Skenario</th>{head}</tr></thead><tbody>{body}</tbody></table>'
            f'<div class="it-grid-key">Rupiah dihitung dari {_e(base_label)} ({_e(fmt_idr_short(base))}). '
            f'✓ dalam batas -{limit:.0%} Anda · ✕ melewati batas</div>')


def legend_rows(allocation: dict[str, float], amounts: dict[str, float], mode: str) -> str:
    rows = "".join(
        f'<div class="it-legendrow"><span><span class="it-dot" style="background:{category_color(c, mode)}"></span>'
        f'{_e(CATEGORY_NAMES.get(c, c))}<small>{s:.0%}</small></span><b>{_e(fmt_idr(amounts.get(c, 0)))}</b></div>'
        for c, s in allocation.items() if s > 0)
    return f"<div>{rows}</div>"


def step_cards(steps: list[tuple[str, float]]) -> list[str]:
    return [f'<div class="it-card it-step"><div class="n">{_e(p)}</div><div class="a">{_e(fmt_idr(a))}</div>'
            f'<div style="opacity:.65;font-size:.82rem">per bulan</div></div>' for p, a in steps]


def term_card(term: str, text: str, example: str = "", group: str = "") -> str:
    tag = f'<span class="grp">{_e(group)}</span>' if group else ""
    ex = f'<p class="ex"><b>Contoh:</b> {_e(example)}</p>' if example else ""
    return f'<div class="it-card it-term">{tag}<b>{_e(term)}</b><p>{_e(text)}</p>{ex}</div>'


def empty_state(title: str, body: str, code_lines: list[str]) -> str:
    code = "<br>".join(f"<code>{_e(c)}</code>" for c in code_lines)
    return f'<div class="it-card it-empty"><div class="big">{_e(title)}</div><div style="opacity:.75">{_e(body)}</div><div style="margin-top:12px">{code}</div></div>'


# ----------------------------------------------------------------------------- charts
def _base(fig: go.Figure, height: int, mode: str) -> go.Figure:
    grid = "rgba(128,128,128,.22)"
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=44, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Source Sans, system-ui, sans-serif", size=13),
        # legend above the plot: below it, it collides with rotated tick labels on a phone
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=12)),
        hoverlabel=dict(font_size=13),
    )
    # automargin lets the axes make room for their own labels and titles instead of being cut off on narrow screens
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="rgba(128,128,128,.4)", automargin=True)
    fig.update_yaxes(gridcolor=grid, zeroline=False, automargin=True)
    return fig


def donut(allocation: dict[str, float], center_title: str, center_sub: str, mode: str) -> go.Figure:
    cats = [c for c, s in allocation.items() if s > 0]
    fig = go.Figure(go.Pie(
        labels=[CATEGORY_NAMES.get(c, c) for c in cats], values=[allocation[c] for c in cats], hole=0.66, sort=False,
        marker=dict(colors=[category_color(c, mode) for c in cats], line=dict(color="rgba(0,0,0,0)", width=4)),
        textinfo="none", hovertemplate="%{label}: %{percent}<extra></extra>", direction="clockwise",
    ))
    fig.add_annotation(text=f"<b style='font-size:20px'>{center_title}</b><br><span style='opacity:.65'>{center_sub}</span>",
                       showarrow=False, font=dict(size=13))
    _base(fig, 250, mode).update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0))
    return fig


def level_chart(levels: list[float], losses: list[float], limit: float, selected: float, mode: str) -> go.Figure:
    falls = [-l * 100 for l in losses]
    inside = [-l <= limit for l in losses]
    blue = BLUE[mode]
    fig = go.Figure(go.Bar(
        x=[fmt_level(l) for l in levels], y=falls,
        marker=dict(color=[blue if ok else "rgba(137,135,129,.55)" for ok in inside],
                    line=dict(color=[ink(mode) if l == selected else "rgba(0,0,0,0)" for l in levels],
                              width=[3 if l == selected else 0 for l in levels])),
        hovertemplate="Profil %{x}<br>Perkiraan turun %{y:.1f}%<extra></extra>",
    ))
    fig.add_hline(y=limit * 100, line=dict(dash="dash", width=2, color=CRITICAL), annotation_text=f"Batas Anda {limit:.0%}",
                  annotation_position="top left", annotation_font=dict(size=12, color=CRITICAL))
    _base(fig, 330, mode).update_layout(showlegend=False, bargap=0.28, xaxis_title="Profil risiko Bibit",
                                        yaxis_title="Perkiraan turun (%)")
    fig.update_xaxes(type="category")  # labels like "4,5" must not be parsed as the number 45
    try:
        fig.update_layout(barcornerradius=4)
    except Exception:  # older Plotly: square bar ends are fine
        pass
    return fig


def projection_chart(years: list[int], series: dict[str, list[float]], contributions: list[float],
                     real_selected: list[float], selected: str, mode: str) -> go.Figure:
    """Values in Rp juta. Band = pessimistic..optimistic, solid line = chosen scenario, dashed = deposits."""
    blue = BLUE[mode]
    names = list(series)
    lo, hi = series[names[0]], series[names[-1]]
    fig = go.Figure()
    if len(names) > 1:  # a single user-defined line has no range to shade
        fig.add_trace(go.Scatter(x=years, y=hi, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=years, y=lo, mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(42,120,214,.16)", name="Rentang pesimis-optimis", hoverinfo="skip"))
    for name in names:
        chosen = name == selected
        fig.add_trace(go.Scatter(
            x=years, y=series[name], mode="lines", name=name, line=dict(color=blue, width=3.5 if chosen else 1.4),
            opacity=1 if chosen else 0.55, hovertemplate=f"{name}: Rp%{{y:,.0f}} juta<extra></extra>"))
    fig.add_trace(go.Scatter(x=years, y=contributions, mode="lines", name="Total setoran",
                             line=dict(color="#898781", width=2, dash="dash"), hovertemplate="Setoran: Rp%{y:,.0f} juta<extra></extra>"))
    fig.add_trace(go.Scatter(x=years, y=real_selected, mode="lines", name=f"{selected} (daya beli sekarang)",
                             line=dict(color=CATEGORY_COLORS[mode]["saham"], width=2.2, dash="dot"),
                             hovertemplate="Daya beli sekarang: Rp%{y:,.0f} juta<extra></extra>"))
    _base(fig, 380, mode).update_layout(hovermode="x unified", xaxis_title="Tahun", yaxis_title="Rp juta",
                                        yaxis=dict(tickformat=",.0f"))
    return fig


def compare_chart(rows: dict[str, dict[str, float | None]], mode: str) -> go.Figure:
    """Two portfolios (system vs robo) on the same past-performance measures."""
    # <br> keeps the labels upright and inside the plot at any width (no rotation, no overlap)
    measures = [("return_1y_pct", "Return<br>1 th"), ("return_3y_pct", "Return<br>3 th"),
                ("return_5y_pct", "Return<br>5 th"), ("drawdown_1y_pct", "Turun<br>terdalam")]
    palette = [BLUE[mode], CATEGORY_COLORS[mode]["saham"]]
    fig = go.Figure()
    for (label, vals), color in zip(rows.items(), palette):
        fig.add_trace(go.Bar(name=label, x=[m[1] for m in measures], y=[vals.get(m[0]) for m in measures],
                             marker_color=color, text=[fmt_pct(vals.get(m[0]), 1, True) for m in measures],
                             textposition="outside", cliponaxis=False,
                             hovertemplate=f"{label}: %{{y:.2f}}%<extra></extra>"))
    _base(fig, 330, mode).update_layout(barmode="group", bargap=0.3, bargroupgap=0.08, yaxis_title="%")
    fig.add_hline(y=0, line=dict(width=1, color="rgba(128,128,128,.6)"))
    return fig


def product_scatter(df: pd.DataFrame, picks: list[str], mode: str) -> go.Figure:
    """Past 3-year return vs worst 1-year fall. Only the three main categories are coloured; the rest stay grey."""
    d = df.dropna(subset=["return_3y_pct", "drawdown_1y_pct"])
    fig = go.Figure()
    groups = [("pasar_uang", "Pasar uang"), ("pendapatan_tetap", "Obligasi"), ("saham", "Saham")]
    for cat, label in groups:
        g = d[d["category"] == cat]
        fig.add_trace(go.Scatter(x=g["drawdown_1y_pct"], y=g["return_3y_pct"], mode="markers", name=label, text=g["name"],
                                 marker=dict(size=9, color=category_color(cat, mode), opacity=0.78, line=dict(width=1.5, color="rgba(0,0,0,0)")),
                                 hovertemplate="%{text}<br>Turun terdalam %{x:.1f}% · Return 3 th %{y:.1f}%<extra></extra>"))
    other = d[~d["category"].isin([g[0] for g in groups])]
    fig.add_trace(go.Scatter(x=other["drawdown_1y_pct"], y=other["return_3y_pct"], mode="markers", name="Lainnya", text=other["name"],
                             marker=dict(size=8, color="#898781", opacity=0.5),
                             hovertemplate="%{text}<br>Turun terdalam %{x:.1f}% · Return 3 th %{y:.1f}%<extra></extra>"))
    sel = d[d["name"].isin(picks)]
    if not sel.empty:
        positions = ["top center", "bottom center", "middle left", "middle right"]  # keep neighbouring labels apart
        fig.add_trace(go.Scatter(x=sel["drawdown_1y_pct"], y=sel["return_3y_pct"], mode="markers+text", name="Pilihan sistem",
                                 text=sel["name"], textposition=[positions[i % 4] for i in range(len(sel))],
                                 textfont=dict(size=11),
                                 marker=dict(size=15, symbol="diamond", color="rgba(0,0,0,0)", line=dict(width=2.5, color=ink(mode))),
                                 hoverinfo="skip"))
    return _base(fig, 430, mode).update_layout(xaxis_title="Penurunan terdalam 1 th (%)",
                                               yaxis_title="Return 3 th (%)")


_MD = re.compile(r"\*\*(.+?)\*\*")


def md_bold(text: str) -> str:
    return _MD.sub(r"<b>\1</b>", _e(text))
