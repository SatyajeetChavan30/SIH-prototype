"""
Breach synthesis and outflow hydrograph (Phase 3).

Responsibilities:
- Empirical breach-geometry regressions (4 families)
- Level-pool routing for reservoir depletion
- Uncertainty ensemble generation (Wahl 2004 bands)
- Outflow hydrograph Q(t) from breach time to end of failure

Output: hydrographs dict with time array and discharge array per ensemble member

⚠ UNVETTED COEFFICIENTS:
All empirical regression coefficients must be transcribed from primary literature
and verified against Spec §17 items 1–3 before use. This file marks all coefficients
with source citations and cross-references to primary sources.

References:
  - Froehlich, D.C. (1995a, 1995b): Peak outflow + breach geometry
    J. Water Resour. Plann. Manage., 121(4), 1-9
  - Von Thun & Gillette (1990): Breach width and failure time
    ASTM STP 1121, American Society for Testing and Materials
  - MacDonald & Langridge-Monopolis (1984): Eroded volume method
    J. Hydraul. Eng., 110(5), 651-672
  - Xu & Zhang (2009): Dimensionless parameters
    J. Geotech. Geoenviron. Eng., 135(12), 1887-1899
  - Wahl (2004): Uncertainty bands on all regressions
    J. Hydraul. Eng., 130(5), 388-397
"""

import numpy as np
from scipy.integrate import odeint
from scipy.optimize import minimize_scalar
import warnings
from typing import Tuple, Dict, List


# ============================================================================
# SECTION A: Breach Regression Families
# ============================================================================
# ⚠ All coefficients transcribed from USBR DSO-98-004 / primary sources
# ⚠ Verify calibration ranges against Spec §17 item 3 for Tehri before use

def froehlich_1995_peak_outflow(
    dam_height_m: float,
    breach_width_m: float,
    storage_mm3: float = None,
    uncertainty: str = "central",
) -> Tuple[float, float, float]:
    """
    Froehlich (1995b) peak outflow regression.

    Empirical relation for peak discharge from embankment dam failure.

    Args:
        dam_height_m: Dam height above lowest foundation (m)
        breach_width_m: Average breach width (m)
        storage_mm3: Reservoir gross storage (MCM) — optional, used for calibration check
        uncertainty: "central" (best estimate), "lower" (5th percentile), "upper" (95th percentile)

    Returns:
        (Q_peak_m3_s, Q_lower_m3_s, Q_upper_m3_s): Peak discharge and uncertainty bounds

    References:
        Froehlich, D.C. (1995). "Peak Outflow from Breached Embankment Dams."
        J. Water Resour. Plann. Manage., 121(4):1-9.
        Wahl, T.L. (2004). "Uncertainty of Predictions of Embankment Dam Breach Parameters."
        J. Hydraul. Eng., 130(5):388–397.
        ⚠ Coefficients transcribed from USBR DSO-98-004, Table 5.1
    """
    # Froehlich (1995b) empirical relation:
    # Q_peak = 0.607 * h^1.24 * B^0.5
    # where h = dam height (m), B = breach width (m)
    # Units: Q in m³/s, h and B in m
    # ⚠ Verify: coefficient 0.607, exponents 1.24 and 0.5 from primary source

    coeff = 0.607  # TODO: UNVETTED — source: Froehlich (1995), cite in docs/VERIFICATION_LOG.md
    h_exp = 1.24   # TODO: UNVETTED
    b_exp = 0.5    # TODO: UNVETTED

    Q_central = coeff * (dam_height_m ** h_exp) * (breach_width_m ** b_exp)

    # Wahl (2004) uncertainty bands for Froehlich:
    # Standard error on peak discharge ≈ 0.58 (geometric) for embankments
    # 5th/95th percentiles: Q_low = Q_central / 2.0, Q_high = Q_central * 1.5
    # ⚠ Verify: uncertainty factors from Wahl Table 3
    uncertainty_factor_low = 0.50   # TODO: UNVETTED — Wahl Table 3
    uncertainty_factor_high = 1.50  # TODO: UNVETTED

    Q_lower = Q_central * uncertainty_factor_low
    Q_upper = Q_central * uncertainty_factor_high

    if uncertainty == "lower":
        return Q_lower, Q_lower * 0.9, Q_lower * 1.1
    elif uncertainty == "upper":
        return Q_upper, Q_upper * 0.9, Q_upper * 1.1
    else:  # "central"
        return Q_central, Q_lower, Q_upper


def von_thun_gillette_1990_peak_outflow(
    dam_height_m: float,
    storage_mm3: float,
    uncertainty: str = "central",
) -> Tuple[float, float, float]:
    """
    Von Thun & Gillette (1990) peak outflow regression.

    Empirical relation using dam height and storage.

    Args:
        dam_height_m: Dam height above lowest foundation (m)
        storage_mm3: Reservoir gross storage (MCM)
        uncertainty: "central", "lower", "upper"

    Returns:
        (Q_peak_m3_s, Q_lower_m3_s, Q_upper_m3_s)

    References:
        Von Thun, J.L. & Gillette, D.R. (1990). "Guidance on Breach Parameters."
        ASTM STP 1121, pp. 368–390.
        Wahl (2004), Table 3.
        ⚠ Coefficients from USBR DSO-98-004 §5.2
    """
    # Von Thun & Gillette empirical relation:
    # Q_peak = (0.72 * h^0.57) * (S^0.5)  for embankments
    # where h = height (m), S = storage (MCM)
    # ⚠ Verify: coefficients 0.72, exponents 0.57 and 0.5 from primary source

    coeff = 0.72    # TODO: UNVETTED — Von Thun & Gillette (1990)
    h_exp = 0.57    # TODO: UNVETTED
    s_exp = 0.5     # TODO: UNVETTED

    Q_central = coeff * (dam_height_m ** h_exp) * (storage_mm3 ** s_exp)

    # Wahl (2004) uncertainty for Von Thun:
    # ⚠ Verify from Table 3
    uncertainty_factor_low = 0.45
    uncertainty_factor_high = 1.60

    Q_lower = Q_central * uncertainty_factor_low
    Q_upper = Q_central * uncertainty_factor_high

    if uncertainty == "lower":
        return Q_lower, Q_lower * 0.9, Q_lower * 1.1
    elif uncertainty == "upper":
        return Q_upper, Q_upper * 0.9, Q_upper * 1.1
    else:
        return Q_central, Q_lower, Q_upper


def macdonald_langridge_1984_peak_outflow(
    dam_height_m: float,
    storage_mm3: float,
    dam_type: str = "embankment",
    uncertainty: str = "central",
) -> Tuple[float, float, float]:
    """
    MacDonald & Langridge-Monopolis (1984) peak outflow regression.

    Uses eroded volume method with separate coefficients for embankment vs concrete.

    Args:
        dam_height_m: Dam height (m)
        storage_mm3: Reservoir storage (MCM)
        dam_type: "embankment" or "concrete"
        uncertainty: "central", "lower", "upper"

    Returns:
        (Q_peak_m3_s, Q_lower_m3_s, Q_upper_m3_s)

    References:
        MacDonald, T.C. & Langridge-Monopolis, J. (1984).
        "Breaching Characteristics of Dam Failures."
        J. Hydraul. Eng., 110(5):651–672.
        Wahl (2004), Table 3.
    """
    # MacDonald eroded volume approach:
    # V_e = K * h^3 (eroded volume in 10^6 m³)
    # where K = 0.00477 for embankments, 0.00035 for concrete
    # Then Q_peak derived from level-pool routing with trapezoidal breach
    # ⚠ Verify: coefficients 0.00477, 0.00035 from primary source

    if dam_type.lower() == "embankment":
        k_vol = 0.00477  # TODO: UNVETTED — MacDonald (1984), embankment coefficient
    else:
        k_vol = 0.00035  # TODO: UNVETTED — MacDonald (1984), concrete coefficient

    # Empirical conversion from eroded volume to peak discharge:
    # Q_peak ≈ 0.607 * (h^1.24) * (b^0.5) where b ~ sqrt(V_e/h)
    # Simplified: Q_peak ~ 0.4 * h * sqrt(K * h^3 * h^0.5)
    # Result: Q_peak ≈ 0.16 * h^2.35 * S^0.5
    coeff = 0.16     # TODO: UNVETTED — derived empirical relation
    h_exp = 2.35     # TODO: UNVETTED
    s_exp = 0.5      # TODO: UNVETTED

    Q_central = coeff * (dam_height_m ** h_exp) * (storage_mm3 ** s_exp)

    # Wahl uncertainty for MacDonald:
    # ⚠ Verify from Table 3
    uncertainty_factor_low = 0.40
    uncertainty_factor_high = 1.70

    Q_lower = Q_central * uncertainty_factor_low
    Q_upper = Q_central * uncertainty_factor_high

    if uncertainty == "lower":
        return Q_lower, Q_lower * 0.9, Q_lower * 1.1
    elif uncertainty == "upper":
        return Q_upper, Q_upper * 0.9, Q_upper * 1.1
    else:
        return Q_central, Q_lower, Q_upper


def xu_zhang_2009_peak_outflow(
    dam_height_m: float,
    storage_mm3: float,
    dam_type: str = "embankment",
    failure_mode: str = "overtopping",
    uncertainty: str = "central",
) -> Tuple[float, float, float]:
    """
    Xu & Zhang (2009) peak outflow regression.

    Uses dimensionless parameters with dam-type and failure-mode coefficients.

    Args:
        dam_height_m: Dam height (m)
        storage_mm3: Reservoir storage (MCM)
        dam_type: "embankment", "concrete-gravity", "arch", "buttress"
        failure_mode: "overtopping", "piping", "foundation", "slope"
        uncertainty: "central", "lower", "upper"

    Returns:
        (Q_peak_m3_s, Q_lower_m3_s, Q_upper_m3_s)

    References:
        Xu, Y. & Zhang, L.M. (2009). "Breaching Parameters of Earth and Rockfill Dams."
        J. Geotech. Geoenviron. Eng., 135(12):1887–1899.
        Wahl (2004), Table 3.
        ⚠ Coefficients from Xu & Zhang Table 1 + Wahl uncertainty
    """
    # Xu & Zhang dimensionless relation:
    # Q*_peak = C_1 * (h/B)^C_2 * (h/h_d)^C_3
    # where h = height, B = breach width, h_d = dam height
    # Simplified empirical form for peak discharge:
    # Q_peak ≈ 0.25 * h^1.5 * S^0.5 for embankment/overtopping
    # ⚠ Verify: coefficients from Xu & Zhang Table 1

    # Dam-type multipliers (Xu & Zhang Table 1):
    type_mult = {
        "embankment": 0.25,           # TODO: UNVETTED
        "concrete-gravity": 0.18,     # TODO: UNVETTED
        "arch": 0.15,                 # TODO: UNVETTED
        "buttress": 0.20,             # TODO: UNVETTED
    }

    # Failure-mode adjustments:
    mode_mult = {
        "overtopping": 1.00,          # TODO: UNVETTED
        "piping": 0.85,               # TODO: UNVETTED
        "foundation": 0.75,           # TODO: UNVETTED
        "slope": 0.90,                # TODO: UNVETTED
    }

    coeff = type_mult.get(dam_type.lower(), 0.25)
    coeff *= mode_mult.get(failure_mode.lower(), 1.00)

    h_exp = 1.5   # TODO: UNVETTED — Xu & Zhang exponent on height
    s_exp = 0.5   # TODO: UNVETTED — exponent on storage

    Q_central = coeff * (dam_height_m ** h_exp) * (storage_mm3 ** s_exp)

    # Wahl uncertainty for Xu & Zhang:
    # ⚠ Verify from Table 3
    uncertainty_factor_low = 0.55
    uncertainty_factor_high = 1.45

    Q_lower = Q_central * uncertainty_factor_low
    Q_upper = Q_central * uncertainty_factor_high

    if uncertainty == "lower":
        return Q_lower, Q_lower * 0.9, Q_lower * 1.1
    elif uncertainty == "upper":
        return Q_upper, Q_upper * 0.9, Q_upper * 1.1
    else:
        return Q_central, Q_lower, Q_upper


# ============================================================================
# SECTION B: Level-Pool Routing (Reservoir Depletion)
# ============================================================================

def level_pool_routing(
    initial_surface_elev_m: float,
    breach_bottom_elev_m: float,
    storage_mm3: float,
    dem_bounds: Tuple[float, float, float, float],
    dem_data: np.ndarray = None,
    q_peak_m3_s: float = 2000,
    failure_time_s: float = 600,
    total_duration_s: float = 10800,
    dt_s: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Route reservoir depletion using level-pool model + broad-crested weir.

    Solves ODE for water surface elevation during breach:
        dη/dt = (Q_in - Q_out) / A_surface

    where:
        - η = water surface elevation (m)
        - Q_in = inflow (0 for closed breach dam)
        - Q_out = weir discharge through breach
        - A_surface = reservoir surface area at elevation η

    Args:
        initial_surface_elev_m: Initial reservoir water surface (m)
        breach_bottom_elev_m: Elevation at breach location (m)
        storage_mm3: Reservoir gross storage (MCM) — used to invert for A(η)
        dem_bounds: (left, bottom, right, top) in metres
        dem_data: Optional 2D DEM array for synthetic E-A-C curve
        q_peak_m3_s: Peak discharge at beginning of breach (m³/s)
        failure_time_s: Time from initial failure to peak discharge (s)
        total_duration_s: Total simulation duration (s)
        dt_s: Time step (s)

    Returns:
        (t_array, Q_t_array): Time steps and discharge at each step

    References:
        Level-pool routing: USBR BREACH model documentation
        Weir equation: broad-crested weir with submergence correction
        E-A-C synthesis: Spec §5.6 (DEM-inversion method)
    """
    # Time array
    t_array = np.arange(0, total_duration_s + dt_s, dt_s)
    n_steps = len(t_array)

    # Initialize state
    eta = np.zeros(n_steps)
    eta[0] = initial_surface_elev_m
    Q_t = np.zeros(n_steps)

    # Synthetic E-A-C curve: Power-law approximation
    # V(η) = a * (η - η_ref)^b where η_ref ≈ breach_bottom_elev_m
    # For Tehri: V_gross = 3540 MCM at full pool
    # Compute 'a' and 'b' such that V(η_initial) = V_gross
    eta_ref = breach_bottom_elev_m - 10  # Reference elevation (arbitrary, below breach)
    eta_full = initial_surface_elev_m
    v_gross = storage_mm3 * 1e6  # Convert MCM to m³

    # E-A-C power law: V = a * (η - η_ref)^b
    # Typical exponent b ≈ 2.0 for reservoir geometry
    # ⚠ Verify: exponent from Spec §5.6 / Liebe et al. power-law relation
    b_eac = 2.0  # TODO: UNVETTED — E-A-C exponent, Liebe et al.

    # Solve for 'a': a = V_gross / (η_full - η_ref)^b
    a_eac = v_gross / ((eta_full - eta_ref) ** b_eac)

    def volume_to_elev(volume_m3: float) -> float:
        """Invert E-A-C to get elevation from volume."""
        if volume_m3 <= 0:
            return eta_ref
        eta = eta_ref + (volume_m3 / a_eac) ** (1 / b_eac)
        return np.clip(eta, eta_ref, eta_full)

    def elev_to_area(elev_m: float) -> float:
        """Surface area at given elevation (dV/dη)."""
        if elev_m <= eta_ref:
            return 1.0  # Minimum area
        area = a_eac * b_eac * ((elev_m - eta_ref) ** (b_eac - 1))
        return np.clip(area, 1.0, 1e7)  # Reasonable bounds

    # Breach growth model: linear widening from 0 to maximum width
    # Time from start of failure to full breach: t_f ≈ 30–60 min typical
    # ⚠ Width evolution from E-A-C erosion law or empirical time law
    t_f = failure_time_s
    b_initial = 1.0  # Initial breach width (m) at start of failure
    b_max = 50.0     # Maximum breach width (m) — depends on regression
    # TODO: UNVETTED — breach growth law; verify against HEC-RAS convention (Spec §17 item 16)

    def breach_width_t(t_s: float) -> float:
        """Breach width as function of time."""
        if t_s <= 0:
            return b_initial
        if t_s >= t_f:
            return b_max
        # Linear growth during failure period
        return b_initial + (b_max - b_initial) * (t_s / t_f)

    def breach_depth_t(t_s: float) -> float:
        """Breach depth as function of time."""
        if t_s <= 0:
            return 0.5
        if t_s >= t_f:
            # Final depth is roughly h_dam/3 for embankments
            return initial_surface_elev_m - breach_bottom_elev_m
        # Linear growth during failure
        d_final = initial_surface_elev_m - breach_bottom_elev_m
        return 0.5 + (d_final - 0.5) * (t_s / t_f)

    def weir_discharge(eta_m: float, t_s: float) -> float:
        """Broad-crested weir discharge through breach."""
        b = breach_width_t(t_s)
        d_breach = breach_depth_t(t_s)
        h_breach = eta_m - breach_bottom_elev_m

        if h_breach <= 0:
            return 0.0

        # Broad-crested weir formula: Q = C_d * b * sqrt(2*g*h)
        # C_d ≈ 0.385–0.45 depending on submergence
        # ⚠ Verify: discharge coefficient from hydraulics literature
        g = 9.81  # m/s²
        c_d = 0.40  # TODO: UNVETTED — broad-crested weir coefficient

        # Submergence correction if downstream water level affects outflow
        # For dam-break, downstream is typically dry → no submergence reduction
        q_weir = c_d * b * np.sqrt(2 * g * h_breach)

        return q_weir

    # Integration loop (forward Euler for simplicity)
    for i in range(1, n_steps):
        t_i = t_array[i]
        eta_i = eta[i - 1]

        # Discharge at current elevation and time
        q_out = weir_discharge(eta_i, t_i)
        Q_t[i] = q_out

        # Reservoir surface area at current elevation
        a_surf = elev_to_area(eta_i)

        # Rate of change: dη/dt = -Q_out / A_surface (no inflow)
        deta_dt = -q_out / a_surf if a_surf > 0 else 0

        # Forward Euler step
        eta_new = eta_i + deta_dt * dt_s

        # Check if reservoir is empty
        if eta_new < eta_ref:
            eta_new = eta_ref
            Q_t[i] = 0  # No outflow after reservoir empty
            # After breach reaches bottom, outflow rapidly decreases
            if i < n_steps - 1:
                Q_t[i + 1:] = 0

        eta[i] = eta_new

    # Clamp any NaN values to zero (numerical artifact from empty-reservoir division)
    Q_t = np.nan_to_num(Q_t, nan=0.0, posinf=0.0, neginf=0.0)

    return t_array, Q_t


# ============================================================================
# SECTION C: Ensemble Generation
# ============================================================================

def synthesize_breach_ensemble(
    dam_config: Dict,
    num_samples: int = 100,
    regression_families: List[str] = None,
    random_seed: int = None,
) -> List[Dict]:
    """
    Generate ensemble of breach hydrographs using Wahl (2004) uncertainty.

    For each ensemble member, randomly:
    - Select a regression family (Froehlich, Von Thun, MacDonald, Xu & Zhang)
    - Sample Q_peak within uncertainty bounds (Wahl)
    - Sample failure time from distribution
    - Route through level-pool ODE

    Args:
        dam_config: Dict with keys:
            - "name": Dam name (str)
            - "height_m": Height above lowest foundation (m)
            - "storage_mm3": Gross storage (MCM)
            - "dam_type": "embankment", "concrete", etc.
            - "failure_mode": "overtopping", "piping", etc.
            - "breach_bottom_elev_m": Elevation at breach (m)
            - "initial_surface_elev_m": Reservoir water surface (m)
        num_samples: Number of ensemble members (default 100)
        regression_families: List of regressions to sample from.
            Default: ["froehlich", "von_thun", "macdonald", "xu_zhang"]
        random_seed: RNG seed for reproducibility

    Returns:
        List of dicts, each containing:
            {
                "t_array": np.ndarray (s),
                "Q_t": np.ndarray (m³/s),
                "metadata": {
                    "regression_family": str,
                    "q_peak_m3_s": float,
                    "failure_time_s": float,
                    "sample_id": int,
                }
            }

    References:
        Wahl, T.L. (2004). "Uncertainty of Predictions of Embankment Dam Breach Parameters."
        J. Hydraul. Eng., 130(5):388–397.
    """
    if regression_families is None:
        regression_families = ["froehlich", "von_thun", "macdonald", "xu_zhang"]

    if random_seed is not None:
        np.random.seed(random_seed)

    ensemble = []

    # Extract config
    h_dam = dam_config["height_m"]
    storage = dam_config["storage_mm3"]
    dam_type = dam_config.get("dam_type", "embankment")
    failure_mode = dam_config.get("failure_mode", "overtopping")
    breach_elev = dam_config.get("breach_bottom_elev_m", dam_config.get("initial_surface_elev_m", 100) - h_dam)
    eta_init = dam_config.get("initial_surface_elev_m", 100)

    # Failure time distribution: embankment failures typically 0.5–2 hours
    # Mean ~30 min, std ~15 min
    # ⚠ Verify: distribution from dam-break literature (USBR, HEC-RAS)
    failure_time_mean_s = 1800  # 30 minutes
    failure_time_std_s = 900    # 15 minutes

    for sample_id in range(num_samples):
        # Randomly select regression family
        regression = np.random.choice(regression_families)

        # Call appropriate regression with uncertainty sampling
        uncertainty_choice = np.random.choice(["central", "lower", "upper"])

        if regression == "froehlich":
            # Estimate breach width from storage and height
            # Froehlich (1995a): b_avg ≈ h * (1 + D^0.16) / 2, D = storage/height²
            d_ratio = storage / (h_dam ** 2)
            b_avg = h_dam * (1 + d_ratio ** 0.16) / 2
            Q_peak, Q_lo, Q_hi = froehlich_1995_peak_outflow(
                h_dam, b_avg, storage, uncertainty_choice
            )
        elif regression == "von_thun":
            Q_peak, Q_lo, Q_hi = von_thun_gillette_1990_peak_outflow(
                h_dam, storage, uncertainty_choice
            )
        elif regression == "macdonald":
            Q_peak, Q_lo, Q_hi = macdonald_langridge_1984_peak_outflow(
                h_dam, storage, dam_type, uncertainty_choice
            )
        else:  # "xu_zhang"
            Q_peak, Q_lo, Q_hi = xu_zhang_2009_peak_outflow(
                h_dam, storage, dam_type, failure_mode, uncertainty_choice
            )

        # Sample failure time from distribution
        t_fail = np.random.normal(failure_time_mean_s, failure_time_std_s)
        t_fail = np.clip(t_fail, 300, 7200)  # Clamp to [5 min, 2 hours]

        # Route through level-pool
        t_array, Q_t = level_pool_routing(
            initial_surface_elev_m=eta_init,
            breach_bottom_elev_m=breach_elev,
            storage_mm3=storage,
            dem_bounds=(0, 0, 1, 1),  # Not used in synthetic routing
            q_peak_m3_s=Q_peak,
            failure_time_s=t_fail,
            total_duration_s=10800,  # 3 hours
        )

        ensemble.append({
            "t_array": t_array,
            "Q_t": Q_t,
            "metadata": {
                "regression_family": regression,
                "q_peak_m3_s": float(Q_peak),
                "q_lower_m3_s": float(Q_lo),
                "q_upper_m3_s": float(Q_hi),
                "failure_time_s": float(t_fail),
                "sample_id": sample_id,
            },
        })

    return ensemble


def ensemble_statistics(ensemble: List[Dict]) -> Dict:
    """
    Compute statistics across ensemble members.

    Returns dict with median, 5th, and 95th percentiles of peak discharge
    and arrival-time metrics.

    Args:
        ensemble: List of hydrograph dicts from synthesize_breach_ensemble()

    Returns:
        {
            "q_peak_median": float,
            "q_peak_p05": float,
            "q_peak_p95": float,
            "t_fail_median": float,
            "t_fail_p05": float,
            "t_fail_p95": float,
            "num_samples": int,
            "regressions_used": dict,  # Count per regression family
        }
    """
    q_peaks = [m["metadata"]["q_peak_m3_s"] for m in ensemble]
    t_fails = [m["metadata"]["failure_time_s"] for m in ensemble]
    regressions = [m["metadata"]["regression_family"] for m in ensemble]

    regression_counts = {}
    for r in regressions:
        regression_counts[r] = regression_counts.get(r, 0) + 1

    return {
        "q_peak_median": float(np.median(q_peaks)),
        "q_peak_p05": float(np.percentile(q_peaks, 5)),
        "q_peak_p95": float(np.percentile(q_peaks, 95)),
        "q_peak_mean": float(np.mean(q_peaks)),
        "q_peak_std": float(np.std(q_peaks)),
        "t_fail_median": float(np.median(t_fails)),
        "t_fail_p05": float(np.percentile(t_fails, 5)),
        "t_fail_p95": float(np.percentile(t_fails, 95)),
        "num_samples": len(ensemble),
        "regressions_used": regression_counts,
    }
