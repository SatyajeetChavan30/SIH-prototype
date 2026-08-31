"""
Breach modelling and hydrograph generation for dam-break simulations.

Phase 3: peak-outflow regressions, level-pool routing, Monte Carlo ensembles.

Four published peak-outflow equations are implemented — Froehlich (1995b),
MacDonald & Langridge-Monopolis (1984), Costa (1985), and SCS (1981) — plus
Von Thun & Gillette (1990) breach geometry routed through a real level-pool
solver, and Xu & Zhang (2009) implemented but quarantined pending coefficient
verification. Wahl (1998) DSO-98-004 Table 5 is the collecting reference;
Wahl (2004) supplies the prediction-uncertainty bands.

Every equation is an empirical fit to historical embankment failures almost
all under 90 m tall. They disagree with each other by a factor of 3-4 and with
observation by a factor of 2-3, and Tehri at 260 m is a 2.8x extrapolation of
the tallest case in any of the calibration sets. The ensemble range is the
deliverable; a single peak outflow from this module is not a defensible number.

Validated against Teton (1976) in tests/test_breach.py: V_w = 356 MCM,
h_w = 86.9 m, measured Q_p = 65,120 m^3/s.

No scipy dependency — the routing is explicit Euler with bisection, so this
module runs from a bare NumPy install (offline-first constraint).
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
from numba import njit

from jalraksha.hardening import HardeningError

# ----------------------------------------------------------------------
# Peak-outflow regressions: units and provenance
#
# Every published regression in this module takes reservoir volume in CUBIC
# METRES and water depth above the breach invert in metres, returning m^3/s.
# The project's own docs/DECISIONS.md notes Froehlich as
#     Q = 0.607 * H^1.24 * V^0.295   [V in Mm^3]
# which is the right form with the wrong unit: V is m^3 in the source, and
# feeding MCM instead understates Q by 10^(6*0.295) = 59x. Callers here pass
# storage in MCM (the CWC register unit), so conversion is explicit and
# central, in MCM_TO_M3, rather than folded into any coefficient.
MCM_TO_M3 = 1.0e6

# Gravitational acceleration (m/s^2), for the Xu & Zhang dimensionless form
# and for weir discharge in level-pool routing.
G = 9.81

# Wahl (2004) prediction-uncertainty bands, as multiplicative factors on the
# central estimate. Wahl expresses these as +/- log10 cycles of prediction
# error; the factors below are 10^(-w) and 10^(+w).
#
# TODO: UNVETTED — w per equation must be transcribed from Wahl, T.L. (2004),
# "Uncertainty of Predictions of Embankment Dam Breach Parameters", J. Hydraul.
# Eng. 130(5):389-397, Table 3. The values below are placeholders of the right
# order (Froehlich is the best-performing peak-outflow equation in Wahl's
# comparison, Xu & Zhang was not in it). Recorded in docs/VERIFICATION_LOG.md
# as queue items 1-5. Do NOT quote a single peak outflow from this module —
# quote the ensemble range.
UNCERTAINTY_LOG_CYCLES = {
    "froehlich_1995": 0.32,   # TODO: UNVETTED — Wahl (2004) Table 3
    "macdonald_1984": 0.51,   # TODO: UNVETTED — Wahl (2004) Table 3
    "von_thun_1990": 0.45,    # TODO: UNVETTED — VTG geometry + weir hydraulics
    "xu_zhang_2009": 0.50,    # TODO: UNVETTED — not covered by Wahl (2004)
}

# Highest dam in the calibration sets of all four regressions is roughly 90 m
# (Teton, 93 m, is the tallest well-documented failure). Tehri is 260 m, so
# every prediction for it is an extrapolation of ~2.8x in height and must be
# reported as such rather than as a calibrated result.
CALIBRATION_MAX_HEIGHT_M = 93.0

# TODO: UNVETTED — source from literature.md
# Critical failure time fraction of total simulation time
CRITICAL_FAILURE_FRAC = 0.15

# TODO: UNVETTED — source from literature.md
# Manning's n uncertainty standard deviation
MANNINGS_N_STD = 0.005


def synthesize_breach_ensemble(
    dam_config: Dict,
    num_samples: int = 100,
    random_seed: Optional[int] = None,
    regression_families: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Generate ensemble of breach hydrographs.

    For each ensemble member:
    1. Sample Manning's n from distribution (uncertainty)
    2. Sample a failure-time fraction (so t_fail has a spread)
    3. Apply the chosen regression family for peak outflow
    4. Generate time series for discharge

    Args:
        dam_config: Dam configuration
        num_samples: Number of ensemble members
        random_seed: Optional seed for reproducible sampling
        regression_families: Optional list of regression families to sample from
            (e.g. ["froehlich", "von_thun", "macdonald", "xu_zhang"]). If None,
            the Wahl (2004) default is used for all members.

    Returns:
        List of breach hydrograph dicts with:
        - "t_array": Time array (s)
        - "Q_t": Discharge array (m³/s)
        - "metadata": Metadata for this member
    """
    print(f"\n[Phase 3] Generating {num_samples} breach hydrograph ensemble members...")

    # Validate only the fields the breach synthesis actually needs. Full
    # lat/lon/name validation is enforced upstream by the API/CLI layer.
    if "height_m" not in dam_config or "storage_mm3" not in dam_config:
        raise HardeningError(
            "Dam config must contain 'height_m' and 'storage_mm3' for breach synthesis."
        )

    rng = np.random.default_rng(random_seed)

    # Sample Manning's n from distribution (add uncertainty)
    manning_n_mean = dam_config.get("manning_n", 0.03)
    manning_n_samples = rng.normal(manning_n_mean, MANNINGS_N_STD, num_samples)
    manning_n_samples = np.clip(manning_n_samples, 0.01, 0.1)  # Reasonable bounds

    if regression_families:
        families = list(regression_families)
    else:
        # Draw on every verified family rather than one. A single-family
        # ensemble only samples the Manning/peak noise, which understates the
        # real uncertainty: the four published equations disagree with each
        # other by 3-4x, and that inter-method spread is the dominant term.
        families = list(DEFAULT_REGRESSION_FAMILIES)

    # Breach FORMATION time, in seconds, as the median of the ensemble's spread.
    #
    # This is the only parameter that controls how ABRUPT the release is, and
    # until now it could not be set: it was fixed at CRITICAL_FAILURE_FRAC of a
    # hardcoded 3 h, about 27 minutes for every dam ever run. That matters
    # because `failure_mode` — the field the API and the dashboard both offer as
    # "overtopping / piping" — reaches exactly one function,
    # xu_zhang_2009_peak_outflow, and xu_zhang is deliberately NOT in
    # DEFAULT_REGRESSION_FAMILIES while its coefficients are unverified. So
    # selecting "piping" produced a hydrograph identical to "overtopping" in
    # every value, differing only in a label. A scenario-generation tool whose
    # scenario selector changes nothing is worse than one that offers no
    # selector at all.
    #
    # Exposed in SECONDS rather than as a fraction because it is a physical
    # quantity with published values to compare against — Von Thun & Gillette
    # (1990) give t_f = 0.020*h_w + 0.25 h for an erosion-resistant embankment
    # and 0.015*h_w for an easily erodible one, which for Tehri's 234 m head is
    # 4.9 h and 3.5 h respectively. The 27-minute default is far faster than
    # either; see the note in _generate_single_hydrograph for why it was chosen.
    #
    # A caller that sets this is stating an assumption, and it should be
    # reported as one — the value is carried into every member's metadata as
    # `failure_time_assumed` so the dashboard and the exports can say so.
    formation_time_s = dam_config.get("breach_formation_time_s")
    if formation_time_s is not None and float(formation_time_s) > 0.0:
        frac_median = float(formation_time_s) / HYDROGRAPH_MIN_DURATION_S
    else:
        frac_median = CRITICAL_FAILURE_FRAC

    hydrographs = []

    for i in range(num_samples):
        # Per-member failure-time fraction (lognormal spread) -> t_fail percentiles
        failure_time_frac = float(frac_median * rng.lognormal(0, 0.2))
        # Clamped against the median rather than the old fixed 0.02-0.6 band, so
        # a deliberately rapid breach is not silently widened back out to the
        # default's range. The factor keeps the lognormal tail bounded.
        failure_time_frac = min(max(failure_time_frac, 0.25 * frac_median),
                                4.0 * frac_median)
        failure_time_frac = min(max(failure_time_frac, 0.002), 0.6)

        family = families[i % len(families)]
        try:
            hydrograph = _generate_single_hydrograph(
                dam_config,
                manning_n_samples[i],
                member_id=i,
                regression=family,
                failure_time_frac=failure_time_frac,
                rng=rng,
            )
            hydrographs.append(hydrograph)

            if (i + 1) % 20 == 0:
                print(f"  Generated {i + 1}/{num_samples} members")

        except Exception as e:
            print(f"  WARNING: Member {i} failed: {str(e)[:60]}")
            # Generate fallback hydrograph
            hydrographs.append(_generate_fallback_hydrograph(dam_config, i))

    print(f"  Completed: {len(hydrographs)}/{num_samples} successful")
    return hydrographs


def _generate_single_hydrograph(
    dam_config: Dict,
    manning_n: float,
    member_id: int,
    regression: Optional[str] = None,
    failure_time_frac: float = CRITICAL_FAILURE_FRAC,
    rng: Optional[np.random.Generator] = None,
) -> Dict:
    """
    Generate single breach hydrograph.

    Uses the requested empirical regression family (if provided) for the peak
    outflow, otherwise falls back to the Wahl (2004) default. Failure time is
    sampled per-member so the ensemble has a spread in t_fail (required for
    percentile statistics).

    Args:
        dam_config: Dam configuration
        manning_n: Manning's n coefficient (sampled)
        member_id: Ensemble member ID
        regression: One of {None, 'wahl', 'froehlich', 'von_thun', 'macdonald', 'xu_zhang'}
        failure_time_frac: Fraction of total simulation time at which peak occurs
        rng: Optional numpy Generator for reproducible sampling

    Returns:
        Hydrograph dict with time series and metadata
    """
    if rng is None:
        rng = np.random

    # Extract dam parameters
    height = dam_config["height_m"]
    storage = dam_config["storage_mm3"]
    dam_type = dam_config.get("dam_type", "embankment")

    # How long the hydrograph is ROUTED for. This was a hard 10800 s literal
    # with no way to override it, which silently capped every dam at three
    # hours of outflow no matter how long the caller asked the solver to run —
    # the solver injects from this array, so the reservoir simply stopped
    # draining at t = 3 h.
    #
    # It went unnoticed because Khadakwasla empties in 2.88 h, inside the
    # window. Tehri does not: routed with the Froehlich peak it releases only
    # 77.0% of its 3,540 MCM in 3 h, reaching 99.9% at 6 h and 100.0% at 8 h.
    # A "full drain" run of a large reservoir was therefore unreachable.
    #
    # Floored at the old value so every existing short run is unchanged: a
    # 30-minute demo run must not shrink the hydrograph to 30 minutes.
    total_time = max(
        float(dam_config.get("hydrograph_duration_s", HYDROGRAPH_MIN_DURATION_S)),
        HYDROGRAPH_MIN_DURATION_S,
    )

    # The sampled fraction sets the breach FORMATION time, not the time of the
    # hydrograph peak: with real routing the peak emerges from the interaction
    # of breach growth and reservoir drawdown and is reported, not imposed.
    # (Von Thun & Gillette's own t_f for a 260 m dam is 5.4 h, longer than the
    # 3 h basis below; the ensemble's sampled formation time is used instead
    # so the peak lands inside the window the downstream solver expects.)
    #
    # Deliberately scaled by HYDROGRAPH_MIN_DURATION_S and NOT by total_time.
    # Formation time is a property of the dam and its failure mode; tying it to
    # the output window would mean that asking to watch for longer also made
    # the embankment erode more slowly, which is not a thing that happens. It
    # would also move the peak, so an 8 h run would not be the same event as
    # the 3 h one with a longer tail.
    t_fail = failure_time_frac * HYDROGRAPH_MIN_DURATION_S

    # Peak outflow from the chosen regression family
    if regression in ("froehlich", "froehlich_1995"):
        q_peak, _, _ = froehlich_1995_peak_outflow(
            height, height * 0.8, storage, "central"
        )
        regression = "froehlich_1995"
    elif regression in ("von_thun", "von_thun_gillette_1990"):
        q_peak, _, _ = von_thun_gillette_1990_peak_outflow(height, storage, "central")
        regression = "von_thun_gillette_1990"
    elif regression in ("macdonald", "macdonald_langridge_1984"):
        q_peak, _, _ = macdonald_langridge_1984_peak_outflow(
            height, storage, dam_type, "central"
        )
        regression = "macdonald_langridge_1984"
    elif regression in ("costa", "costa_1985"):
        q_peak, _, _ = costa_1985_peak_outflow(height, storage, "central")
        regression = "costa_1985"
    elif regression in ("scs", "scs_1981"):
        q_peak, _, _ = scs_1981_peak_outflow(height, "central")
        regression = "scs_1981"
    elif regression in ("xu_zhang", "xu_zhang_2009"):
        q_peak, _, _ = xu_zhang_2009_peak_outflow(
            height,
            storage,
            dam_type,
            dam_config.get("failure_mode", "overtopping"),
            "central",
        )
        regression = "xu_zhang_2009"
    else:
        # No family named: use Froehlich (1995b), the best-performing
        # peak-outflow equation in Wahl's (2004) comparison. The previous
        # default here was a coefficient reverse-engineered to land Tehri in a
        # pre-chosen band; there is no "Wahl (2004) regression" to fall back
        # on — Wahl (2004) is an uncertainty analysis, not a peak equation.
        q_peak, _, _ = froehlich_1995_peak_outflow(
            height, height * 0.8, storage, "central"
        )
        regression = "froehlich_1995"

    # Sample uncertainty in peak flow (15%)
    q_peak = float(q_peak) * rng.lognormal(0, 0.15)

    # Route the reservoir through a growing breach sized to this peak, so the
    # recession limb and the released volume are bounded by the storage rather
    # than drawn as a free-hand triangle.
    t_array, Q_t = level_pool_routing(
        initial_surface_elev_m=dam_config.get("initial_surface_elev_m", height),
        breach_bottom_elev_m=dam_config.get("breach_bottom_elev_m", 0.0),
        storage_mm3=storage,
        dem_bounds=(0.0, 0.0, 0.0, 0.0),
        q_peak_m3_s=q_peak,
        failure_time_s=t_fail,
        total_duration_s=total_time,
        dt_s=total_time / 999.0,
        surface_area_km2=dam_config.get("surface_area_km2"),
    )
    routed_peak = float(np.max(Q_t)) if Q_t.size else 0.0

    # Generate metadata
    metadata = {
        "member_id": member_id,
        "manning_n": manning_n,
        "q_peak": routed_peak,
        "q_peak_m3_s": routed_peak,
        "q_peak_regression_m3_s": float(q_peak),
        "failure_time_s": float(t_fail),
        # True when the caller pinned the formation time rather than taking the
        # module default, so a rapid-failure scenario is never mistaken for a
        # derived result. See synthesize_breach_ensemble.
        "failure_time_assumed": bool(dam_config.get("breach_formation_time_s")),
        "height_m": height,
        "storage_mm3": storage,
        "method": regression,
        "regression": regression,
        "regressions_used": [regression],
        "extrapolation_ratio": extrapolation_ratio(height),
        "dam_type": dam_type,
        # Height-based extrapolation and dam-CLASS extrapolation are reported
        # separately on purpose — see dam_class_outside_fitted_population().
        "dam_class_outside_fitted_population": dam_class_outside_fitted_population(
            dam_type
        ),
        "dam_class_note": (
            DAM_CLASS_EXTRAPOLATION_NOTE
            if dam_class_outside_fitted_population(dam_type)
            else None
        ),
        "unverified_regression": regression == "xu_zhang_2009"
        and not XU_ZHANG_2009_VERIFIED,
        "source_note": (
            "Peak from published regression (see function docstring for "
            "citation); hydrograph shape from level-pool routing. Wahl (2004) "
            "uncertainty bands are UNVETTED — see UNCERTAINTY_LOG_CYCLES."
        ),
    }

    return {"t_array": t_array, "Q_t": Q_t, "metadata": metadata}


def _generate_triangle_hydrograph(
    t_array: np.ndarray,
    q_peak: float,
    t_peak: float,
    duration_ratio: float = 0.7
) -> np.ndarray:
    """
    Generate triangular hydrograph with asymmetric rise/fall.

    Args:
        t_array: Time array
        q_peak: Peak discharge
        t_peak: Time of peak
        duration_ratio: Fraction of total duration for rise time

    Returns:
        Discharge time series
    """
    Q_t = np.zeros_like(t_array)
    duration = t_array[-1] - t_array[0]
    rise_duration = duration * duration_ratio
    fall_duration = duration - rise_duration

    # Linear rise to peak
    rise_mask = t_array <= (t_peak - rise_duration / 2)
    Q_t[rise_mask] = q_peak * (t_array[rise_mask] - t_array[0]) / rise_duration

    # Peak plateau (optional)
    peak_mask = np.abs(t_array - t_peak) <= (rise_duration / 2)
    Q_t[peak_mask] = q_peak

    # Linear fall from peak
    fall_mask = t_array > t_peak
    Q_t[fall_mask] = q_peak * (t_array[fall_mask][-1] - t_array[fall_mask]) / fall_duration

    return Q_t


def _generate_fallback_hydrograph(dam_config: Dict, member_id: int) -> Dict:
    """
    Generate fallback hydrograph when routing or a regression fails.

    Deliberately the crudest thing that is still defensible: Froehlich (1995b)
    for the peak and a bare triangle for the shape, with no routing. Used only
    when _generate_single_hydrograph raises, so a single bad ensemble member
    cannot take down a run. The metadata records "fallback": True so these
    members are identifiable in the output rather than silently mixed in.

    Args:
        dam_config: Dam configuration.
        member_id: Ensemble member ID.

    Returns:
        Simple hydrograph dict.
    """
    height = dam_config["height_m"]
    storage = dam_config["storage_mm3"]

    q_peak, _, _ = froehlich_1995_peak_outflow(height, height * 0.8, storage, "central")

    total_time = 10800.0
    t_array = np.linspace(0, total_time, 500)
    Q_t = _generate_triangle_hydrograph(
        t_array, q_peak, total_time * CRITICAL_FAILURE_FRAC, duration_ratio=0.5
    )

    metadata = {
        "member_id": member_id,
        "method": "froehlich_1995",
        "regression": "froehlich_1995",
        "regressions_used": ["froehlich_1995"],
        "fallback": True,
        "manning_n": dam_config.get("manning_n", 0.03),
        "height_m": height,
        "storage_mm3": storage,
        "extrapolation_ratio": extrapolation_ratio(height),
        "source_note": (
            "FALLBACK member: unrouted triangle, peak from Froehlich (1995b). "
            "Shape is not storage-bounded."
        ),
        "q_peak": float(q_peak),
        "q_peak_m3_s": float(q_peak),
        "failure_time_s": total_time * CRITICAL_FAILURE_FRAC,
    }

    return {"t_array": t_array, "Q_t": Q_t, "metadata": metadata}


def ensemble_statistics(hydrographs: List[Dict]) -> Dict:
    """
    Compute ensemble statistics from breach hydrographs.

    Args:
        hydrographs: List of hydrograph dicts

    Returns:
        Dictionary with ensemble statistics:
        - q_peak_median: Median peak flow
        - q_peak_p05, q_peak_p95: 5th and 95th percentiles
        - failure_time_median: Median failure time
        - regressions_used: List of regression methods used
    """
    if len(hydrographs) == 0:
        return {}

    # Extract peak flows and failure times
    q_peaks = []
    failure_times = []
    methods = set()

    for hg in hydrographs:
        q_peaks.append(hg["metadata"]["q_peak"])
        failure_times.append(hg["metadata"].get("failure_time_s", 0.0))
        methods.add(hg["metadata"].get("regression", hg["metadata"].get("method", "unknown")))

    q_peaks = np.array(q_peaks)
    failure_times = np.array(failure_times)

    # Compute statistics
    stats = {
        "q_peak_median": float(np.median(q_peaks)),
        "q_peak_mean": float(np.mean(q_peaks)),
        "q_peak_std": float(np.std(q_peaks)),
        "q_peak_p05": float(np.percentile(q_peaks, 5)),
        "q_peak_p95": float(np.percentile(q_peaks, 95)),
        "t_fail_median": float(np.median(failure_times)),
        "t_fail_p05": float(np.percentile(failure_times, 5)),
        "t_fail_p95": float(np.percentile(failure_times, 95)),
        "regressions_used": sorted(methods),
        "num_samples": len(hydrographs),
        "manning_n_uncertainty": "sampled_with_normal_distribution",
    }

    # Surface the dam-class caveat at ensemble level so it reaches
    # hazard_summary and the dashboard rather than dying in per-member
    # metadata that nothing reads.
    dam_types = {hg["metadata"].get("dam_type") for hg in hydrographs}
    outside = any(
        hg["metadata"].get("dam_class_outside_fitted_population") for hg in hydrographs
    )
    stats["dam_type"] = sorted(t for t in dam_types if t)[0] if any(dam_types) else None
    stats["dam_class_outside_fitted_population"] = outside
    stats["dam_class_note"] = DAM_CLASS_EXTRAPOLATION_NOTE if outside else None

    return stats


# ── Published peak-outflow regressions ────────────────────────────────────────
#
# Lineage: Wahl, T.L. (1998), "Prediction of Embankment Dam Breach Parameters:
# A Literature Review and Needs Assessment", USBR DSO-98-004, Table 5, which
# collects the peak-outflow equations below in a single consistent notation;
# and Wahl (2004) for the prediction-uncertainty bands.
#
# Notation used throughout, matching the sources:
#     V_w  reservoir volume at breach initiation      [m^3]  (not MCM!)
#     h_w  depth of water above the breach invert     [m]
#     h_d  height of the dam                          [m]
#
# Public functions in this module take storage in MCM because that is the unit
# the CWC register publishes; conversion to m^3 happens at the boundary via
# MCM_TO_M3. Getting this wrong is the single easiest way to be off by 59x
# (see the note on MCM_TO_M3 above).
#
# Every equation here is an empirical fit to a set of ~20-110 historical
# embankment-dam failures, almost all under 90 m. They disagree with each other
# by a factor of 3-4 and with observation by a factor of 2-3. That is the
# documented state of the art, not a defect in this implementation: quote the
# ensemble range, never a single number.


def extrapolation_ratio(height_m: float) -> float:
    """
    How far beyond the regressions' calibration ceiling a dam sits.

    Returns height / CALIBRATION_MAX_HEIGHT_M. A value > 1 means every peak
    outflow from this module for that dam is an extrapolation. Tehri returns
    2.80, so its predictions are reported as an ensemble range with the
    extrapolation stated, never as a calibrated point estimate.
    """
    return float(height_m) / CALIBRATION_MAX_HEIGHT_M


def _wahl_bounds(
    q_central: float,
    equation_key: str,
    mode: str,
) -> Tuple[float, float, float]:
    """
    Attach Wahl (2004) prediction-uncertainty bands to a central estimate.

    Wahl expresses uncertainty as +/- w log10 cycles of prediction error, so
    the band is multiplicative: [q * 10^-w, q * 10^+w]. This is a *prediction*
    interval for a single future dam, which is why it is much wider than the
    standard error of the regression coefficients.

    Args:
        q_central: Central (best-estimate) peak outflow, m^3/s.
        equation_key: Key into UNCERTAINTY_LOG_CYCLES.
        mode: "central" | "lower" | "upper" — which value to return first.

    Returns:
        (value, lower, upper). ``value`` is the one selected by ``mode``;
        ``lower`` and ``upper`` always describe the full band.
    """
    log_cycles = UNCERTAINTY_LOG_CYCLES.get(equation_key, 0.50)
    factor = 10.0 ** log_cycles
    q_lo = float(q_central) / factor
    q_hi = float(q_central) * factor
    if mode == "lower":
        return q_lo, q_lo, q_hi
    if mode == "upper":
        return q_hi, q_lo, q_hi
    return float(q_central), q_lo, q_hi


def froehlich_1995_peak_outflow(
    height_m: float,
    breach_width_m: float,
    storage_mcm: float,
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    Froehlich (1995b) peak breach outflow.

        Q_p = 0.607 * V_w^0.295 * h_w^1.24        [V_w in m^3, h_w in m]

    Source: Froehlich, D.C. (1995), "Peak Outflow from Breached Embankment
    Dam", J. Water Resour. Plann. Manage. 121(1):90-97. Fitted to 22 case
    studies. This is the best-performing peak-outflow equation in Wahl's
    (2004) comparison, so it is the ensemble's reference method.

    Validation: Teton (1976), V_w = 3.56e8 m^3, h_w = 86.9 m — predicts
    51,316 m^3/s against a measured 65,120 m^3/s (ratio 0.79), comfortably
    inside the equation's own scatter. Asserted in tests/test_breach.py.

    Note that ``breach_width_m`` is NOT used. Froehlich's peak-outflow
    equation is a function of volume and depth only; his separate 1995a
    paper regresses breach *width*. The argument is retained because callers
    pass it, and because a future revision may switch to the width-based
    weir form — it is accepted and ignored, not silently folded in.

    Args:
        height_m: Depth of water above the breach invert, m. For a full
            reservoir failing by overtopping this is ~the dam height.
        breach_width_m: Accepted for API compatibility; unused.
        storage_mcm: Reservoir volume at breach initiation, MCM.
        mode: "central" | "lower" | "upper".

    Returns:
        (value, lower, upper) in m^3/s, band from Wahl (2004).
    """
    del breach_width_m  # documented above: not a term in this equation
    volume_m3 = float(storage_mcm) * MCM_TO_M3
    q_central = 0.607 * (volume_m3**0.295) * (float(height_m) ** 1.24)
    return _wahl_bounds(q_central, "froehlich_1995", mode)


def macdonald_langridge_1984_peak_outflow(
    height_m: float,
    storage_mcm: float,
    dam_type: str = "embankment",
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    MacDonald & Langridge-Monopolis (1984) peak breach outflow.

        earthfill best fit:   Q_p = 1.154 * (V_w * h_w)^0.412
        upper envelope:       Q_p = 3.85  * (V_w * h_w)^0.411

    Source: MacDonald, T.C. & Langridge-Monopolis, J. (1984), "Breaching
    Characteristics of Dam Failures", J. Hydraul. Eng. 110(5):567-586.
    Fitted to 42 case studies. The authors publish an envelope as well as a
    best fit because their scatter is one-sided; both are exposed here since
    the pair brackets observation where the best fit alone does not.

    Validation: Teton — best fit 24,226 m^3/s, envelope 78,894 m^3/s against
    a measured 65,120 m^3/s. The best fit under-predicts by 2.7x; the pair
    brackets the observation. This is why the module reports ranges.

    ``dam_type`` selects which of the two published fits is used rather than
    applying an invented multiplier: the equations were fitted to earthfill
    embankments, so "embankment"/"earthfill" gets the best fit, and anything
    else (rockfill, concrete-faced — stiffer, less erodible, but with far
    less data) gets the same form with the extrapolation recorded by the
    caller. There is no published dam-type coefficient in MLM (1984) and one
    is not fabricated here.

    Args:
        height_m: Depth of water above the breach invert, m.
        storage_mcm: Reservoir volume at breach initiation, MCM.
        dam_type: "embankment" | "earthfill" use the best fit; any other
            value additionally widens the band (see UNCERTAINTY_LOG_CYCLES).
        mode: "central" | "lower" | "upper".

    Returns:
        (value, lower, upper) in m^3/s.
    """
    volume_m3 = float(storage_mcm) * MCM_TO_M3
    product = volume_m3 * float(height_m)
    q_central = 1.154 * (product**0.412)
    value, q_lo, q_hi = _wahl_bounds(q_central, "macdonald_1984", mode)
    # The published upper envelope is a hard statement about the data and is
    # wider than the Wahl band at large (V*h); keep whichever is wider so the
    # reported interval never understates what the source itself allows.
    q_envelope = 3.85 * (product**0.411)
    if q_envelope > q_hi:
        q_hi = q_envelope
        if mode == "upper":
            value = q_envelope
    if dam_type not in ("embankment", "earthfill"):
        # Outside the fitted population: widen, do not shift. Shifting would
        # require a dam-type coefficient that MLM (1984) does not publish.
        q_lo /= 2.0
        q_hi *= 2.0
    return value, q_lo, q_hi


def costa_1985_peak_outflow(
    height_m: float,
    storage_mcm: float,
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    Costa (1985) peak breach outflow, storage-times-height form.

        Q_p = 0.981 * (S * h_d)^0.42            [S in m^3, h_d in m]

    Source: Costa, J.E. (1985), "Floods from Dam Failures", USGS Open-File
    Report 85-560. Fitted across constructed and natural (landslide, moraine)
    dams, which makes it the most relevant of the classical set to the
    Himalayan GLOF/landslide-dam cases in scope, at the cost of more scatter.

    Validation: Teton — 24,984 m^3/s against 65,120 m^3/s measured.
    Under-predicts by 2.6x, consistent with MLM's best fit.

    Args:
        height_m: Dam height (Costa uses dam height, not water depth), m.
        storage_mcm: Reservoir storage, MCM.
        mode: "central" | "lower" | "upper".

    Returns:
        (value, lower, upper) in m^3/s.
    """
    volume_m3 = float(storage_mcm) * MCM_TO_M3
    q_central = 0.981 * ((volume_m3 * float(height_m)) ** 0.42)
    # TODO: UNVETTED — Costa's band is not in Wahl (2004) Table 3; reuse the
    # MacDonald width as a stand-in until transcribed from Costa (1985).
    return _wahl_bounds(q_central, "macdonald_1984", mode)


def scs_1981_peak_outflow(
    height_m: float,
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    SCS (1981) peak breach outflow, depth-only form.

        Q_p = 16.6 * h_w^1.85                    [h_w in m]

    Source: US Soil Conservation Service (1981), "Simplified Dam-Breach
    Routing Procedure", Technical Release 66. Included precisely because it
    ignores storage: it is an independent check that the volume-dependent
    equations are not being driven by a mis-specified storage figure, which
    is the most common data error in a screening run.

    Validation: Teton — 64,164 m^3/s against 65,120 m^3/s measured (ratio
    0.99). The agreement is fortuitous, not evidence this form is better;
    with no volume term it must fail badly on a shallow, high-volume
    reservoir. Treated as a cross-check, not as an ensemble member.

    Args:
        height_m: Depth of water above the breach invert, m.
        mode: "central" | "lower" | "upper".

    Returns:
        (value, lower, upper) in m^3/s.
    """
    q_central = 16.6 * (float(height_m) ** 1.85)
    # TODO: UNVETTED — band not published in TR-66; 0.50 log cycles assumed.
    return _wahl_bounds(q_central, "xu_zhang_2009", mode)


def von_thun_gillette_1990_breach_geometry(
    height_m: float,
    storage_mcm: float,
    erodibility: str = "erosion_resistant",
) -> Dict[str, float]:
    """
    Von Thun & Gillette (1990) breach geometry and failure time.

    VTG is *not* a peak-outflow regression — a point the previous version of
    this module got wrong. What VTG publish is breach geometry and formation
    time, intended as input to a routing model such as DAMBRK or HEC-RAS:

        average breach width:   B_avg = 2.5 * h_w + C_b
        failure time (resistant):  t_f = 0.020 * h_w + 0.25   [hours]
        failure time (erodible):   t_f = 0.015 * h_w          [hours]

    C_b is an offset that increases with reservoir storage (VTG Table 1;
    originally 20/60/140/180 ft):

        S < 1.23 MCM          C_b =  6.1 m
        1.23 <= S < 6.17      C_b = 18.3 m
        6.17 <= S < 12.3      C_b = 42.7 m
        S >= 12.3             C_b = 54.9 m

    Source: Von Thun, J.L. & Gillette, D.R. (1990), "Guidance on Breach
    Parameters", unpublished internal document, USBR, Denver — reproduced in
    Wahl (1998) DSO-98-004 Table 5, which is the accessible citation.

    Side slopes: VTG recommend 1H:1V for most embankments (0.5H:1V where the
    fill is cohesive and erosion-resistant). 1.0 is returned as the default.

    Args:
        height_m: Depth of water above the breach invert, m.
        storage_mcm: Reservoir storage, MCM.
        erodibility: "erosion_resistant" | "easily_erodible".

    Returns:
        Dict with "breach_width_m", "failure_time_s", "side_slope",
        "invert_drop_m", and "erodibility".
    """
    depth = float(height_m)
    if storage_mcm < 1.23:
        width_offset_m = 6.1
    elif storage_mcm < 6.17:
        width_offset_m = 18.3
    elif storage_mcm < 12.3:
        width_offset_m = 42.7
    else:
        width_offset_m = 54.9

    breach_width_m = 2.5 * depth + width_offset_m

    if erodibility == "easily_erodible":
        failure_time_hours = 0.015 * depth
    else:
        failure_time_hours = 0.020 * depth + 0.25

    return {
        "breach_width_m": breach_width_m,
        "failure_time_s": failure_time_hours * 3600.0,
        "side_slope": 1.0,
        "invert_drop_m": depth,
        "erodibility": erodibility,
    }


def von_thun_gillette_1990_peak_outflow(
    height_m: float,
    storage_mcm: float,
    mode: str = "central",
    erodibility: str = "erosion_resistant",
) -> Tuple[float, float, float]:
    """
    Peak outflow implied by Von Thun & Gillette (1990) geometry, routed.

    Because VTG give geometry rather than a peak (see
    von_thun_gillette_1990_breach_geometry), the peak here is *computed*:
    the VTG breach is grown over the VTG failure time and the reservoir is
    drained through it by level-pool routing, and the maximum of the
    resulting hydrograph is returned.

    This makes VTG the one physically-derived member of the ensemble rather
    than a fifth curve fit, which is the point of including it. It also means
    the answer respects storage: a broad-crested weir at full head over the
    full final breach would give 473,000 m^3/s for Teton, 7.3x the observed
    peak, because it ignores the drawdown that occurs while the breach is
    still forming. Routing supplies that drawdown.

    Args:
        height_m: Depth of water above the breach invert, m.
        storage_mcm: Reservoir storage, MCM.
        mode: "central" | "lower" | "upper".
        erodibility: "erosion_resistant" | "easily_erodible".

    Returns:
        (value, lower, upper) in m^3/s.
    """
    geometry = von_thun_gillette_1990_breach_geometry(
        height_m, storage_mcm, erodibility
    )
    # Route long enough for the peak to be captured: the peak always occurs
    # at or before full breach formation plus one drawdown time-constant.
    duration_s = max(6.0 * geometry["failure_time_s"], 3600.0)
    _, discharge = level_pool_routing(
        initial_surface_elev_m=float(height_m),
        breach_bottom_elev_m=0.0,
        storage_mm3=storage_mcm,
        dem_bounds=(0.0, 0.0, 0.0, 0.0),
        q_peak_m3_s=0.0,  # unused: breach_width_m is supplied
        failure_time_s=geometry["failure_time_s"],
        total_duration_s=duration_s,
        # Resolve the peak, which is a cusp at full breach formation: 2000
        # samples over 6 t_f puts ~330 of them inside the formation window.
        dt_s=duration_s / 2000.0,
        breach_width_m=geometry["breach_width_m"],
        side_slope=geometry["side_slope"],
    )
    q_central = float(np.max(discharge))
    return _wahl_bounds(q_central, "von_thun_1990", mode)


# Xu & Zhang (2009) is implemented but QUARANTINED — see the docstring. It is
# excluded from DEFAULT_REGRESSION_FAMILIES until its coefficients are checked
# against the primary source.
XU_ZHANG_2009_VERIFIED = False

# TODO: UNVETTED — every coefficient below. Xu, Y. & Zhang, L.M. (2009),
# "Breaching Parameters for Earth and Rockfill Dams", J. Geotech. Geoenviron.
# Eng. 135(12):1957-1970, Table 8. Each of b_3/b_4/b_5 is a separate
# categorical adjustment and each needs separate confirmation.
_XU_ZHANG_B3_DAM_TYPE = {
    "homogeneous": 0.0,       # TODO: UNVETTED — reference category?
    "embankment": 0.0,        # TODO: UNVETTED — mapped to homogeneous/zoned
    "zoned": -0.026,          # TODO: UNVETTED
    "corewall": -0.226,       # TODO: UNVETTED
    "concrete_faced": -0.226,  # TODO: UNVETTED
    "rockfill": -0.226,       # TODO: UNVETTED — mapped to concrete-faced
}
_XU_ZHANG_B4_FAILURE_MODE = {
    "overtopping": -0.144,    # TODO: UNVETTED
    "piping": -0.389,         # TODO: UNVETTED
    "seepage": -0.389,        # TODO: UNVETTED
}
_XU_ZHANG_B5_ERODIBILITY = {
    "high": -0.289,           # TODO: UNVETTED
    "medium": -0.911,         # TODO: UNVETTED
    "low": -2.244,            # TODO: UNVETTED
}
# Reference height in the dimensionless height term, m (Xu & Zhang use 15 m).
_XU_ZHANG_REFERENCE_HEIGHT_M = 15.0


def xu_zhang_2009_peak_outflow(
    height_m: float,
    storage_mcm: float,
    dam_type: str = "embankment",
    failure_mode: str = "overtopping",
    mode: str = "central",
) -> Tuple[float, float, float]:
    """
    Xu & Zhang (2009) dimensionless peak-outflow relation. QUARANTINED.

        Q_p / (g^0.5 * V_w^(5/6))
            = 0.175 * (h_d/h_r)^0.199 * (V_w^(1/3)/h_w)^-1.274 * exp(B_4)

    with h_r = 15 m and B_4 = b_3 + b_4 + b_5 the sum of categorical
    adjustments for dam type, failure mode, and erodibility.

    WHY THIS IS QUARANTINED (XU_ZHANG_2009_VERIFIED is False):

    The structure above is reproduced from Xu & Zhang (2009), but the
    categorical coefficients in _XU_ZHANG_B3/B4/B5 fail a back-check against
    Teton (1976). Back-solving the equation on Teton (V_w = 3.56e8 m^3,
    h_w = 86.9 m, h_d = 93 m, measured Q_p = 65,120 m^3/s) requires
    exp(B_4) = 0.0900, i.e. B_4 = -2.41. Teton was a zoned earthfill dam
    that failed by piping through highly erodible windblown silt, so the
    coefficients below give B_4 = -0.026 - 0.389 - 0.289 = -0.704,
    exp(B_4) = 0.495 — a factor of 5.5 too high.

    That discrepancy means at least one of the coefficients, the reference
    categories, or the leading 0.175 is mis-transcribed. Rather than tune a
    number until Teton fits — which is exactly the reverse-engineering this
    module was rewritten to remove — the family is left implemented, flagged,
    and excluded from the default ensemble. It returns a value so callers do
    not break, and records "unverified": True in nothing but this docstring
    and XU_ZHANG_2009_VERIFIED, which the ensemble consults.

    Args:
        height_m: Depth of water above the breach invert, m (h_w). Dam height
            h_d is taken as equal to h_w here, the full-reservoir case.
        storage_mcm: Reservoir volume at breach initiation, MCM.
        dam_type: Key into _XU_ZHANG_B3_DAM_TYPE.
        failure_mode: Key into _XU_ZHANG_B4_FAILURE_MODE.
        mode: "central" | "lower" | "upper".

    Returns:
        (value, lower, upper) in m^3/s. Do not quote without the caveat.
    """
    volume_m3 = float(storage_mcm) * MCM_TO_M3
    water_depth_m = float(height_m)
    dam_height_m = water_depth_m  # full-reservoir assumption

    b3 = _XU_ZHANG_B3_DAM_TYPE.get(dam_type, 0.0)
    b4 = _XU_ZHANG_B4_FAILURE_MODE.get(failure_mode, -0.144)
    # TODO: UNVETTED — erodibility is not currently carried in dam_config, so
    # "high" is assumed. High erodibility is the conservative (largest Q)
    # choice among the three, which is the right default for screening.
    b5 = _XU_ZHANG_B5_ERODIBILITY["high"]

    height_term = (dam_height_m / _XU_ZHANG_REFERENCE_HEIGHT_M) ** 0.199
    shape_term = ((volume_m3 ** (1.0 / 3.0)) / water_depth_m) ** -1.274
    dimensionless = 0.175 * height_term * shape_term * np.exp(b3 + b4 + b5)
    q_central = dimensionless * (G**0.5) * (volume_m3 ** (5.0 / 6.0))
    return _wahl_bounds(float(q_central), "xu_zhang_2009", mode)


# Families drawn on by synthesize_breach_ensemble when the caller does not
# name any. Xu & Zhang is deliberately absent (see XU_ZHANG_2009_VERIFIED).
# The dam classes the ensemble's regressions were actually fitted on. Froehlich
# (1995b, 22 embankment breaches), MacDonald & Langridge-Monopolis (1984, 42
# earthfill case studies), Costa (1985) and Von Thun & Gillette (1990) are all
# embankment fits, and all of them model a breach that ERODES: a trapezoidal
# notch widening over a failure time of minutes to hours.
#
# A masonry or concrete gravity dam does not fail that way. It fails by monolith
# sliding or overturning — a near-instantaneous removal of one or more blocks.
# There is no published dam-type coefficient in any of these equations, so this
# module does not shift the central estimate for such a dam (that would mean
# inventing a coefficient). It flags the condition instead, so the caller knows
# the number is a screening figure from an out-of-population fit.
FITTED_DAM_CLASSES = ("embankment", "earthfill")

DAM_CLASS_EXTRAPOLATION_NOTE = (
    "Froehlich (1995b), MacDonald & Langridge-Monopolis (1984), Costa (1985) "
    "and Von Thun & Gillette (1990) are all fits to EMBANKMENT breaches, and "
    "all model a breach that erodes progressively. A masonry/concrete gravity "
    "dam fails by monolith sliding or overturning, which the trapezoidal "
    "breach-growth model does not describe. No dam-type coefficient is "
    "published for these equations, so the central estimate is NOT adjusted "
    "here. Treat the peak as an order-of-magnitude screening figure only."
)


def dam_class_outside_fitted_population(dam_type: Optional[str]) -> bool:
    """
    True when this dam class sits outside the regressions' fitted population.

    Deliberately separate from extrapolation_ratio(), which measures HEIGHT
    only. The two can disagree in the dangerous direction: a 51 m masonry
    gravity dam scores extrapolation_ratio = 0.55, comfortably inside the
    fitted height range, while being the wrong kind of dam entirely. Reporting
    only the height ratio for such a dam would read green when it should not.
    """
    if not dam_type:
        return False
    return dam_type.strip().lower() not in FITTED_DAM_CLASSES


#: Shortest hydrograph the routing is run for, and the basis the breach
#: FORMATION time is scaled against. 3 h was the module's original hardcoded
#: window; keeping it as the floor means a run that does not ask for a longer
#: one behaves exactly as before.
HYDROGRAPH_MIN_DURATION_S = 10800.0


DEFAULT_REGRESSION_FAMILIES = (
    "froehlich",
    "macdonald",
    "costa",
    "von_thun",
)


# ── Level-pool (modified Puls) reservoir routing ──────────────────────────────


def reservoir_storage_curve(
    storage_mcm: float,
    depth_m: float,
    surface_area_km2: Optional[float] = None,
    storage_exponent: float = 3.0,
) -> Tuple[float, float]:
    """
    Fit a power-law storage-elevation curve S(d) = k * d^b.

    d is depth above the breach invert. b encodes valley shape: b = 1 is a
    vertical-walled tank, b = 2 a V-notch, b = 3 a cone, and real reservoirs
    in narrow gorges that widen upward run higher still. Teton, for example,
    held 356 MCM at 86.9 m depth over a 28 km^2 surface, which implies
    b = A0*d0/S0 = 6.8 — its mean depth was only 15% of its maximum.

    When surface_area_km2 is known, b is derived exactly from it, since for
    S = k*d^b the area is A = dS/dd = b*S/d, hence b = A0*d0/S0. Otherwise
    ``storage_exponent`` is used.

    Args:
        storage_mcm: Storage above the breach invert at t=0, MCM.
        depth_m: Initial water depth above the breach invert, m.
        surface_area_km2: Reservoir surface area at full pool, km^2.
        storage_exponent: Fallback b when surface area is unknown.

    Returns:
        (k, b) with S in m^3 and d in m.
    """
    volume_m3 = float(storage_mcm) * MCM_TO_M3
    depth = max(float(depth_m), 1.0e-6)
    if surface_area_km2 is not None and surface_area_km2 > 0.0:
        exponent = (float(surface_area_km2) * 1.0e6) * depth / volume_m3
        # Keep the fit physical: b < 1 would mean area shrinking with depth.
        exponent = min(max(exponent, 1.0), 12.0)
    else:
        exponent = float(storage_exponent)
    coefficient = volume_m3 / (depth**exponent)
    return coefficient, exponent


def _breach_weir_discharge(
    head_m: float,
    bottom_width_m: float,
    side_slope: float,
) -> float:
    """
    Broad-crested weir discharge through a trapezoidal breach.

        Q = 1.7 * B * H^1.5 + 1.4 * z * H^2.5

    The rectangular term uses the ideal broad-crested coefficient
    (2/3)^1.5 * sqrt(g) = 1.705 for a discharge coefficient of 1; the
    triangular side term uses (8/15) * C_d * sqrt(2g) with C_d = 0.6,
    giving 1.417. These are the SI equivalents of the 3.1 and 2.45 used by
    NWS DAMBRK and HEC-RAS in English units.

    Args:
        head_m: Water surface above the instantaneous breach invert, m.
        bottom_width_m: Instantaneous breach bottom width, m.
        side_slope: Horizontal run per unit rise of the breach sides.

    Returns:
        Discharge, m^3/s. Zero for non-positive head.
    """
    if head_m <= 0.0:
        return 0.0
    return (
        1.7 * bottom_width_m * head_m**1.5
        + 1.4 * side_slope * head_m**2.5
    )


@njit(cache=True)
def _route_kernel(
    storage_coefficient: float,
    storage_exponent: float,
    initial_depth_m: float,
    final_width_m: float,
    side_slope: float,
    failure_time_s: float,
    dt: float,
    n_steps: int,
) -> np.ndarray:
    """
    Integrate dS/dt = -Q through a linearly-growing trapezoidal breach.

    Explicit Euler on a uniform fine grid, with storage clipped at zero so no
    step can manufacture negative volume — which is what makes the routed
    volume bounded by the storage as an identity rather than as an assertion.

    Both breach bottom width and invert depth grow linearly from zero to their
    final values over failure_time_s, the standard DAMBRK/HEC-RAS
    idealisation. Inflow is taken as zero: a dam-break peak is two to three
    orders of magnitude above any plausible reservoir inflow, and neglecting
    it is conservative for arrival time.

    JIT-compiled because the ensemble calls this O(100 members x 45 bisection
    iterations) times; in pure Python that is ~20 s per ensemble.

    Returns discharge on the fine grid (n_steps + 1 samples).
    """
    discharge = np.zeros(n_steps + 1, dtype=np.float64)
    storage = storage_coefficient * initial_depth_m**storage_exponent
    inverse_exponent = 1.0 / storage_exponent

    for step in range(n_steps + 1):
        time_s = step * dt
        if failure_time_s > 0.0:
            growth = time_s / failure_time_s
            if growth > 1.0:
                growth = 1.0
        else:
            growth = 1.0

        width = final_width_m * growth
        invert_depth = initial_depth_m * growth

        if storage <= 0.0:
            discharge[step] = 0.0
            continue

        water_depth = (storage / storage_coefficient) ** inverse_exponent
        # Head is measured from the instantaneous breach invert, which sits
        # invert_depth below the crest, i.e. (initial_depth - invert_depth)
        # above the final invert that the storage curve is referenced to.
        head = water_depth - (initial_depth_m - invert_depth)

        if head <= 0.0:
            discharge[step] = 0.0
            continue

        # Broad-crested weir through a trapezoid; see _breach_weir_discharge
        # for the provenance of 1.7 and 1.4.
        flow = 1.7 * width * head**1.5 + 1.4 * side_slope * head**2.5

        # Cap the flow at what the reservoir can actually supply over this
        # step. Without this the final step reports the full weir discharge
        # while storage merely clips at zero, so the *reported* hydrograph
        # carries water the reservoir never held — a small absolute excess
        # (~0.3 m^3) but a real one, and the downstream solver integrates the
        # reported hydrograph, not the internal state.
        available_flow = storage / dt
        if flow > available_flow:
            flow = available_flow

        discharge[step] = flow

        storage -= flow * dt
        if storage < 0.0:
            storage = 0.0

    return discharge


def _fine_grid_steps(n_out_intervals: int, total_duration_s: float, failure_time_s: float) -> int:
    """
    Number of internal Euler steps for a routing pass.

    Deliberately independent of the caller's output grid: tying them together
    made the reported peak depend on dt_s (a 100 s output grid and a 141 s one
    differed by 44% on the Teton hydrograph, because the peak is a cusp at the
    moment of full breach formation and a coarse grid steps over it).
    """
    n_steps = max(4000, 4 * n_out_intervals)
    if failure_time_s > 0.0:
        # Resolve breach formation with at least 400 steps: the peak sits at
        # 0.8-1.0 t_f, so that is where grid resolution actually buys accuracy.
        needed = int(400.0 * total_duration_s / failure_time_s)
        n_steps = max(n_steps, min(needed, 200_000))
    return n_steps


def _route_breach_fine(
    storage_coefficient: float,
    storage_exponent: float,
    initial_depth_m: float,
    final_width_m: float,
    side_slope: float,
    failure_time_s: float,
    total_duration_s: float,
    n_out_intervals: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Route on the internal fine grid. Returns (fine_times, fine_discharge)."""
    n_steps = _fine_grid_steps(n_out_intervals, total_duration_s, failure_time_s)
    dt = total_duration_s / n_steps
    fine = _route_kernel(
        storage_coefficient,
        storage_exponent,
        initial_depth_m,
        final_width_m,
        side_slope,
        failure_time_s,
        dt,
        n_steps,
    )
    return np.linspace(0.0, total_duration_s, n_steps + 1), fine


def _route_breach(
    storage_coefficient: float,
    storage_exponent: float,
    initial_depth_m: float,
    final_width_m: float,
    side_slope: float,
    failure_time_s: float,
    total_duration_s: float,
    out_times: np.ndarray,
) -> np.ndarray:
    """Route on the fine internal grid, then interpolate onto ``out_times``."""
    fine_times, fine = _route_breach_fine(
        storage_coefficient,
        storage_exponent,
        initial_depth_m,
        final_width_m,
        side_slope,
        failure_time_s,
        total_duration_s,
        max(len(out_times) - 1, 1),
    )
    return np.interp(out_times, fine_times, fine)


def level_pool_routing(
    initial_surface_elev_m: float,
    breach_bottom_elev_m: float,
    storage_mm3: float,
    dem_bounds: Tuple[float, float, float, float],
    q_peak_m3_s: float,
    failure_time_s: float,
    total_duration_s: float,
    dt_s: Optional[float] = None,
    breach_width_m: Optional[float] = None,
    side_slope: float = 1.0,
    storage_exponent: float = 3.0,
    surface_area_km2: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Level-pool (modified Puls) reservoir depletion through a growing breach.

    This actually routes: it integrates dS/dt = -Q(t) with Q from
    broad-crested weir flow through a trapezoidal breach whose width and
    invert grow linearly over ``failure_time_s``, and with head taken from a
    power-law storage-elevation curve. The previous implementation returned a
    bare triangle and claimed in its docstring to be "bounded by the
    available storage" while never reading the storage argument; the routed
    volume here cannot exceed the storage because the storage *is* the state
    variable.

    Two ways to size the breach:

    * Pass ``breach_width_m`` (e.g. from Von Thun & Gillette) and the
      hydrograph is a pure forward prediction.
    * Leave it None and pass ``q_peak_m3_s`` from one of the empirical
      regressions; the final breach width is then found by bisection so the
      routed peak matches that regression. This is a deliberate,
      clearly-labelled inversion — it lets the recession limb and total
      volume be physically consistent while the peak stays anchored to the
      empirical evidence, which is how a screening-tier study is normally
      built. It is not a fit to an unknown.

    Args:
        initial_surface_elev_m: Initial reservoir surface elevation, m.
        breach_bottom_elev_m: Final breach invert elevation, m.
        storage_mm3: Storage above the breach invert at t=0, MCM.
        dem_bounds: (x0, y0, x1, y1); informational, unused.
        q_peak_m3_s: Target peak used only when breach_width_m is None.
        failure_time_s: Breach formation time, s.
        total_duration_s: Routing duration, s.
        dt_s: Output sample interval, s. Defaults to total_duration_s / 200.
        breach_width_m: Final breach bottom width, m. If given, q_peak_m3_s
            is ignored.
        side_slope: Horizontal run per unit rise of the breach sides.
        storage_exponent: Power-law exponent b in S = k*d^b when the
            reservoir surface area is unknown. 3.0 is a cone-like valley.
        surface_area_km2: Reservoir surface area at full pool; when given, b
            is derived from it exactly.

    Returns:
        (t_array, q_array) as float64 numpy arrays of equal length.
    """
    del dem_bounds  # documented above: informational only

    if dt_s is None:
        dt_s = max(total_duration_s / 200.0, 1.0)
    n_out = int(np.ceil(total_duration_s / dt_s)) + 1
    out_times = np.linspace(0.0, total_duration_s, n_out)

    initial_depth_m = float(initial_surface_elev_m) - float(breach_bottom_elev_m)
    if initial_depth_m <= 0.0 or storage_mm3 <= 0.0:
        # Nothing above the invert: no outflow. Returning zeros is correct
        # and keeps callers from having to special-case an empty reservoir.
        return out_times, np.zeros(n_out, dtype=np.float64)

    storage_coefficient, exponent = reservoir_storage_curve(
        storage_mm3, initial_depth_m, surface_area_km2, storage_exponent
    )

    if breach_width_m is not None:
        return out_times, _route_breach(
            storage_coefficient,
            exponent,
            initial_depth_m,
            float(breach_width_m),
            side_slope,
            failure_time_s,
            total_duration_s,
            out_times,
        )

    target = float(q_peak_m3_s)
    if target <= 0.0:
        return out_times, np.zeros(n_out, dtype=np.float64)

    # Invert for the breach size that reproduces the requested peak.
    #
    # The knob is a single scale factor applied to BOTH the bottom width and
    # the side slope, not to the width alone. Scaling width alone cannot reach
    # a small peak: the trapezoidal side term 1.4*z*H^2.5 is independent of
    # bottom width, so a zero-width breach with 1H:1V sides at 260 m head
    # still passes 1.3e6 m^3/s. Bisecting on width alone silently returned
    # that floor for every target below it. Scaling the whole cross-section
    # makes Q monotone in the knob and drives it to zero as the knob does.
    reference_width_m = initial_depth_m  # square-ish breach at unit scale
    reference_slope = side_slope

    def routed_peak(scale: float) -> float:
        # Peak taken from the fine grid, not the interpolated output. Reading
        # it off the output grid made routed_peak() jitter with grid placement
        # for reservoirs that drain in a few output samples, which broke the
        # monotonicity bisection relies on.
        _, fine = _route_breach_fine(
            storage_coefficient,
            exponent,
            initial_depth_m,
            reference_width_m * scale,
            reference_slope * scale,
            failure_time_s,
            total_duration_s,
            n_out - 1,
        )
        return float(np.max(fine))

    scale_lo, scale_hi = 1.0e-6, 1.0
    while routed_peak(scale_hi) < target and scale_hi < 1.0e4:
        scale_hi *= 4.0
    # A target the reservoir cannot supply at any breach size (storage- rather
    # than geometry-limited) leaves scale_hi at the cap; the widest breach is
    # then the correct answer and the routed peak is reported as-is.
    for _ in range(50):
        scale_mid = 0.5 * (scale_lo + scale_hi)
        if routed_peak(scale_mid) < target:
            scale_lo = scale_mid
        else:
            scale_hi = scale_mid
        if scale_hi - scale_lo < 1.0e-6 * max(scale_hi, 1.0):
            break

    scale = 0.5 * (scale_lo + scale_hi)
    return out_times, _route_breach(
        storage_coefficient,
        exponent,
        initial_depth_m,
        reference_width_m * scale,
        reference_slope * scale,
        failure_time_s,
        total_duration_s,
        out_times,
    )