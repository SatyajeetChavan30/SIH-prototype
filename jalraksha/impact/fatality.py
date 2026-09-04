"""
Loss-of-Life & Fatality Estimation Module (Phase 6).

WHAT IS ACTUALLY IMPLEMENTED HERE, which is not what this docstring used to say.
It listed three models. One is implemented, one was described but not written,
and one is absent entirely — and the function named after the missing one
computed something else under its name.

  1. **Graham (1999) / USBR DSO-99-06** — IMPLEMENTED. Fatality rate from threat
     zone severity, warning time band and public understanding.
     ``estimate_loss_of_life_graham``.

  2. **A depth-velocity saturating fatality rate** — IMPLEMENTED, and it is NOT
     Jonkman's published function. ``estimate_loss_of_life_depth_velocity``
     applies an exponential saturation in the depth-velocity product with an
     exponential warning-time decay. Its docstring used to state the log-normal
     ``F(d, v) = Phi((ln(d*v) - mu) / sigma)`` and the code has never computed
     that. The function is renamed to say what it is;
     ``estimate_loss_of_life_jonkman`` remains as a deprecated alias so existing
     callers keep working, and warns.

  3. **Jonkman (2008)** — QUARANTINED. ``estimate_loss_of_life_jonkman_2008``
     has the published log-normal SHAPE and raises until its mu and sigma are
     transcribed from the paper, following the same pattern as
     ``terrain/natural_dam.py``'s Walder & O'Connor and Peng & Zhang. A
     quarantined model that raises is safer than a plausible one that runs:
     these numbers become a casualty figure on a slide.

  4. **DeKay & McClelland (1993)** — ABSENT. Cited in this docstring for a long
     time and never written (docs/VERIFICATION_LOG.md row 11). Named here so the
     citation list stops implying an implementation.

References:
  - Graham, W.J. (1999) "A Procedure for Estimating Loss of Life Caused by Dam
    Failure", DSO-99-06, USBR.
  - Jonkman, S.N., Vrijling, J.K., Vrouwenvelder, A.C.W.M. (2008) "Methods for
    the estimation of loss of life due to floods", Natural Hazards 46(3):
    353-389; and Jonkman et al. (2008) "Loss of life due to floods", Journal of
    Flood Risk Management 1(1):43-56.
  - DeKay, M.L. & McClelland, G.H. (1993) "Predicting loss of life in cases of
    dam failure and flash flood", Risk Analysis 13(2):193-205.
"""

import warnings
from typing import Dict, Union

import numpy as np


def estimate_loss_of_life_graham(
    par: float,
    warning_time_min: float,
    flood_severity: str = "medium",
    understanding_level: str = "medium",
) -> Dict[str, float]:
    """
    Estimate loss of life using Graham (1989) USBR DSO-99-06 methodology.

    Fatality rates (F):
      Severe flood (high velocity/depth, structural destruction):
        - Warning < 15 min: F = 0.75
        - Warning 15-60 min: F = 0.20
        - Warning > 60 min: F = 0.01
      Medium flood (moderate depth/velocity):
        - Warning < 15 min: F = 0.15
        - Warning 15-60 min: F = 0.04
        - Warning > 60 min: F = 0.002
      Low flood (shallow depth):
        - Warning < 15 min: F = 0.01
        - Warning 15-60 min: F = 0.002
        - Warning > 60 min: F = 0.0002

    Args:
        par: Population at Risk (count)
        warning_time_min: Warning time available to population (minutes)
        flood_severity: 'low', 'medium', or 'high'/'severe'
        understanding_level: 'vague', 'medium', or 'good' (modifies fatality rate)

    Returns:
        Dict with estimated_fatalities, fatality_rate, par, warning_time_min
    """
    par = max(0.0, float(par))
    w_min = max(0.0, float(warning_time_min))
    severity = flood_severity.lower()

    if severity in ("high", "severe"):
        if w_min < 15.0:
            base_rate = 0.75
        elif w_min <= 60.0:
            base_rate = 0.20
        else:
            base_rate = 0.01
    elif severity in ("medium", "mod", "moderate"):
        if w_min < 15.0:
            base_rate = 0.15
        elif w_min <= 60.0:
            base_rate = 0.04
        else:
            base_rate = 0.002
    else:  # low
        if w_min < 15.0:
            base_rate = 0.01
        elif w_min <= 60.0:
            base_rate = 0.002
        else:
            base_rate = 0.0002

    # Adjust for population understanding level
    und = understanding_level.lower()
    if und in ("vague", "poor"):
        adj_factor = 1.5
    elif und in ("good", "high"):
        adj_factor = 0.7
    else:
        adj_factor = 1.0

    fatality_rate = min(1.0, base_rate * adj_factor)
    estimated_fatalities = par * fatality_rate

    return {
        "estimated_fatalities": float(estimated_fatalities),
        "fatality_rate": float(fatality_rate),
        "par": par,
        "warning_time_min": w_min,
        "flood_severity": flood_severity,
    }


#: Whether Jonkman (2008)'s log-normal mortality coefficients have been
#: transcribed from the paper and checked. They have NOT.
#:
#: Same quarantine as terrain/natural_dam.py's WALDER_OCONNOR_1997_VERIFIED and
#: PENG_ZHANG_2012_VERIFIED. The published model gives a separate (mu, sigma)
#: pair per hazard zone — breach, rapidly-rising, remaining — and applying the
#: wrong pair, or the right pair to the wrong zone definition, changes a
#: casualty estimate by an order of magnitude while still producing a number
#: that looks reasonable.
#:
#: TODO: UNVETTED — transcribe mu and sigma per zone, the zone definitions in
#: depth, rise rate and depth-velocity product, and the fitted event population.
#: docs/VERIFICATION_LOG.md row 32.
JONKMAN_2008_VERIFIED = False


class JonkmanModelUnverified(NotImplementedError):
    """Raised when the quarantined Jonkman (2008) model is called."""


def estimate_loss_of_life_jonkman_2008(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    population_grid: np.ndarray,
    warning_time_min: float = 30.0,
) -> Dict[str, float]:
    """
    Jonkman (2008) log-normal mortality functions. QUARANTINED — raises.

    The published model gives, per hazard zone,

        F_D(h) = Phi_N( (ln(h) - mu_N) / sigma_N )

    with Phi_N the standard normal CDF and a distinct (mu_N, sigma_N) for the
    breach zone, the zone with rapidly rising water, and the remaining zone.
    This function exists so the shape is in the codebase and the gap is
    visible; it raises until the coefficients are transcribed.

    Raises:
        JonkmanModelUnverified: always, while JONKMAN_2008_VERIFIED is False.
    """
    if not JONKMAN_2008_VERIFIED:
        raise JonkmanModelUnverified(
            "Jonkman (2008)'s log-normal mortality coefficients have not been "
            "transcribed from the paper. Each hazard zone has its own mu and "
            "sigma, and guessing them would produce a casualty figure that "
            "looks reasonable and is not. Use "
            "estimate_loss_of_life_depth_velocity for the screening estimate "
            "this repository does implement, or "
            "estimate_loss_of_life_graham for the USBR procedure. "
            "docs/VERIFICATION_LOG.md row 32."
        )
    raise AssertionError(
        "JONKMAN_2008_VERIFIED was set True without an implementation being "
        "supplied. Transcribe the coefficients before flipping the flag."
    )


def estimate_loss_of_life_depth_velocity(
    depth: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    population_grid: np.ndarray,
    warning_time_min: float = 30.0,
) -> Dict[str, float]:
    """
    Screening fatality rate from the depth-velocity product. NOT Jonkman (2008).

    This function was named ``estimate_loss_of_life_jonkman`` and its docstring
    stated ``F(d, v) = Phi((ln(d*v) - mu) / sigma)``. It has never computed
    that. What it computes, and what the name now says, is a saturating
    exponential in the depth-velocity product with an exponential warning-time
    decay:

        severe zone      F = min(0.90, 0.5 * (1 - exp(-0.4 * d*v)) * W)
        other wet zone   F = min(0.05, 0.02 * d * W)
        W                = exp(-0.03 * warning_time_min)

    The severe-zone boundary (d*v >= 1.5 m2/s or d >= 2.1 m) is the conventional
    one and is the only part with an external basis.

    TODO: UNVETTED — the four shape constants (0.5, 0.4, 0.02, 0.03) and both
    caps (0.90, 0.05) are working values with no published source. They are not
    Jonkman's, not Graham's, and not DeKay & McClelland's. Treat the output as
    an ordering of cells by hazard, not as a casualty count; the Graham
    procedure is the one to quote. docs/VERIFICATION_LOG.md row 32.

    Args:
        depth: 2D depth array (m)
        velocity_x: 2D velocity x (m/s)
        velocity_y: 2D velocity y (m/s)
        population_grid: 2D population density per cell
        warning_time_min: Warning lead time in minutes

    Returns:
        Dict with total_fatalities, mean_fatality_rate, total_par, and ``model``
        naming what produced them — so a report cannot attribute these numbers
        to Jonkman by reading the key they arrived under.
    """
    depth = np.asarray(depth, dtype=np.float32)
    vx = np.asarray(velocity_x, dtype=np.float32)
    vy = np.asarray(velocity_y, dtype=np.float32)
    pop = np.asarray(population_grid, dtype=np.float32)

    v_mag = np.sqrt(vx**2 + vy**2)
    dv = depth * v_mag  # Depth-velocity product (m2/s)

    # Jonkman severe zone threshold: dv >= 1.5 m2/s and depth >= 2.1m
    wet_mask = depth >= 0.1
    severe_mask = wet_mask & ((dv >= 1.5) | (depth >= 2.1))

    # Fatality rate calculation (Jonkman log-normal mortality)
    # For severe zone: mean fatality rate ~ 0.12 * exp(-0.03 * warning_min)
    warn_decay = np.exp(-0.03 * max(0.0, warning_time_min))

    fatality_rate = np.zeros_like(depth, dtype=np.float32)

    # Severe zone mortality
    fatality_rate[severe_mask] = np.minimum(0.9, 0.5 * (1.0 - np.exp(-0.4 * dv[severe_mask])) * warn_decay)
    # Non-severe wet zone mortality
    non_severe = wet_mask & ~severe_mask
    fatality_rate[non_severe] = np.minimum(0.05, 0.02 * depth[non_severe] * warn_decay)

    fatalities = fatality_rate * pop
    total_fatalities = float(np.sum(fatalities))
    total_par = float(np.sum(pop[wet_mask]))
    mean_rate = float(np.mean(fatality_rate[wet_mask])) if np.sum(wet_mask) > 0 else 0.0

    return {
        "total_fatalities": total_fatalities,
        "mean_fatality_rate": mean_rate,
        "total_par": total_par,
        "warning_time_min": warning_time_min,
        "model": "depth_velocity_saturating_screening",
        "model_is_published": False,
        "model_note": (
            "Saturating exponential in the depth-velocity product. NOT Jonkman "
            "(2008), whose log-normal form is quarantined in "
            "estimate_loss_of_life_jonkman_2008. Shape constants are unvetted; "
            "quote the Graham (1999) procedure for a defensible figure."
        ),
    }


def estimate_loss_of_life_jonkman(*args, **kwargs) -> Dict[str, float]:
    """
    Deprecated alias for ``estimate_loss_of_life_depth_velocity``.

    Kept so existing callers keep working, and warning because the name
    misattributes the result: this has never computed Jonkman's model. For the
    published log-normal see ``estimate_loss_of_life_jonkman_2008``, which is
    quarantined pending coefficient transcription.
    """
    warnings.warn(
        "estimate_loss_of_life_jonkman does not implement Jonkman (2008). It "
        "computes a saturating depth-velocity screening rate with unvetted "
        "constants. Call estimate_loss_of_life_depth_velocity by name, or "
        "estimate_loss_of_life_jonkman_2008 for the published model (which "
        "raises until its coefficients are transcribed).",
        DeprecationWarning,
        stacklevel=2,
    )
    return estimate_loss_of_life_depth_velocity(*args, **kwargs)
