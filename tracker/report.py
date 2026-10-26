"""PDF report for one recommendation, built from a snapshot dict (history.snapshot), so the current recommendation and
a saved one go through the same code. Only numbers already in the snapshot are used; projections are recomputed
deterministically with metrics.future_value_dca. Built-in PDF fonts only (no downloads), so text avoids symbols
outside Latin-1: direction is written as +/- and status as words, never colour alone."""
from __future__ import annotations

import io
import math
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String, Wedge
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import metrics
from .ui import CATEGORY_COLORS, CATEGORY_NAMES, fmt_idr, fmt_idr_short, fmt_level, fmt_pct, sequential

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

GREEN, DARK_GREEN = HexColor("#1baf7a"), HexColor("#0e6b4b")
INK, MUTED, LINE, PANEL = HexColor("#16201c"), HexColor("#5d6a64"), HexColor("#d9dfdb"), HexColor("#f4f7f5")
GOOD, CRITICAL = HexColor("#006300"), HexColor("#b32d2d")
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember"]
SCENARIO_COLORS = {"Pesimis": "#898781", "Dasar": "#1baf7a", "Optimis": "#2a78d6"}


def _style(name: str, **kw) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "body": _style("body"),
    "small": _style("small", fontSize=8, leading=11, textColor=MUTED),
    "h2": _style("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=14, spaceAfter=1),
    "sub": _style("sub", fontSize=8.5, leading=11.5, textColor=MUTED, spaceAfter=6),
    "label": _style("label", fontName="Helvetica-Bold", fontSize=6.8, leading=9, textColor=MUTED),
    "kpi": _style("kpi", fontName="Helvetica-Bold", fontSize=16, leading=19),
    "kpisub": _style("kpisub", fontSize=7.5, leading=10, textColor=MUTED),
    "bullet": _style("bullet", leftIndent=10, bulletIndent=0, spaceAfter=2),
    "name": _style("name", fontName="Helvetica-Bold", fontSize=11.5, leading=14),
    "right": _style("right", alignment=TA_RIGHT),
}


def _p(text: str, style: str = "body", **kw) -> Paragraph:
    return Paragraph(text, S[style] if not kw else ParagraphStyle("tmp", parent=S[style], **kw))


def _e(value) -> str:
    return escape(str(value))


def _date_id(iso: str, with_time: bool = False) -> str:
    dt = datetime.fromisoformat(iso)
    out = f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"
    return f"{out}, {dt:%H.%M}" if with_time else out


def _cat_name(cat: str) -> str:
    return CATEGORY_NAMES.get(cat, cat)


def _cat_color(cat: str) -> HexColor:
    return HexColor(CATEGORY_COLORS["light"].get(cat, CATEGORY_COLORS["light"]["other"]))


def _num(value, fmt) -> str:
    return "n/a" if value is None or (isinstance(value, float) and math.isnan(value)) else fmt(value)


def _ret(value) -> str:
    return _num(value, lambda v: fmt_pct(v, 1, signed=True))


def _ret_color(value) -> str:
    if value is None:
        return "#5d6a64"
    return "#006300" if value >= 0 else "#b32d2d"


# ----------------------------------------------------------------------------- building blocks
def _section(title: str, sub: str = "") -> list:
    items = [_p(_e(title), "h2")]
    items.append(_p(_e(sub), "sub") if sub else Spacer(1, 4))
    return items


def _kpi(label: str, value: str, sub: str = "") -> list:
    return [_p(_e(label.upper()), "label"), _p(_e(value), "kpi"), _p(_e(sub), "kpisub")]


def _hero(snap: dict, current: bool) -> Table:
    inputs, prof = snap["inputs"], snap["profile"]
    badge = ("REKOMENDASI SAAT INI - BELUM DISIMPAN" if current
             else f"TERSIMPAN {_date_id(snap['saved_at'], True).upper()}")
    chips = (f"Data produk per {_date_id(snap['data_as_of'])}   |   Profil risiko {fmt_level(prof['level'])} "
             f"({prof['name'].capitalize()})   |   Tujuan {inputs['horizon_years']:g} tahun")
    cell = [
        _p(f'<font color="#bff0dc"><b>{_e(badge)}</b></font>', "small", fontSize=7.5),
        Spacer(1, 3),
        _p('<font color="#bff0dc"><b>KOMPAS INVESTASI</b></font>', "small", fontSize=9),
        _p('<font color="white"><b>Laporan Rekomendasi</b></font>', "body", fontSize=22, leading=26),
        _p('<font color="#d6f5e8">Produk Bibit yang cocok dengan profil risiko dan batas penurunan Anda</font>',
           "body", fontSize=10, leading=14),
        Spacer(1, 7),
        _p(f'<font color="white">{_e(chips)}</font>', "body", fontSize=8.5),
    ]
    t = Table([[cell]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_GREEN), ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16), ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14), ("LINEBEFORE", (0, 0), (0, -1), 5, GREEN),
    ]))
    return t


def _kpi_row(cells: list[list]) -> Table:
    w = CONTENT_W / len(cells)
    t = Table([cells], colWidths=[w] * len(cells))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEBEFORE", (1, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _donut(allocation: dict[str, float], centre: str, size: float = 56 * mm) -> Drawing:
    d = Drawing(size, size)
    cx = cy = size / 2
    outer, inner = size / 2 - 2, size / 2 - 17 * mm / 1.4
    angle = 90.0
    shares = [(c, s) for c, s in allocation.items() if s > 0]
    for cat, share in shares:
        if len(shares) == 1:
            d.add(Circle(cx, cy, outer, fillColor=_cat_color(cat), strokeColor=colors.white, strokeWidth=1.5))
            break
        end = angle - share * 360
        d.add(Wedge(cx, cy, outer, end, angle, fillColor=_cat_color(cat), strokeColor=colors.white, strokeWidth=1.5))
        angle = end
    d.add(Circle(cx, cy, inner, fillColor=colors.white, strokeColor=colors.white))
    d.add(String(cx, cy + 1, centre, fontName="Helvetica-Bold", fontSize=11, fillColor=INK, textAnchor="middle"))
    d.add(String(cx, cy - 10, "per bulan", fontName="Helvetica", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    return d


def _allocation_block(snap: dict) -> Table:
    alloc, amounts = snap["allocation"], snap["monthly_amounts"]
    rows = [[_p("JENIS", "label"), _p("PORSI", "label"), _p("PER BULAN", "label", alignment=TA_RIGHT)]]
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]
    for i, (cat, share) in enumerate((c, s) for c, s in alloc.items() if s > 0):
        rows.append([
            _p(f'<font color="{_cat_color(cat).hexval().replace("0x", "#")}">&#9632;</font>  <b>{_e(_cat_name(cat))}</b>',
               "body", fontSize=10.5),
            _p(f"<b>{share:.0%}</b>", "body", fontSize=12),
            _p(f"<b>{_e(fmt_idr(amounts.get(cat, 0)))}</b>", "right", fontSize=11.5),
        ])
        style.append(("LINEBELOW", (0, i + 1), (-1, i + 1), 0.4, LINE))
    right = Table(rows, colWidths=[44 * mm, 20 * mm, 40 * mm])
    right.setStyle(TableStyle(style))
    total = float(sum(amounts.values()))
    t = Table([[_donut(alloc, fmt_idr_short(total)), right]], colWidths=[62 * mm, CONTENT_W - 62 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _portfolio_section(snap: dict) -> list:
    pf = snap.get("portfolio")
    if not pf:
        return []
    total_now, total_after = pf["total_now"], sum(pf["after"].values())
    items = _section("Dari portofolio Anda menuju target",
                     f"Portofolio sekarang {fmt_idr_short(total_now)}. Tidak ada yang perlu dijual: setoran bulanan menutup selisih ke target.")
    head = [_p(t, "label") for t in ("JENIS", "SEKARANG", "TARGET", "SETORAN BULAN INI", "SETELAH SETORAN", "STATUS")]
    rows = [head]
    for cat in dict.fromkeys([*pf["target"], *pf["current"]]):
        now = pf["current"].get(cat, 0.0) / total_now
        tgt = pf["target"].get(cat, 0.0)
        dep = pf["contribution"].get(cat, 0.0)
        if dep > 0 and now < tgt - 0.02:
            status, color = "Di bawah target, diisi dulu", "#006300"
        elif abs(now - tgt) <= 0.05:
            status, color = "Sesuai target", "#5d6a64"
        elif dep == 0:
            status, color = "Di atas target, tidak ditambah", "#b32d2d"
        else:
            status, color = "Setoran sesuai porsi target", "#5d6a64"
        rows.append([
            _p(f'<font color="{_cat_color(cat).hexval().replace("0x", "#")}">&#9632;</font> <b>{_e(_cat_name(cat))}</b>'),
            _p(f"{now:.0%}"), _p(f"{tgt:.0%}"), _p(f"<b>{_e(fmt_idr(dep))}</b>"),
            _p(f"{pf['after'].get(cat, 0.0) / total_after:.0%}"), _p(f'<font color="{color}"><b>{status}</b></font>', "body", fontSize=8),
        ])
    t = Table(rows, colWidths=[30 * mm, 20 * mm, 18 * mm, 32 * mm, 26 * mm, CONTENT_W - 126 * mm], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED), ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                           ("BACKGROUND", (0, 0), (-1, 0), PANEL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    items.append(t)
    months = pf.get("months_to_target")
    tail = (f" Dengan setoran yang sama, komposisi mendekati target (selisih di bawah 5 poin) sekitar {months} bulan lagi, "
            "belum menghitung perubahan harga.") if months else " Komposisi Anda sudah dekat dengan target."
    items += [Spacer(1, 4), _p(f"Perkiraan turun di tahun buruk: <b>{fmt_pct(pf['stress_now'] * 100)}</b> sekarang, "
                              f"<b>{fmt_pct(pf['stress_after'] * 100)}</b> setelah setoran bulan ini (total portofolio)." + tail, "small")]
    return items


def _risk_drawing(loss: float, limit: float, ok: bool, whole: bool = False, crisis_loss: float | None = None) -> Drawing:
    """Bad-year bar, plus a second bar for the assumed severe crisis when given. Status is words, not colour alone."""
    w = CONTENT_W
    two = crisis_loss is not None
    d = Drawing(w, 94 if two else 46)
    scale = max(limit, -loss, -(crisis_loss or 0.0)) * 1.35 or 1
    lx = w * limit / scale
    scope = "total portofolio" if whole else "di tahun buruk"
    rows = [(62 if two else 20, loss, f"Perkiraan turun {scope}" + (" (data 1 tahun)" if two else ""), ok)]
    if two:
        rows.append((18, crisis_loss, "Krisis berat (asumsi)", -crisis_loss <= limit))
    for i, (y, value, label, row_ok) in enumerate(rows):
        d.add(Rect(0, y, w, 11, rx=5.5, ry=5.5, fillColor=HexColor("#e6ebe8"), strokeColor=None))
        d.add(Rect(0, y, max(w * -value / scale, 11), 11, rx=5.5, ry=5.5, fillColor=GOOD if row_ok else CRITICAL, strokeColor=None))
        d.add(Line(lx, y - 5, lx, y + 16, strokeColor=INK, strokeWidth=1.6))
        if i == 0:
            d.add(String(lx, y + 21, f"batas Anda -{limit:.0%}", fontName="Helvetica-Bold", fontSize=8, fillColor=INK,
                         textAnchor="middle" if lx > 60 else "start"))
        d.add(String(0, y - 14, f"{label}: {fmt_pct(value * 100)}", fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
        d.add(String(w, y - 14, "DALAM BATAS ANDA" if row_ok else "MELEWATI BATAS ANDA", fontName="Helvetica-Bold", fontSize=9.5,
                     fillColor=GOOD if row_ok else CRITICAL, textAnchor="end"))
    return d


def _scale_drawing(level: float) -> Drawing:
    n, w = 19, CONTENT_W
    gap = 2.5
    seg = (w - gap * (n - 1)) / n
    d = Drawing(w, 52)
    sel = round((level - 1) * 2)
    for i in range(n):
        x = i * (seg + gap)
        if i == sel:
            d.add(Rect(x, 17, seg, 19, rx=3, ry=3, fillColor=HexColor(sequential(i, n)), strokeColor=INK, strokeWidth=1.6))
            cx = x + seg / 2
            d.add(Polygon([cx - 4, 43, cx + 4, 43, cx, 38], fillColor=INK, strokeColor=INK))
            d.add(String(cx, 46, fmt_level(level), fontName="Helvetica-Bold", fontSize=10, fillColor=INK, textAnchor="middle"))
        else:
            d.add(Rect(x, 18, seg, 14, rx=3, ry=3, fillColor=HexColor(sequential(i, n)), strokeColor=None))
    zones = [("Konservatif 1-4", 0, 6), ("Moderat 4,5-7", 7, 12), ("Agresif 7,5-10", 13, 18)]
    for label, a, b in zones:
        xa, xb = a * (seg + gap), b * (seg + gap) + seg
        d.add(Line(xa, 12, xb, 12, strokeColor=LINE, strokeWidth=0.8))
        d.add(String((xa + xb) / 2, 2, label, fontName="Helvetica", fontSize=8, fillColor=MUTED, textAnchor="middle"))
    return d


def _product_card(cat: str, share: float, amount: float, picks: list[dict]) -> KeepTogether:
    col = _cat_color(cat)
    main = picks[0]
    head = Table([[
        _p(f'<font color="white"><b>{_e(_cat_name(cat).upper())}</b></font>', "body", fontSize=8.5),
        _p(f'<font color="white"><b>{share:.0%}  |  {_e(fmt_idr(amount))} per bulan</b></font>', "right", fontSize=10),
    ]], colWidths=[CONTENT_W * 0.4, CONTENT_W * 0.6])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), col), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 6),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

    def metric(label: str, value: str, color: str = "#16201c") -> list:
        return [_p(_e(label.upper()), "label"), _p(f'<font color="{color}"><b>{_e(value)}</b></font>', "body", fontSize=11)]

    dd = main.get("drawdown_1y_pct")
    metrics_row = Table([[
        metric("Return 1 tahun", _ret(main.get("return_1y_pct")), _ret_color(main.get("return_1y_pct"))),
        metric("Return 3 tahun", _ret(main.get("return_3y_pct")), _ret_color(main.get("return_3y_pct"))),
        metric("Turun terdalam 1 th", _num(dd, lambda v: fmt_pct(-abs(v), 1) if abs(v) >= 0.05 else "0%")),
        metric("Dana kelolaan", _num(main.get("aum_idr"), fmt_idr_short)),
    ]], colWidths=[CONTENT_W / 4 - 5] * 4)
    metrics_row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    body = [
        _p(_e(main["name"]) + (f' <font size="8" color="#0e6b4b">[sudah Anda miliki: {_e(fmt_idr_short(main["held_idr"]))}]</font>'
                               if main.get("held_idr") else ""), "name"),
        _p(f"Dipilih karena: {_e(main.get('alasan') or 'skor seimbang di kategorinya')}.", "small"),
        Spacer(1, 5), metrics_row, Spacer(1, 4),
    ]
    if len(picks) > 1:
        alts = "   |   ".join(f"<b>{i}.</b> {_e(p['name'])} ({_e(_ret(p.get('return_3y_pct')))} 3 th)"
                             for i, p in enumerate(picks[1:], start=2))
        body.append(_p(f"<b>Alternatif:</b> {alts}", "small"))
    if main.get("url"):
        body.append(_p(f'<link href="{_e(main["url"])}" color="#2a78d6">{_e(main["url"])}</link>', "small"))
    inner = Table([[body]], colWidths=[CONTENT_W])
    inner.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return KeepTogether([head, inner, Spacer(1, 9)])


def _projection_chart(years: list[int], series: dict[str, list[float]], deposits: list[float]) -> Drawing:
    w, h = CONTENT_W, 190
    left, right, top, bottom = 52, 62, 10, 22
    pw, ph = w - left - right, h - top - bottom
    d = Drawing(w, h)
    ymax = max(max(v) for v in series.values()) * 1.05 or 1
    xmax = max(years) or 1

    def px(x):
        return left + pw * x / xmax

    def py(y):
        return bottom + ph * y / ymax

    for i in range(5):
        v = ymax * i / 4
        d.add(Line(left, py(v), left + pw, py(v), strokeColor=LINE if i else MUTED, strokeWidth=0.5))
        d.add(String(left - 5, py(v) - 3, fmt_idr_short(v).replace("Rp", ""), fontName="Helvetica", fontSize=7,
                     fillColor=MUTED, textAnchor="end"))
    step = max(1, round(xmax / 6))
    for yr in range(0, xmax + 1, step):
        d.add(String(px(yr), bottom - 12, f"{yr} th", fontName="Helvetica", fontSize=7, fillColor=MUTED, textAnchor="middle"))

    def line(vals, color, width, dash=None):
        pts = list(zip(years, vals))
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            d.add(Line(px(xa), py(ya), px(xb), py(yb), strokeColor=HexColor(color), strokeWidth=width, strokeDashArray=dash))

    line(deposits, "#9aa39e", 1.2, [3, 2])
    d.add(String(px(xmax) + 4, py(deposits[-1]) - 3, "Setoran", fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
    for name, vals in series.items():
        line(vals, SCENARIO_COLORS.get(name, "#898781"), 2.6 if name == "Dasar" else 1.6)
        d.add(String(px(xmax) + 4, py(vals[-1]) - 3, name, fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
    return d


def _projection_section(snap: dict) -> list:
    proj = snap.get("projection")
    inputs = snap["inputs"]
    if not proj or not proj.get("rates"):
        return []
    horizon, budget, inflation = inputs["horizon_years"], inputs["monthly_budget"], proj.get("inflation", 0.0)
    initial = (snap.get("portfolio") or {}).get("total_now", 0.0)
    rates = proj["rates"]
    years = list(range(0, int(horizon) + 1))
    series = {n: [metrics.future_value_dca(budget, r, y, initial=initial) for y in years] for n, r in rates.items()}
    deposits = [initial + budget * 12 * y for y in years]
    start = f" ditambah portofolio sekarang {fmt_idr_short(initial)}" if initial else ""
    items = _section(f"Proyeksi {horizon:g} tahun",
                     f"Setor {fmt_idr(budget)} per bulan{start}, dengan asumsi return tetap. Ini skenario 'bagaimana kalau', bukan ramalan.")
    items.append(_projection_chart(years, series, deposits))
    base = "Dasar" if "Dasar" in rates else next(iter(rates))
    names = list(rates)
    head = [_p("TAHUN", "label"), _p("MODAL + SETORAN" if initial else "SETORAN", "label")] + [_p(n.upper(), "label") for n in names] + \
           [_p(f"{base.upper()} (DAYA BELI SEKARANG)", "label")]
    rows = [head]
    for y in sorted({y for y in (1, 3, 5, 10, int(horizon)) if 0 < y <= horizon}):
        rows.append([_p(f"{y}", "body"), _p(fmt_idr_short(initial + budget * 12 * y), "body")]
                    + [_p(f"<b>{_e(fmt_idr_short(series[n][y]))}</b>" if n == base else _e(fmt_idr_short(series[n][y])), "body")
                       for n in names]
                    + [_p(_e(fmt_idr_short(metrics.deflate(series[base][y], inflation, y))), "body")])
    t = Table(rows, colWidths=[16 * mm, 28 * mm] + [26 * mm] * len(names) + [CONTENT_W - 44 * mm - 26 * mm * len(names)],
              repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED), ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                           ("BACKGROUND", (0, 0), (-1, 0), PANEL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    items += [Spacer(1, 6), t, Spacer(1, 4)]
    rate_text = ", ".join(f"{n} {fmt_pct(r * 100)}" for n, r in rates.items())
    items.append(_p(f"Return portofolio per tahun yang dipakai: {_e(rate_text)}. Inflasi {inflation:.1%} per tahun dipakai "
                    "untuk kolom daya beli sekarang. <b>Pesimis</b> = kondisi kurang bagus, batas bawah perencanaan. "
                    "<b>Dasar</b> = kondisi biasa. <b>Optimis</b> = kondisi cukup baik. Jadikan Pesimis sebagai rencana: "
                    "bila target tercapai di situ, rencananya tangguh.", "small"))
    return items


def _decision_summary(snap: dict) -> list:
    inputs = snap["inputs"]
    items = []
    for cat, picks in snap["picks"].items():
        if not picks:
            continue
        amount = snap["monthly_amounts"].get(cat, 0)
        items.append(_p(f"<b>{_e(fmt_idr(amount))}</b> per bulan ({snap['allocation'][cat]:.0%}) untuk "
                        f"<b>{_e(picks[0]['name'])}</b> ({_e(_cat_name(cat).lower())}).", "bullet", bulletText="-"))
    verdict = ("Perkiraan penurunan di tahun buruk" f" {fmt_pct(snap['stress_loss'] * 100)} berada "
               + ("dalam" if snap["within_limit"] else "<b>di luar</b>") + f" batas Anda (-{inputs['max_drop_pct']}%) menurut simulasi; "
               "kerugian nyata bisa lebih besar dan batas ini bukan jaminan.")
    items.append(_p(verdict, "bullet", bulletText="-"))
    return items


def _start_plan(budget: float) -> Table:
    steps = [("Bulan 1-3", 0.4), ("Bulan 4-6", 0.7), ("Bulan 7 dan seterusnya", 1.0)]
    cells = [[_p(_e(label.upper()), "label"), _p(f"<b>{_e(fmt_idr(budget * f))}</b>", "body", fontSize=14, leading=18),
              _p("per bulan", "kpisub")] for label, f in steps]
    t = Table([cells], colWidths=[CONTENT_W / 3] * 3)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("LINEBEFORE", (1, 0), (-1, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _footer(snap: dict):
    left = f"Kompas Investasi  |  Laporan rekomendasi  |  data produk per {_date_id(snap['data_as_of'])}"

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 9 * mm, left)
        canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"Halaman {doc.page}")
        canvas.restoreState()
    return draw


# ----------------------------------------------------------------------------- public API
def filename(snap: dict, current: bool = False) -> str:
    stamp = datetime.fromisoformat(snap["saved_at"]).strftime("%Y-%m-%d_%H%M")
    return f"laporan-rekomendasi_{'saat-ini_' if current else ''}{stamp}.pdf"


def build_pdf(snap: dict, current: bool = False) -> bytes:
    """Render the snapshot as an A4 PDF and return its bytes. `current` only changes the badge on the cover."""
    inputs, prof = snap["inputs"], snap["profile"]
    budget, horizon = inputs["monthly_budget"], inputs["horizon_years"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=20 * mm,
        title="Kompas Investasi - Laporan Rekomendasi", author="Kompas Investasi",
    )
    proj = snap.get("projection") or {}
    base_rate = (proj.get("rates") or {}).get("Dasar")
    kpis = [
        _kpi("Profil risiko", fmt_level(prof["level"]), prof["name"].capitalize()),
        _kpi("Perkiraan turun", fmt_pct(snap["stress_loss"] * 100), f"batas Anda -{inputs['max_drop_pct']}%"),
        _kpi("Dana per bulan", fmt_idr_short(budget), f"{fmt_idr_short(budget * 12 * horizon)} selama {horizon:g} tahun"),
    ]
    if base_rate is not None:
        fv = metrics.future_value_dca(budget, base_rate, horizon, initial=(snap.get("portfolio") or {}).get("total_now", 0.0))
        kpis.append(_kpi(f"Proyeksi {horizon:g} th (Dasar)", fmt_idr_short(fv),
                         f"daya beli sekarang {fmt_idr_short(metrics.deflate(fv, proj.get('inflation', 0.0), horizon))}"))
    else:
        kpis.append(_kpi("Tujuan", f"{horizon:g} tahun", "sampai target tercapai"))

    story: list = [_hero(snap, current), Spacer(1, 10), _kpi_row(kpis)]
    story += _section("Keputusan yang dianjurkan", "Langkah konkret per bulan berdasarkan profil risiko dan data produk di atas.")
    story += _decision_summary(snap)
    if snap.get("notes"):
        story += [Spacer(1, 4)] + [_p(f"<b>Perhatian:</b> {_e(n)}", "body", textColor=CRITICAL) for n in snap["notes"]]
    if snap.get("note"):
        story += [Spacer(1, 4), _p(f"<b>Catatan Anda:</b> {_e(snap['note'])}", "body")]

    story += _section("Pembagian dana", "Setoran bulan ini diarahkan ke jenis yang masih di bawah target portofolio Anda."
                      if snap.get("portfolio") else "Ke mana dana tiap bulan dibagi menurut komposisi profil risiko.")
    story += [_allocation_block(snap)]
    story += _portfolio_section(snap)
    story.append(CondPageBreak(60 * mm))
    story += _section("Batas risiko Anda", "Perkiraan turun dihitung dari simulasi tahun buruk, dibandingkan dengan batas yang Anda tetapkan.")
    crisis = snap.get("crisis")
    story += [_risk_drawing(snap["stress_loss"], inputs["max_drop_pct"] / 100, snap["within_limit"], whole=bool(snap.get("portfolio")),
                            crisis_loss=crisis["loss"] if crisis else None)]
    if crisis:
        sh = crisis["shocks"]
        def pct(value: float) -> str:
            return "0%" if abs(value) < 5e-4 else _e(fmt_pct(value * 100))

        story += [Spacer(1, 4), _p("<b>Krisis berat adalah asumsi, bukan data</b>: saham " + pct(sh.get("saham", 0)) + ", obligasi "
                     + pct(sh.get("pendapatan_tetap", 0)) + ", pasar uang " + pct(sh.get("pasar_uang", 0))
                     + ". Data produk hanya mencakup 1 tahun terakhir, jadi penurunan yang lebih dalam di masa lalu atau masa depan "
                     "belum tercermin di bar pertama. Bila bar kedua melewati batas Anda, itu sinyal untuk mempertimbangkan profil "
                     "yang lebih konservatif.", "small")]
    story += _section(f"Posisi di skala profil risiko Bibit", "Skala 1 (paling konservatif) sampai 10 (paling agresif).")
    story += [_scale_drawing(prof["level"])]

    story.append(CondPageBreak(75 * mm))
    story += _section("Produk pilihan", "Satu pilihan utama per jenis, dengan alternatif peringkat berikutnya. Data per "
                      f"{_date_id(snap['data_as_of'])}; cek halaman produk di Bibit sebelum membeli.")
    for cat, picks in snap["picks"].items():
        if picks:
            story.append(_product_card(cat, snap["allocation"].get(cat, 0), snap["monthly_amounts"].get(cat, 0), picks))

    projection = _projection_section(snap)
    if projection:
        story.append(CondPageBreak(135 * mm))
    story += projection
    story += _section("Cara memulai (bertahap)", "Setoran bertahap mengurangi risiko seluruh dana masuk di waktu yang kurang tepat.")
    story += [_start_plan(budget)]

    story += [Spacer(1, 14), HRFlowable(width="100%", thickness=0.6, color=LINE), Spacer(1, 6)]
    story += [_p("<b>Cara sistem memilih.</b> Profil risiko tertinggi yang perkiraan penurunannya masih di bawah batas Anda dan tidak "
                 "melebihi batas untuk lama tujuan. Produk disaring: bukan USD, dana kelolaan minimal Rp100 miliar, riwayat "
                 "3 tahun (kecuali pasar uang), lalu diperingkat per kategori. Tidak ada produk yang dipilih hanya karena "
                 "return tertinggi tahun lalu.", "small"), Spacer(1, 3),
              _p("<b>Keterbatasan.</b> Data hanya snapshot; penurunan terdalam hanya mencakup 1 tahun terakhir; sistem tidak membaca "
                 "prospektus (isi portofolio, biaya, durasi dan kualitas penerbit obligasi). Kinerja masa lalu dan proyeksi bukan jaminan hasil. Nilai reksa dana bisa "
                 "naik maupun turun.", "small")]
    footer = _footer(snap)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
