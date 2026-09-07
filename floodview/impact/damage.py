"""
Depth-damage analysis for economic impact assessment (Phase 6).

Converts an inundation depth field plus an EXPOSURE field into a monetary
damage figure. Two things about this module are deliberate and load-bearing.

WHAT WAS DELETED, AND WHY. The previous version carried a ``DepthDamageAnalyzer``
class whose coefficients were attributed to "Graham (2009), a comprehensive
study for the Uttarakhand region", complete with r-squared values of 0.82,
0.79 and 0.75. No such study appears in this project's ``literature.md`` or in
any bibliography here; the only Graham is the 1999 USBR report on FATALITY
rates, which is a different quantity entirely. A goodness-of-fit statistic
attached to a fit that was never performed is a fabricated credential, so the
coefficients, the r-squared values and the class that held them are gone rather
than relabelled. Deleted with them: three fixed asset baselines (125 / 85 / 45
crore) that were identical for every dam in the country and derived from
nothing, an assumed population density of 450 persons/km2, and two hardcoded
200 m cell areas that silently ignored the run's actual resolution.

EXPOSURE COMES FROM THE CATCHMENT, NOT FROM A CONSTANT. Damage is
``ratio(depth) x exposure x unit_cost``. The exposure term is GHSL
built-up SURFACE (m2 per cell) or WorldCover cropland area, both fetched onto
the solver's own grid — so it varies with the site, which is the whole point.
The unit cost term is a constant, is UNVETTED, and is ECHOED IN EVERY RESULT so
a reader can divide it back out and substitute their own. That echo is not
decoration: it is what makes a figure whose cost basis is unverified still
useful.

THE CURVE IS NOT PUBLISHED AND SAYS SO. ``compute_depth_damage`` is a
saturating exponential ``r(d) = 1 - exp(-k*d)`` with three unsourced rate
constants. It is monotonic, bounded and zero at zero depth, which is enough to
ORDER cells by damage; it is not a calibrated loss function and no result from
it is published without ``model_is_published: False``. This mirrors
``impact/fatality.py::estimate_loss_of_life_depth_velocity``, for the same
reason: a plausible number under a published author's name is worse than an
obviously provisional one.

THE PUBLISHED ALTERNATIVE IS PRESENT IN SHAPE AND QUARANTINED. Huizinga et al.
(2017), the JRC global depth-damage curves, is the fallback ``literature.md``
identifies for the India-specific curves nobody has located (verification queue
row 10). Its structure is here; its tables are not transcribed, so it is held
behind ``HUIZINGA_2017_VERIFIED = False`` exactly as ``fatality.py`` holds
Jonkman (2008) and ``terrain/natural_dam.py`` holds Walder & O'Connor (1997)
and Peng & Zhang (2012).

NO EARTH ENGINE IMPORTS HERE. Impact is Phase 6 and ``floodview.gee`` is
Phase 9; importing upward would violate the dependency direction in CLAUDE.md's
Architecture Rules and would make this module untestable offline. The service
layer fetches the exposure rasters and passes arrays in, the same seam
``tasks.py::_population_at_risk`` already uses for GHSL population.

References:
  - Huizinga, J., de Moel, H., Szewczyk, W. (2017) "Global flood depth-damage
    functions: methodology and the database with guidelines", EUR 28552 EN,
    JRC. (literature.md ref 31 — NOT transcribed, see below.)
  - Pesaresi, M. & Politis, P. (2023) "GHS-BUILT-S R2023A", European
    Commission JRC. (Supplies the exposure term.)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Damage ratio curve
# ─────────────────────────────────────────────────────────────────────────────

# TODO: UNVETTED — the three rate constants below have no published source.
# They are the shape parameters of a saturating exponential chosen so that the
# curve is monotonic, bounded in [0, 1] and zero at zero depth, with damage
# rising fastest for residential and slowest for agricultural land. That
# ordering is defensible; the VALUES are not, and no primary source is cited
# for them because none was used.
#
# What would close this: the India-specific depth-damage curves that
# literature.md section 7.1 flags as "the largest gap" (search NIH Roorkee, IIT
# publications, DRIP reports, World Bank India flood-risk studies), or failing
# that the Huizinga (2017) JRC tables for Asia, whose structure is already
# present below in `huizinga_2017_damage_fraction`.
#
# docs/VERIFICATION_LOG.md row 36.
_SECTOR_RATE = {
    "residential": 0.8,
    "non_residential": 0.7,
    "agricultural": 0.6,
}

#: Sector names this module accepts. "infrastructure" and "total" were accepted
#: by the previous version; "infrastructure" is now "non_residential" (the name
#: of the GHS-BUILT-S band that supplies its exposure), and "total" is gone
#: because a damage ratio for "everything at once" is not a curve, it is an
#: average of curves weighted by an exposure mix nobody stated.
SECTORS = tuple(_SECTOR_RATE)


class UnknownSectorError(ValueError):
    """
    A sector name with no depth-damage curve was requested.

    Raised rather than defaulting. The previous version did
    ``_SECTOR_RATE.get(sector, 0.8)``, so a typo'd or renamed sector silently
    received the RESIDENTIAL curve and the result carried the wrong sector's
    name back to the caller.
    """


def compute_depth_damage(depths, sector: str = "residential") -> np.ndarray:
    """
    Normalised depth-damage ratio (0-1) as a function of inundation depth.

    Uses a saturating exponential ``r(d) = 1 - exp(-k*d)`` with a
    sector-dependent rate constant. Monotonic non-decreasing, ``r(0) = 0``,
    asymptotic to 1. UNPUBLISHED — see the module docstring.

    Args:
        depths: Scalar or array of inundation depths (m).
        sector: One of :data:`SECTORS`.

    Returns:
        Damage ratio array in [0, 1].

    Raises:
        UnknownSectorError: for any sector without a curve.
    """
    if sector not in _SECTOR_RATE:
        raise UnknownSectorError(
            f"No depth-damage curve for sector {sector!r}. "
            f"Known sectors: {', '.join(SECTORS)}."
        )
    depths = np.asarray(depths, dtype=np.float64)
    return 1.0 - np.exp(-_SECTOR_RATE[sector] * depths)


def calculate_economic_loss(
    depth: np.ndarray,
    asset_grid: np.ndarray,
    sector: str = "residential",
    cell_area_m2: float = 400.0,
) -> Dict[str, Any]:
    """
    Economic loss from inundation depth and a per-AREA asset value.

    ``Loss_cell = ratio(d) * asset_value_per_m2 * cell_area_m2``.

    The currency is the CALLER'S: ``asset_grid`` is a value per m2 in whatever
    unit the caller holds, and this function cannot know which. That is why the
    returned key is ``total_loss`` and not ``total_loss_crore_inr``. For a
    rupee figure derived from a fetched exposure raster, use
    :func:`estimate_sector_damage`, which owns the INR unit costs and states
    them.

    Note the distinction from :func:`estimate_sector_damage`: here the asset
    grid is a DENSITY (value per m2) so multiplying by cell area is right;
    there the exposure grid is already an AREA PER CELL so multiplying by cell
    area would square it.

    Args:
        depth: Inundation depth grid (m).
        asset_grid: Asset value per m2, caller's currency.
        sector: One of :data:`SECTORS`.
        cell_area_m2: Cell area (m2).

    Returns:
        Dict with total_loss, damaged_cell_count, mean_damage_ratio, etc.
    """
    depth = np.asarray(depth, dtype=np.float64)
    asset_grid = np.asarray(asset_grid, dtype=np.float64)

    flooded = depth > 0.0
    ratios = compute_depth_damage(depth, sector=sector)
    cell_loss = ratios * asset_grid * cell_area_m2

    total_loss = float(np.sum(cell_loss[flooded])) if np.any(flooded) else 0.0
    damaged_cell_count = int(np.sum(flooded))
    mean_damage_ratio = float(np.mean(ratios[flooded])) if np.any(flooded) else 0.0

    return {
        "total_loss": total_loss,
        "damaged_cell_count": damaged_cell_count,
        "mean_damage_ratio": mean_damage_ratio,
        "sector": sector,
        "cell_area_m2": cell_area_m2,
        "currency": "caller-defined (asset_grid units per m2)",
        "model": "saturating_exponential_depth_damage",
        "model_is_published": False,
        "source_note": (
            "UNVETTED — the depth-damage rate constants are unpublished shape "
            "parameters, not calibrated loss functions. "
            "docs/VERIFICATION_LOG.md row 36."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Unit costs
# ─────────────────────────────────────────────────────────────────────────────
#
# TODO: UNVETTED — every constant in this section is an order-of-magnitude
# placeholder, not a sourced figure, and each is echoed in the result payload
# so a reader can rescale it. A currency value with no price year is not a
# value, so each carries one.
#
# What would close these:
#   * Residential / non-residential: CPWD plinth-area rates for the relevant
#     state and building class, or a published Indian flood-damage study
#     quoting reconstruction cost per m2 with its price year and its
#     definition of "damage" (repair vs replacement — these differ by a
#     factor of several and this module does not currently distinguish them).
#   * Cropland: a state agricultural department or ICAR figure for gross value
#     of output per hectare on the relevant cropping pattern, with the
#     proportion of a season's value lost to a single inundation event stated
#     separately — this constant currently conflates the two.
#
# docs/VERIFICATION_LOG.md row 35.

#: Reconstruction cost of residential built-up surface, INR per m2.
UNIT_RECONSTRUCTION_COST_RESIDENTIAL_INR_PER_M2 = 20000.0
UNIT_RECONSTRUCTION_COST_RESIDENTIAL_PRICE_YEAR = 2023

#: Reconstruction cost of non-residential built-up surface, INR per m2.
UNIT_RECONSTRUCTION_COST_NON_RESIDENTIAL_INR_PER_M2 = 25000.0
UNIT_RECONSTRUCTION_COST_NON_RESIDENTIAL_PRICE_YEAR = 2023

#: Value of cropland lost to a single inundation, INR per m2. A DIFFERENT
#: QUANTITY from the two above — an annual output value, not a reconstruction
#: cost — which is why it does not share their name.
CROP_VALUE_INR_PER_M2 = 12.0
CROP_VALUE_PRICE_YEAR = 2023

_UNIT_COST = {
    "residential": (UNIT_RECONSTRUCTION_COST_RESIDENTIAL_INR_PER_M2,
                    UNIT_RECONSTRUCTION_COST_RESIDENTIAL_PRICE_YEAR,
                    "reconstruction cost of built-up surface"),
    "non_residential": (UNIT_RECONSTRUCTION_COST_NON_RESIDENTIAL_INR_PER_M2,
                        UNIT_RECONSTRUCTION_COST_NON_RESIDENTIAL_PRICE_YEAR,
                        "reconstruction cost of built-up surface"),
    "agricultural": (CROP_VALUE_INR_PER_M2,
                     CROP_VALUE_PRICE_YEAR,
                     "annual value of output on inundated cropland"),
}

#: 1 crore = 10^7 rupees.
_CRORE = 1.0e7

#: Damage is reported as a band, not a point. The width is a judgement about
#: how far an unpublished curve on an unvetted unit cost can be trusted, not a
#: propagated uncertainty — nothing here has a published variance to propagate.
#: TODO: UNVETTED. docs/VERIFICATION_LOG.md row 35.
UNCERTAINTY_FRACTION = 0.30


# ─────────────────────────────────────────────────────────────────────────────
# The sector estimate that reaches the dashboard
# ─────────────────────────────────────────────────────────────────────────────


def estimate_sector_damage(
    depth: np.ndarray,
    exposure_m2: np.ndarray,
    sector: str,
    unit_cost_inr_per_m2: Optional[float] = None,
    depth_threshold_m: float = 0.1,
) -> Dict[str, Any]:
    """
    Damage in crore INR for one sector, from depth and exposed AREA per cell.

    ``exposure_m2`` is square metres of the asset INSIDE each cell — GHS-BUILT-S
    surface for the built sectors, cropland fraction times cell area for
    agriculture. It is NOT a density, so it is not multiplied by the cell area:
    doing so would square the area term and inflate the result by the cell area
    itself (40,000x at 200 m). This is the single most consequential unit
    convention in the module and there is a test pinning it.

    Cells below ``depth_threshold_m`` contribute nothing. The threshold matches
    ``impact/population.py::compute_population_exposure``, so "exposed" means
    the same depth in the damage figure and the headcount beside it.

    Args:
        depth: Maximum inundation depth grid (m), shape [ny, nx].
        exposure_m2: Asset area per cell (m2), same shape.
        sector: One of :data:`SECTORS`.
        unit_cost_inr_per_m2: Override for the sector's unit cost. Provided so
            a caller can substitute a sourced figure without editing this
            module; the value used is always echoed back.
        depth_threshold_m: Depth below which a cell is treated as unaffected.

    Returns:
        Dict of SCALARS only — no arrays, because this payload is serialised
        into ``impact.json`` and read back by the dashboard.

    Raises:
        UnknownSectorError: for any sector without a curve.
        ValueError: if the two grids do not describe the same domain.
    """
    if sector not in _UNIT_COST:
        raise UnknownSectorError(
            f"No unit cost for sector {sector!r}. "
            f"Known sectors: {', '.join(SECTORS)}."
        )

    depth = np.asarray(depth, dtype=np.float64)
    exposure_m2 = np.asarray(exposure_m2, dtype=np.float64)
    if depth.shape != exposure_m2.shape:
        raise ValueError(
            f"Depth grid {depth.shape} and exposure grid {exposure_m2.shape} "
            f"describe different domains; refusing to broadcast them."
        )

    default_cost, price_year, cost_basis = _UNIT_COST[sector]
    unit_cost = float(default_cost if unit_cost_inr_per_m2 is None
                      else unit_cost_inr_per_m2)

    wet = depth >= depth_threshold_m
    ratios = compute_depth_damage(depth, sector=sector)

    exposed_m2 = float(np.sum(exposure_m2[wet]))
    damaged_m2 = float(np.sum(ratios[wet] * exposure_m2[wet]))
    damage_inr = damaged_m2 * unit_cost
    damage_crore = damage_inr / _CRORE

    # Exposure-weighted mean ratio: the plain mean over wet cells would weight
    # an empty hillside cell the same as a city block, and the resulting
    # "average damage ratio" would describe the domain rather than the assets.
    mean_ratio = (damaged_m2 / exposed_m2) if exposed_m2 > 0.0 else 0.0

    return {
        "sector": sector,
        "damage_crore_inr": damage_crore,
        "damage_lower_crore_inr": damage_crore * (1.0 - UNCERTAINTY_FRACTION),
        "damage_upper_crore_inr": damage_crore * (1.0 + UNCERTAINTY_FRACTION),
        "uncertainty_applied": f"±{UNCERTAINTY_FRACTION * 100:.0f}%",
        "exposed_area_m2": exposed_m2,
        "exposed_area_km2": exposed_m2 / 1.0e6,
        "damage_equivalent_area_m2": damaged_m2,
        "exposure_weighted_damage_ratio": mean_ratio,
        "flooded_cells": int(np.count_nonzero(wet)),
        "depth_threshold_m": depth_threshold_m,
        "unit_cost_inr_per_m2": unit_cost,
        "unit_cost_price_year": price_year,
        "unit_cost_basis": cost_basis,
        "unit_cost_is_default": unit_cost_inr_per_m2 is None,
        "curve_rate_constant": _SECTOR_RATE[sector],
        "model": "saturating_exponential_depth_damage",
        "model_is_published": False,
        "model_note": (
            "Damage = (1 - exp(-k*depth)) x exposed area x unit cost. The "
            "curve is an unpublished saturating exponential, not a calibrated "
            "loss function, and the unit cost is an UNVETTED placeholder — it "
            "is echoed above so the figure can be rescaled. Treat this as an "
            "ordering of severity and an order of magnitude, not an appraisal. "
            "docs/VERIFICATION_LOG.md rows 35 and 36."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Huizinga et al. (2017) — present in shape, QUARANTINED
# ─────────────────────────────────────────────────────────────────────────────
#
# The JRC global depth-damage functions are the published fallback that
# literature.md section 7.1 names for the India-specific curves nobody has
# located, and they are what verification queue row 10 asks for. The structure
# is here so the seam exists; the TABLES ARE NOT TRANSCRIBED.
#
# Set this True ONLY after the Asia continental curves have been transcribed
# from EUR 28552 EN against the published tables, with the damage-fraction
# breakpoints, the depth breakpoints and the maximum-damage values entered per
# occupancy class. Huizinga's tables are piecewise-linear in depth with
# per-continent, per-class damage fractions; applying one continent's curve to
# another shifts a damage figure substantially while still producing a
# perfectly plausible number — which is the same trap
# `fatality.py::JONKMAN_2008_VERIFIED` exists to hold shut.
#
# docs/VERIFICATION_LOG.md row 10.
HUIZINGA_2017_VERIFIED = False


class DepthDamageCurveUnverified(NotImplementedError):
    """A published depth-damage curve was requested before transcription."""


def huizinga_2017_damage_fraction(
    depth: np.ndarray,
    occupancy_class: str = "residential",
    continent: str = "Asia",
) -> np.ndarray:
    """
    JRC global depth-damage function (Huizinga et al. 2017) — NOT AVAILABLE.

    Piecewise-linear damage fraction in depth, per occupancy class and
    continent, to be applied against a maximum damage value per m2.

    Raises:
        DepthDamageCurveUnverified: always, while
            :data:`HUIZINGA_2017_VERIFIED` is False.
    """
    if not HUIZINGA_2017_VERIFIED:
        raise DepthDamageCurveUnverified(
            "Huizinga et al. (2017) JRC depth-damage curves are implemented in "
            "shape only: the piecewise-linear tables from EUR 28552 EN have "
            "not been transcribed, and the continental maximum-damage values "
            "have not been converted to INR at a stated price year. Applying "
            f"a curve for {continent}/{occupancy_class} from untranscribed "
            "tables would produce a plausible figure under a published "
            "author's name, which is the specific failure this quarantine "
            "prevents. Use compute_depth_damage / estimate_sector_damage "
            "instead — they are unpublished and say so. "
            "See docs/VERIFICATION_LOG.md row 10."
        )
    raise AssertionError(
        "HUIZINGA_2017_VERIFIED was set True without an implementation. "
        "Transcribe the EUR 28552 EN tables before flipping the flag."
    )
