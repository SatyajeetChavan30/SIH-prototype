"""
Peak-outflow regressions for NATURAL (landslide, moraine, ice) dams — Phase 3.

Kept separate from ``jalraksha.terrain.breach`` on purpose. Every regression in
that module is fitted on constructed embankments, and its uncertainty bands are
Wahl (2004)'s embankment prediction intervals. Importing those bands here would
be a circular import and, worse, would state something untrue: predictions for
natural dams carry demonstrably wider scatter, because the dams are unengineered,
their internal structure and grain-size distribution are unknown, and the
surveyed case databases are smaller and less well constrained. So this module
carries its own bands, its own note, and its own quarantine flags, and
``breach.py`` imports it one way.

WHAT IS ACTIVE AND WHAT IS QUARANTINED

Costa (1985) is the only regression fitted across natural dams that this project
has transcribed and tested, so it is the only active family for a blockage run.
It lives in ``breach.py`` alongside the embankment set — it is used for both —
but a blockage run reads its uncertainty band from HERE, not from Wahl.

Walder & O'Connor (1997) and Peng & Zhang (2012) are implemented in SHAPE and
quarantined by an explicit ``*_VERIFIED = False`` flag, exactly as
``xu_zhang_2009_peak_outflow`` is. Their coefficients have not been transcribed
from the primary sources, and this project does not ship a number it has not
read. Calling either one raises until the flag flips. That is deliberate: a
placeholder coefficient that silently returns a plausible discharge is worse than
no equation at all, because nothing downstream can tell the difference.

THE COUPLING WORTH NOTING

Peng & Zhang needs a dam VOLUME and WIDTH, which no user-interface slider can
supply for a landslide that has not been surveyed. ``jalraksha.terrain.blockage``
produces both from the burned barrier geometry. The blockage scenario and the
DEM update are therefore not two features bolted together: the second is what
makes the first's inputs exist.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

#: Gravitational acceleration (m/s^2), for the dimensionless forms.
G = 9.81

#: Million cubic metres to cubic metres. Mirrors breach.MCM_TO_M3, duplicated
#: rather than imported so this module has no Phase 3 sibling dependency and can
#: be imported by breach.py without a cycle.
MCM_TO_M3 = 1.0e6

#: Whether the Walder & O'Connor (1997) coefficients have been transcribed from
#: the primary source and checked against its published cases. Until this is
#: True the equation raises rather than returning a number.
WALDER_OCONNOR_1997_VERIFIED = False

#: Same, for Peng & Zhang (2012).
PENG_ZHANG_2012_VERIFIED = False

#: Prediction-uncertainty bands for natural-dam peak outflow, in log10 cycles,
#: applied multiplicatively as [q * 10^-w, q * 10^+w].
#:
#: TODO: UNVETTED — every value here is a placeholder chosen only to EXCEED the
#: corresponding embankment band in breach.UNCERTAINTY_LOG_CYCLES, which is the
#: relationship the literature states. The published widths must be transcribed
#: from Costa (1985) USGS OFR 85-560, Costa & Schuster (1988) GSA Bulletin
#: 100(7):1054-1068, and Walder & O'Connor (1997) WRR 33(10):2337-2348.
#: Recorded in docs/VERIFICATION_LOG.md as queue items 21 and 22.
#:
#: Do NOT quote a single peak outflow from a blockage run. Quote the ensemble
#: range, and quote NATURAL_DAM_SCATTER_NOTE with it.
NATURAL_DAM_LOG_CYCLES: Dict[str, float] = {
    "costa_1985_natural": 0.75,   # TODO: UNVETTED — wider than macdonald's 0.51
    "walder_oconnor_1997": 0.70,  # TODO: UNVETTED — quarantined equation
    "peng_zhang_2012": 0.70,      # TODO: UNVETTED — quarantined equation
}

#: The sentence that has to travel with any natural-dam discharge this project
#: reports. Carried in every blockage ensemble member's metadata.
NATURAL_DAM_SCATTER_NOTE = (
    "Peak-outflow predictions for NATURAL dams (landslide, moraine, ice) carry "
    "wider published scatter than the constructed-embankment fits. The dams are "
    "unengineered, their internal structure and grain-size distribution are "
    "unknown, and the surveyed case databases are smaller. Costa & Schuster "
    "(1988) and Walder & O'Connor (1997) both report this. The bands applied "
    "here are wider than Wahl (2004)'s embankment bands by construction, but "
    "their exact widths are UNVETTED placeholders pending transcription "
    "(docs/VERIFICATION_LOG.md rows 21-22). Report the ensemble range, never a "
    "single discharge."
)

#: Regression families run for a river_blockage scenario. Costa (1985) alone
#: until the two quarantined equations are transcribed — it is the one
#: regression in the transcribed set whose fitting population included natural
#: dams, so it carries a blockage run honestly on its own, at the cost of a wide
#: band. The tuple is keyed to breach.synthesize_breach_ensemble's existing
#: regression_families parameter.
NATURAL_DAM_REGRESSION_FAMILIES: Tuple[str, ...] = ("costa",)

#: Uncertainty-band key a blockage run uses for Costa, instead of the
#: "macdonald_1984" embankment band breach.costa_1985_peak_outflow borrows by
#: default. Reusing an embankment band on a natural-dam equation understates the
#: spread; that pre-existing debt is verification queue row 22.
COSTA_NATURAL_BAND_KEY = "costa_1985_natural"

#: Dam classes these regressions were fitted on. A blockage run INVERTS the
#: sense of breach.dam_class_outside_fitted_population: for a landslide dam it is
#: the embankment families that are out of population, not this one.
FITTED_NATURAL_DAM_CLASSES: Tuple[str, ...] = ("landslide", "moraine", "natural", "ice")


class NaturalDamRegressionUnverified(NotImplementedError):
    """Raised when a quarantined natural-dam regression is called."""


def natural_dam_bounds(
    q_central: float,
    equation_key: str,
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    Attach a natural-dam prediction band to a central estimate.

    Same multiplicative form as ``breach._wahl_bounds`` — a band of +/- w log10
    cycles is [q * 10^-w, q * 10^+w] — but drawn from NATURAL_DAM_LOG_CYCLES.
    The two are deliberately not the same function: sharing one would make it a
    one-line change to apply an embankment band to a landslide dam, which is
    precisely the mistake this module exists to prevent.

    Args:
        q_central: Central peak outflow, m^3/s.
        equation_key: Key into NATURAL_DAM_LOG_CYCLES.
        mode: "central" | "lower" | "upper" — which value to return first.

    Returns:
        (value, lower, upper). ``value`` is selected by ``mode``; ``lower`` and
        ``upper`` always describe the full band.
    """
    if equation_key not in NATURAL_DAM_LOG_CYCLES:
        raise KeyError(
            f"No natural-dam uncertainty band for {equation_key!r}. Known keys: "
            f"{sorted(NATURAL_DAM_LOG_CYCLES)}. A missing band must not silently "
            f"fall back to a default width."
        )
    log_cycles = NATURAL_DAM_LOG_CYCLES[equation_key]
    factor = 10.0**log_cycles
    q_low = float(q_central) / factor
    q_high = float(q_central) * factor
    if mode == "lower":
        return q_low, q_low, q_high
    if mode == "upper":
        return q_high, q_low, q_high
    return float(q_central), q_low, q_high


def dam_class_outside_fitted_population(dam_type: str) -> bool:
    """
    Whether a dam class sits outside the natural-dam regressions' fitted set.

    The mirror image of ``breach.dam_class_outside_fitted_population``. Running a
    blockage scenario on an engineered embankment or gravity dam is the
    extrapolation here, not the other way round.
    """
    return str(dam_type or "").strip().lower() not in FITTED_NATURAL_DAM_CLASSES


def walder_oconnor_1997_peak_outflow(
    height_m: float,
    lake_volume_m3: float,
    breach_erosion_rate_m_s: float | None = None,
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    Walder & O'Connor (1997) peak outflow — QUARANTINED, coefficients untranscribed.

    Source: Walder, J.S. & O'Connor, J.E. (1997), "Methods for predicting peak
    discharge of floods caused by failure of natural and constructed earth dams",
    Water Resources Research 33(10):2337-2348.

    THE STRUCTURE, which is what is implemented here in shape only: the paper
    frames peak outflow through a dimensionless parameter comparing the rate at
    which the breach downcuts against the rate at which the lake draws down. Two
    limiting regimes follow.

      - LARGE-RESERVOIR / RAPID-BREACH limit. The lake level barely falls while
        the breach forms, so the peak is set by breach hydraulics — essentially
        weir flow through the fully formed opening — and is nearly independent of
        lake volume.

      - SMALL-RESERVOIR / SLOW-BREACH limit. The lake empties as fast as the
        breach grows, so the peak is set by the drainable volume and the
        drainable depth, and is nearly independent of the erosion rate.

    Real events sit between the two, and the paper gives the blending. What is
    NOT reproduced here is any coefficient: the numerical constants, the exact
    definition of the dimensionless erosion parameter, and the erosion-rate
    values tabulated for different dam materials all have to be read off the
    paper. Writing plausible constants from memory would produce a discharge that
    looks like a Walder & O'Connor result and is not one.

    TODO: UNVETTED — transcribe both limiting regimes, the blending parameter,
    and the tabulated erosion rates from W&O (1997). Record the fitted case count
    and height range while doing so. docs/VERIFICATION_LOG.md row 19. Flip
    WALDER_OCONNOR_1997_VERIFIED when done and add an exact-formula test in the
    style of TestUnits::test_froehlich_matches_published_formula_exactly.

    Raises:
        NaturalDamRegressionUnverified: always, until the flag above is True.
    """
    if not WALDER_OCONNOR_1997_VERIFIED:
        raise NaturalDamRegressionUnverified(
            "Walder & O'Connor (1997) peak outflow is implemented in shape only; "
            "its coefficients have not been transcribed from Water Resources "
            "Research 33(10):2337-2348. It is excluded from the default "
            "natural-dam ensemble and cannot be called. See "
            "docs/VERIFICATION_LOG.md row 19."
        )

    # Unreachable until transcription; kept so the signature and the units are
    # already fixed for whoever does it.
    raise NaturalDamRegressionUnverified(  # pragma: no cover
        "WALDER_OCONNOR_1997_VERIFIED was set True but no coefficients were "
        "transcribed. Implement the two limiting regimes before flipping the flag."
    )


def peng_zhang_2012_peak_outflow(
    dam_height_m: float,
    dam_width_m: float,
    dam_volume_m3: float,
    lake_volume_m3: float,
    erodibility: str = "medium",
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    Peng & Zhang (2012) landslide-dam breaching — QUARANTINED, untranscribed.

    Source: Peng, M. & Zhang, L.M. (2012), "Breaching parameters of landslide
    dams", Landslides 9(1):13-31.

    THE STRUCTURE: the same dimensionless style as Xu & Zhang (2009) from the
    same group — peak outflow non-dimensionalised as

        Q_p / (g^0.5 * H_d^2.5)

    expressed as an exponential of a linear combination of dimensionless dam
    height, dam width, dam volume, lake volume and an erodibility class term.
    Every coefficient in that combination, and the encoding of the erodibility
    and dam-shape classes, must come from the paper.

    WHY THIS ONE IS WORTH FINISHING. It is the only regression in the set whose
    inputs match what a blockage run actually knows: dam volume and dam width are
    exactly the two quantities ``jalraksha.terrain.blockage.burn_barrier``
    produces from the burned deposit, and neither is available for a landslide
    dam any other way. Xu & Zhang (2009) is quarantined in breach.py for the same
    untranscribed-coefficients reason and over-predicts Teton by 5.6x, so do not
    assume this sibling equation is close either until it is scored.

    TODO: UNVETTED — transcribe the regression coefficients and the
    erodibility/shape class encodings from Landslides 9(1):13-31.
    docs/VERIFICATION_LOG.md row 20.

    Raises:
        NaturalDamRegressionUnverified: always, until PENG_ZHANG_2012_VERIFIED.
    """
    if not PENG_ZHANG_2012_VERIFIED:
        raise NaturalDamRegressionUnverified(
            "Peng & Zhang (2012) landslide-dam peak outflow is implemented in "
            "shape only; its coefficients have not been transcribed from "
            "Landslides 9(1):13-31. It is excluded from the default natural-dam "
            "ensemble and cannot be called. See docs/VERIFICATION_LOG.md row 20."
        )

    raise NaturalDamRegressionUnverified(  # pragma: no cover
        "PENG_ZHANG_2012_VERIFIED was set True but no coefficients were "
        "transcribed. Implement the dimensionless form before flipping the flag."
    )


def dimensionless_peak_outflow(q_peak_m3_s: float, dam_height_m: float) -> float:
    """
    ``Q_p / (g^0.5 * H_d^2.5)`` — the form the Zhang-group equations report in.

    Useful independently of those equations: it is how a landslide-dam discharge
    is compared against a published case of a different size, and it is
    computable from what a blockage run already has.
    """
    height = float(dam_height_m)
    if height <= 0.0:
        raise ValueError(f"dam_height_m must be positive, got {dam_height_m}")
    return float(q_peak_m3_s) / (np.sqrt(G) * height**2.5)
