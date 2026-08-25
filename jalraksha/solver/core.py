"""
2D shallow-water solver core (Phase 1).

Formulation
-----------
Cell-centred finite volume on a uniform Cartesian grid in a METRIC CRS.
Conserved variables U = (h, hu, hv). Well-balanced, not surface-gradient.

  - Spatial: MUSCL reconstruction on eta = b + h with the minmod limiter,
    Audusse et al. (2004) hydrostatic reconstruction at faces, HLLC
    approximate Riemann solver (see jalraksha.solver.flux).
  - Temporal: two-stage SSP-RK2 (Heun). Strong-stability-preserving, so the
    positivity that the first-order Audusse/HLLC update guarantees under
    CFL <= 1/2 survives the second-order extension.
  - Friction: Manning, applied point-implicitly after the RK update so it
    can never reverse a velocity (see flux.apply_friction).
  - Wetting/drying: Liang & Marche (2009). Depths below h_dry (default
    1e-6 m) are inert; velocity recovery uses Kurganov-Petrova
    desingularisation so a 1 micron film cannot produce a 100 m/s velocity.
    h_dry is a solver parameter, not a constant, because it sets a floor on
    wetting-front accuracy: at 1e-3 m the Ritter front stalls at 79% of the
    analytical position no matter how fine the grid.

What this solver is for
-----------------------
Tier-1 screening on 30 m Copernicus GLO-30. Arrival times and inundation
envelopes are the defensible products. Point depths on a 30 m grid in a
Himalayan gorge resolve 1-2 cells across the channel and are indicative
only — see the DEM caveats in the project documentation. This is a
Delft3D-CLASS solver; it is not the Deltares kernel.

Blocking gates (tests/test_solver.py)
-------------------------------------
  1. Lake at rest: |V| < 1e-8 m/s and |d(eta)| < 1e-6 m over 1000 steps on
     random bathymetry. Passes at machine precision by construction, not by
     tolerance tuning — see the C-property proof in flux.py.
  2. Mass conservation: < 0.1% volume change over 1000 steps with walls.
     Exact, because the reflective boundary gives identically zero mass flux.
  3. Dry-bed robustness: no NaN, no negative depth over 500 steps.
  4. Ritter dry-bed dam-break: L2 error decreases under refinement, and
     h(dam site) -> 4*h0/9.

References:
  - Toro (2001) Shock-Capturing Methods for Free-Surface Shallow Flows.
  - Audusse et al. (2004) SIAM J. Sci. Comput. 25(6), 2050-2065.
  - Liang & Marche (2009) Adv. Water Resour. 32(6), 873-884.
  - Kurganov & Petrova (2007) Commun. Math. Sci. 5(1), 133-160.
  - Gottlieb, Ketcheson & Shu (2009) J. Sci. Comput. 38, 251-289. (SSP-RK)
  - Chow (1959) Open-Channel Hydraulics. (Manning's n by surface type)
"""

from typing import Callable, Optional, Union

import numpy as np

from .flux import (
    G,
    H_DRY_DEFAULT,
    VELOCITY_MAX_DEFAULT,
    apply_friction,
    max_wave_speed_inverse_dt,
    tendencies_x,
    tendencies_y,
)
from .types import DTYPE, Grid, Result, State, create_result

# Ghost cells per side. Two are required: the MUSCL slope of the first
# interior cell needs its neighbour's neighbour.
PAD = 2

# Hard ceiling on the Courant number regardless of what the caller asks for.
#
# The positivity proof for Audusse/HLLC holds at CFL <= 1/2 for the additive
# 2D condition. MUSCL narrows that further in practice. Callers routinely
# pass the 1D textbook value 0.9, which is unstable for a dimensionally
# unsplit 2D update, so the request is clamped rather than honoured.
#
# 0.30 is measured, not inherited. On a 60x60 lake at rest over white-noise
# bathymetry of 20-40 m amplitude on a 30 m grid — the harshest bed the
# reconstruction can face, with bed steps several times the local depth —
# the worst at-rest residual |V| after 3000 steps, with the wet-fraction
# term of max_wave_speed_inverse_dt active, is:
#
#     CFL 0.45   5.7e-12   passes the 1e-8 gate but 40x above the floor,
#                          i.e. still growing slowly
#     CFL 0.40   1.3e-13   at the round-off floor
#     CFL 0.35   1.6e-13   at the round-off floor
#     CFL 0.30   1.4e-13   at the round-off floor
#
# 0.30 rather than 0.35 buys ~17% runtime as margin on a solver that gates
# the Phase 4 deliverable. Realistic terrain (1-in-10 valley, gorge with
# 60 m parabolic walls) is stable even at 0.45.
CFL_MAX = 0.30

# Absolute ceiling on a single step (s). Prevents a nearly-dry domain from
# taking one enormous step that then wets a cell far outside the CFL cone.
DT_MAX_DEFAULT = 30.0


class SWESolver:
    """
    Well-balanced 2D SWE solver: HLLC flux, Audusse reconstruction, MUSCL,
    SSP-RK2 integration, Manning friction, wet/dry treatment.

    Example:
        grid = Grid(nx=200, ny=200, dx=30.0, dy=30.0)
        state = create_state(grid, h_init, b_init=dem)
        solver = SWESolver(grid, manning_n=0.035, cfl=0.4)
        result = solver.run(state, t_end=3600.0)
    """

    def __init__(
        self,
        grid: Grid,
        manning_n: Union[float, np.ndarray] = 0.03,
        cfl: float = 0.30,
        boundary: str = "transmissive",
        use_muscl: bool = True,
        dt_max: float = DT_MAX_DEFAULT,
        h_dry: float = H_DRY_DEFAULT,
        velocity_max: float = VELOCITY_MAX_DEFAULT,
    ):
        """
        Initialise the solver.

        Args:
            grid: Spatial grid (must be a metric CRS)
            manning_n: Manning's n, scalar or per-cell array of shape (ny, nx).
                Chow (1959): 0.013-0.017 concrete, 0.030-0.035 natural channel,
                0.05-0.15 vegetated floodplain / built-up.
            cfl: Requested Courant number. Clamped to CFL_MAX = 0.30.
            boundary: "transmissive" (zero-gradient outflow, correct for a
                dam-break routing domain) or "reflective" (solid wall, used
                by the mass-conservation gate).
            use_muscl: Second-order reconstruction. False gives first-order,
                which is more diffusive but bulletproof — useful for triage.
            dt_max: Absolute cap on a single timestep (s).
            h_dry: Wet/dry threshold (m). Do not raise this to suppress
                spurious front velocities — it caps front accuracy. Use the
                velocity_max safety net instead.
            velocity_max: Magnitude cap on |V| (m/s), applied after friction.
                Pass 0 to disable. The default 60 m/s is roughly 2x the
                observed peaks at Malpasset (1959, ~30 m/s) and Chamoli
                (2021, ~25 m/s), so it clips only numerical outliers.
                Activations are counted and reported by describe().

        Raises:
            ValueError: on an unknown boundary type or a bad manning_n shape.
        """
        if boundary not in ("transmissive", "reflective", "wall"):
            raise ValueError(
                f"boundary must be 'transmissive' or 'reflective' (got {boundary!r})"
            )

        self.grid = grid
        self.nx = grid.nx
        self.ny = grid.ny
        self.dx = float(grid.dx)
        self.dy = float(grid.dy)
        self.boundary = "reflective" if boundary == "wall" else boundary
        self.use_muscl = bool(use_muscl)
        self.dt_max = float(dt_max)
        self.g = G
        self.h_dry = float(h_dry)
        self.velocity_max = float(velocity_max)
        if self.h_dry <= 0.0:
            raise ValueError(f"h_dry must be positive (got {h_dry})")

        # Record both so a caller can see that its request was clamped.
        self.cfl_requested = float(cfl)
        self.cfl = min(float(cfl), CFL_MAX)

        # A direction one cell thick has no interior faces, so it must not
        # enter the CFL condition (otherwise a 1D run gets a needlessly
        # halved timestep) and its ghost cells are always mirrored.
        self.active_x = self.nx > 1
        self.active_y = self.ny > 1

        self.manning_field = self._build_manning_field(manning_n)

        # Padded work arrays, allocated once and reused every stage.
        padded_shape = (self.ny + 2 * PAD, self.nx + 2 * PAD)
        self._h_pad = np.zeros(padded_shape, dtype=DTYPE)
        self._u_pad = np.zeros(padded_shape, dtype=DTYPE)
        self._v_pad = np.zeros(padded_shape, dtype=DTYPE)
        self._b_pad = np.zeros(padded_shape, dtype=DTYPE)
        self._d_h = np.zeros(padded_shape, dtype=DTYPE)
        self._d_hu = np.zeros(padded_shape, dtype=DTYPE)
        self._d_hv = np.zeros(padded_shape, dtype=DTYPE)

        self._interior = (slice(PAD, PAD + self.ny), slice(PAD, PAD + self.nx))

        # Diagnostics
        self.n_steps = 0
        self.dt_last = 0.0
        # Count of cells whose velocity hit velocity_max over the whole run.
        # Reported by describe() so a run cannot silently lean on the cap.
        self.n_velocity_capped = 0

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _build_manning_field(self, manning_n: Union[float, np.ndarray]) -> np.ndarray:
        """Broadcast Manning's n to a per-cell float64 field."""
        if np.isscalar(manning_n):
            if manning_n < 0:
                raise ValueError(f"manning_n must be >= 0 (got {manning_n})")
            return np.full((self.ny, self.nx), float(manning_n), dtype=DTYPE)

        field = np.ascontiguousarray(manning_n, dtype=DTYPE)
        if field.shape != (self.ny, self.nx):
            raise ValueError(
                f"manning_n array shape {field.shape} doesn't match grid {(self.ny, self.nx)}"
            )
        if np.any(field < 0):
            raise ValueError("manning_n array contains negative values")
        return field

    # ------------------------------------------------------------------
    # Timestep
    # ------------------------------------------------------------------

    def compute_cfl_timestep(self, state: State) -> float:
        """
        Adaptive timestep from the additive 2D CFL condition, with the
        Audusse bed-step correction.

            dt = cfl / max[ (|u| + c*(1 + r_x))/dx + (|v| + c*(1 + r_y))/dy ]

        where c = sqrt(g*h) and r is the largest upward bed step to a
        neighbour in that direction divided by the local depth (clipped at
        1). See max_wave_speed_inverse_dt for the derivation: r is zero on
        a flat bed, so this reduces to the textbook condition there.

        Args:
            state: Current solution state

        Returns:
            Stable timestep (s). Returns dt_max on a fully dry domain.
        """
        inverse_dt = max_wave_speed_inverse_dt(
            state.h,
            state.u,
            state.v,
            state.b,
            self.dx,
            self.dy,
            self.active_x,
            self.active_y,
            self.h_dry,
        )
        if inverse_dt <= 0.0:
            # Nothing wet: no wave to resolve.
            return self.dt_max
        return min(self.cfl / inverse_dt, self.dt_max)

    # ------------------------------------------------------------------
    # Boundary conditions
    # ------------------------------------------------------------------

    def _fill_ghosts(self) -> None:
        """
        Populate the ghost ring of the padded work arrays.

        transmissive: zero-gradient (copy the edge cell outward). Water leaves
            the domain and does not return. Correct for a routing reach; note
            it means volume is NOT conserved once the front exits.
        reflective: mirror h and b, negate the normal velocity. Gives
            identically zero mass flux through the wall, which is what makes
            the mass-conservation gate exact rather than approximate.

        A one-cell-thick direction is always mirrored so that v (or u) stays
        exactly zero and a nominally 1D run cannot leak sideways.
        """
        h, u, v, b = self._h_pad, self._u_pad, self._v_pad, self._b_pad
        lo, hi_x, hi_y = PAD, PAD + self.nx, PAD + self.ny

        reflect_x = self.boundary == "reflective" or not self.active_x
        reflect_y = self.boundary == "reflective" or not self.active_y

        # ---- x boundaries (left and right columns) ----
        for offset in range(PAD):
            ghost_left = lo - 1 - offset
            ghost_right = hi_x + offset
            if reflect_x:
                src_left = min(lo + offset, hi_x - 1)
                src_right = max(hi_x - 1 - offset, lo)
                sign = -1.0
            else:
                src_left = lo
                src_right = hi_x - 1
                sign = 1.0

            h[:, ghost_left] = h[:, src_left]
            b[:, ghost_left] = b[:, src_left]
            u[:, ghost_left] = sign * u[:, src_left]
            v[:, ghost_left] = v[:, src_left]

            h[:, ghost_right] = h[:, src_right]
            b[:, ghost_right] = b[:, src_right]
            u[:, ghost_right] = sign * u[:, src_right]
            v[:, ghost_right] = v[:, src_right]

        # ---- y boundaries (bottom and top rows) ----
        for offset in range(PAD):
            ghost_bot = lo - 1 - offset
            ghost_top = hi_y + offset
            if reflect_y:
                src_bot = min(lo + offset, hi_y - 1)
                src_top = max(hi_y - 1 - offset, lo)
                sign = -1.0
            else:
                src_bot = lo
                src_top = hi_y - 1
                sign = 1.0

            h[ghost_bot, :] = h[src_bot, :]
            b[ghost_bot, :] = b[src_bot, :]
            v[ghost_bot, :] = sign * v[src_bot, :]
            u[ghost_bot, :] = u[src_bot, :]

            h[ghost_top, :] = h[src_top, :]
            b[ghost_top, :] = b[src_top, :]
            v[ghost_top, :] = sign * v[src_top, :]
            u[ghost_top, :] = u[src_top, :]

    # ------------------------------------------------------------------
    # Spatial operator
    # ------------------------------------------------------------------

    def _tendencies(self, h: np.ndarray, u: np.ndarray, v: np.ndarray, b: np.ndarray):
        """
        Evaluate L(U) = -div F + S for the interior cells.

        Args:
            h, u, v, b: interior arrays, shape (ny, nx)

        Returns:
            (d_h, d_hu, d_hv) interior views of the tendency arrays.
        """
        interior = self._interior
        self._h_pad[interior] = h
        self._u_pad[interior] = u
        self._v_pad[interior] = v
        self._b_pad[interior] = b
        self._fill_ghosts()

        self._d_h.fill(0.0)
        self._d_hu.fill(0.0)
        self._d_hv.fill(0.0)

        if self.active_x:
            tendencies_x(
                self._h_pad,
                self._u_pad,
                self._v_pad,
                self._b_pad,
                self.dx,
                self._d_h,
                self._d_hu,
                self._d_hv,
                self.use_muscl,
                self.h_dry,
            )
        if self.active_y:
            tendencies_y(
                self._h_pad,
                self._u_pad,
                self._v_pad,
                self._b_pad,
                self.dy,
                self._d_h,
                self._d_hu,
                self._d_hv,
                self.use_muscl,
                self.h_dry,
            )

        return self._d_h[interior], self._d_hu[interior], self._d_hv[interior]

    @staticmethod
    def _to_primitive(h: np.ndarray, hu: np.ndarray, hv: np.ndarray, h_dry: float):
        """
        Recover (u, v) from conserved momentum with desingularisation.

        Kurganov & Petrova (2007):  u = 2 h (hu) / (h² + max(h, h_dry)²)

        For h >> h_dry this is hu/h to machine precision; as h -> 0 it tends
        smoothly to zero instead of dividing by a vanishing depth. A naive
        hu/h on a 1e-6 m film routinely yields velocities of 1e3 m/s, which
        then collapses the timestep to nothing and stalls the run.

        Args:
            h: depth (m), already clamped non-negative
            hu, hv: momentum components (m²/s)
            h_dry: wet/dry threshold (m)

        Returns:
            (u, v) velocity arrays (m/s), exactly zero on dry cells.
        """
        h_floor = np.maximum(h, h_dry)
        denom = h * h + h_floor * h_floor
        u = 2.0 * h * hu / denom
        v = 2.0 * h * hv / denom

        dry = h <= h_dry
        u[dry] = 0.0
        v[dry] = 0.0
        return u, v

    # ------------------------------------------------------------------
    # Time integration
    # ------------------------------------------------------------------

    def _advance(self, state: State, dt: float) -> State:
        """
        Advance one step with two-stage SSP-RK2 (Heun), then friction.

            U*   = U^n + dt L(U^n)
            U^n+1 = 1/2 U^n + 1/2 (U* + dt L(U*))

        Args:
            state: Current state (not modified)
            dt: Timestep (s)

        Returns:
            New State at t + dt.
        """
        bed = state.b
        h_old = state.h
        hu_old = state.h * state.u
        hv_old = state.h * state.v

        # --- Stage 1 ---
        d_h, d_hu, d_hv = self._tendencies(h_old, state.u, state.v, bed)
        h_1 = h_old + dt * d_h
        hu_1 = hu_old + dt * d_hu
        hv_1 = hv_old + dt * d_hv

        # A MUSCL overshoot at a front can dip a hair below zero. The
        # magnitude is ~1e-16 relative, far under the 0.1% mass gate.
        np.clip(h_1, 0.0, None, out=h_1)
        u_1, v_1 = self._to_primitive(h_1, hu_1, hv_1, self.h_dry)

        # --- Stage 2 ---
        d_h, d_hu, d_hv = self._tendencies(h_1, u_1, v_1, bed)
        h_new = 0.5 * (h_old + h_1 + dt * d_h)
        hu_new = 0.5 * (hu_old + hu_1 + dt * d_hu)
        hv_new = 0.5 * (hv_old + hv_1 + dt * d_hv)

        np.clip(h_new, 0.0, None, out=h_new)
        u_new, v_new = self._to_primitive(h_new, hu_new, hv_new, self.h_dry)

        # --- Friction (point-implicit, cannot reverse velocity) ---
        self.n_velocity_capped += apply_friction(
            h_new,
            u_new,
            v_new,
            self.manning_field,
            dt,
            self.h_dry,
            self.velocity_max,
        )

        self.n_steps += 1
        self.dt_last = dt

        return State(h=h_new, u=u_new, v=v_new, b=bed, t=state.t + dt)

    def step(self, state: State, dt: Optional[float] = None) -> State:
        """
        Advance one timestep, choosing dt from the CFL condition if not given.

        Args:
            state: Current state
            dt: Optional explicit timestep (s). Not CFL-checked — the caller
                owns stability if it passes this.

        Returns:
            New State at t + dt.
        """
        if dt is None:
            dt = self.compute_cfl_timestep(state)
        return self._advance(state, dt)

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def run(
        self,
        state: State,
        t_end: float,
        snapshot_interval: Optional[float] = None,
        on_snapshot: Optional[Callable[[State], None]] = None,
        max_steps: int = 2_000_000,
        verbose: bool = False,
    ) -> Result:
        """
        Integrate to t_end, accumulating the running-maxima rasters.

        Args:
            state: Initial state (not modified)
            t_end: End time (s, absolute — not a duration from state.t)
            snapshot_interval: If set, call on_snapshot at this cadence (s).
                CLAUDE.md specifies 60 s snapshots for output time series.
            on_snapshot: Callback receiving the State at each snapshot.
            max_steps: Safety cap; a stalled run raises rather than hangs.
            verbose: Print step diagnostics.

        Returns:
            Result with h_max, u_max, v_max, t_arrival, mass_error and the
            final State.

        Raises:
            RuntimeError: if the solution goes non-finite, or max_steps is hit
                before t_end.
        """
        state = state.copy()
        result = create_result(self.grid, state)
        result.update(state)

        cell_area = self.grid.area
        volume_initial = state.volume * cell_area
        next_snapshot = state.t + snapshot_interval if snapshot_interval else np.inf

        if on_snapshot is not None and snapshot_interval is not None:
            on_snapshot(state.copy())

        steps = 0
        while state.t < t_end - 1e-12:
            if steps >= max_steps:
                raise RuntimeError(
                    f"max_steps={max_steps} reached at t={state.t:.2f}s of {t_end:.2f}s. "
                    "The timestep has probably collapsed — check for a spurious "
                    "thin-film velocity or a DEM spike."
                )

            dt = self.compute_cfl_timestep(state)
            # Do not overshoot t_end or the next snapshot.
            dt = min(dt, t_end - state.t)
            if next_snapshot - state.t > 1e-12:
                dt = min(dt, next_snapshot - state.t)
            if dt <= 0.0:
                break

            state = self._advance(state, dt)
            steps += 1

            if not state.is_finite():
                raise RuntimeError(
                    f"Solution went non-finite at t={state.t:.3f}s (step {steps}). "
                    f"dt={dt:.3e}s, max depth={np.nanmax(state.h):.3f}m."
                )

            result.update(state)

            if state.t >= next_snapshot - 1e-9:
                if on_snapshot is not None:
                    on_snapshot(state.copy())
                next_snapshot += snapshot_interval

            if verbose and steps % 200 == 0:
                print(
                    f"  t={state.t:8.1f}s  dt={dt:7.4f}s  "
                    f"h_max={state.h.max():6.2f}m  |V|_max={state.speed.max():5.2f}m/s"
                )

        volume_final = state.volume * cell_area
        if volume_initial > 0.0:
            result.mass_error = abs(volume_final - volume_initial) / volume_initial
        result.n_steps = steps
        result.state = state
        result.t = state.t
        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def describe(self) -> dict:
        """Return the solver configuration, for provenance in exported metadata."""
        return {
            "scheme": "HLLC + Audusse hydrostatic reconstruction",
            "reconstruction": "MUSCL on eta=b+h, minmod" if self.use_muscl else "first-order",
            "time_integration": "SSP-RK2 (Heun)",
            "friction": "Manning, point-implicit",
            "wet_dry": f"Liang & Marche, h_dry={self.h_dry:g} m",
            "precision": "float64",
            "velocity_max": self.velocity_max,
            "velocity_cap_activations": self.n_velocity_capped,
            "cfl": self.cfl,
            "cfl_requested": self.cfl_requested,
            "cfl_clamped": self.cfl < self.cfl_requested,
            "boundary": self.boundary,
            "grid": f"{self.nx} x {self.ny} @ {self.dx} x {self.dy} m",
            "crs": self.grid.crs,
            "manning_n_range": [
                float(self.manning_field.min()),
                float(self.manning_field.max()),
            ],
        }
