"""Rule engine: turns metrics + user profile into plain-language observations.

Deliberately never says "buy product X because it returned Y". Past returns do not predict future ones.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from . import metrics
from .recommend import horizon_level_cap, level_of

CATEGORIES = ["pasar_uang", "pendapatan_tetap", "campuran", "saham", "sbn"]

PROFILES_FILE = Path(__file__).parent.parent / "data" / "risk_profiles.json"


def load_profiles() -> dict[str, dict[str, float]]:
    """Bibit robo levels 1-10 as recorded by the user in data/risk_profiles.json (only 4.5 and 5 checked
    against the app). Each level must sum to 1.0 and use known categories.
    """
    raw = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    profiles = {k: v for k, v in raw.items() if not k.startswith("_")}
    for name, alloc in profiles.items():
        unknown = set(alloc) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"Profil '{name}' memakai kategori tidak dikenal: {sorted(unknown)}")
        if abs(sum(alloc.values()) - 1.0) > 1e-6:
            raise ValueError(f"Profil '{name}' harus berjumlah 1.0 (sekarang {sum(alloc.values()):.2f})")
        profiles[name] = {c: float(alloc.get(c, 0.0)) for c in CATEGORIES}
    return profiles

DRIFT_THRESHOLD = 0.10
CONCENTRATION_THRESHOLD = 0.50


@dataclass
class Profile:
    level_key: str  # key of a Bibit level in data/risk_profiles.json, e.g. "bibit_4.5_moderat"
    horizon_years: float
    monthly_expense: float
    emergency_fund_months_target: int = 6
    monthly_budget: float = 0.0


@dataclass
class Finding:
    level: str  # info | perhatian | penting
    title: str
    detail: str


def target_allocation(profile: Profile) -> dict[str, float]:
    """Allocation of the chosen Bibit level; if the goal is too short for it, the highest level within the horizon cap."""
    profiles = load_profiles()
    cap = horizon_level_cap(profile.horizon_years)
    level = level_of(profile.level_key)
    if level is not None and level > cap:
        allowed = [k for k in profiles if (level_of(k) or float("inf")) <= cap]
        return dict(profiles[max(allowed, key=level_of)])
    return dict(profiles[profile.level_key])


def evaluate(
    profile: Profile,
    transactions: pd.DataFrame,
    holdings: pd.DataFrame,
    as_of: date,
) -> list[Finding]:
    findings: list[Finding] = []
    total = float(holdings["current_value"].sum())
    if total <= 0:
        return [Finding("info", "Belum ada aset", "Isi data holdings terlebih dahulu.")]

    by_cat = metrics.allocation_by(holdings, "category")
    by_prod = metrics.allocation_by(holdings, "product")

    # 1. Emergency fund (pasar uang is the usual parking place)
    needed = profile.monthly_expense * profile.emergency_fund_months_target
    liquid = float(holdings.loc[holdings["category"] == "pasar_uang", "current_value"].sum())
    if needed > 0 and liquid < needed:
        findings.append(Finding(
            "penting", "Dana darurat belum penuh",
            f"Target {profile.emergency_fund_months_target} bulan pengeluaran = Rp{needed:,.0f}; "
            f"di pasar uang baru Rp{liquid:,.0f}. Dana darurat idealnya terpenuhi sebelum menambah aset berisiko.",
        ))

    # 2. Concentration
    top_name, top_share = by_prod.index[0], float(by_prod.iloc[0])
    if len(by_prod) > 1 and top_share > CONCENTRATION_THRESHOLD:
        findings.append(Finding(
            "perhatian", "Terlalu terkonsentrasi di satu produk",
            f"{top_name} = {top_share:.0%} dari portofolio.",
        ))
    elif len(by_prod) == 1:
        findings.append(Finding(
            "info", "Baru satu produk",
            "Wajar untuk awal. Seiring bertambahnya dana, pertimbangkan sebar ke jenis aset sesuai tujuan.",
        ))

    # 3. Drift vs target
    target = target_allocation(profile)
    for cat in CATEGORIES:
        actual = float(by_cat.get(cat, 0.0))
        diff = actual - target[cat]
        if abs(diff) > DRIFT_THRESHOLD:
            arah = "di atas" if diff > 0 else "di bawah"
            findings.append(Finding(
                "perhatian", f"Alokasi {cat} {arah} acuan",
                f"Saat ini {actual:.0%}, acuan profil risiko Anda {target[cat]:.0%} (selisih {diff:+.0%}). "
                "Acuan mengikuti komposisi profil risiko Anda; geser bertahap lewat setoran berikutnya.",
            ))

    # 4. Contribution consistency
    n = metrics.months_with_buys(transactions, as_of, window=6)
    if n < 4:
        findings.append(Finding(
            "info", "Setoran belum rutin",
            f"Hanya {n} dari 6 bulan terakhir ada pembelian. Setoran rutin kecil biasanya lebih berguna daripada setoran besar sesekali.",
        ))

    # 5. Risk vs horizon
    saham = float(by_cat.get("saham", 0.0))
    if profile.horizon_years < 3 and saham > 0.20:
        findings.append(Finding(
            "penting", "Aset saham besar untuk tujuan jangka pendek",
            f"Saham {saham:.0%} padahal tujuan < 3 tahun. Produk saham bisa turun 20% atau lebih dalam waktu singkat.",
        ))

    return findings
