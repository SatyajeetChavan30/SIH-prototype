"""
Analytical tests and blocking correctness gates for the Phase 1 2D SWE solver.

Blocking gates (must pass before any PR merge, per CLAUDE.md):
  1. Lake-at-rest — |V| < 1e-8 m/s and |d(eta)| < 1e-6 m over arbitrary
     bathymetry. Passes by construction via the Audusse C-property proof in
     jalraksha.solver.flux, not by tolerance relaxation.
  2. Mass conservation — < 0.1% volume change over 1000 steps behind walls.
  3. Dry-bed robustness — no NaN, no negative depth, no division blow-up.

Analytical tests (exact solutions):
  4. Ritter (1885) dry-bed dam-break — L2 convergence + h(dam) = 4*h0/9
  5. Stoker (1957) wet-bed dam-break — intermediate depth and shock position
  6. Thacker (1981) parabolic bowl — moving shoreline, oscillation period

References:
  - Ritter, A. (1892) Z. Ver. Deutsch. Ing. 36(33), 947-954.
  - Stoker, J.J. (1957) Water Waves. Interscience.
  - Thacker, W.C. (1981) J. Fluid Mech. 107, 499-508.
  - Toro, E.F. (2001) Shock-Capturing Methods for Free-Surface Shallow Flows.
  - Delestre et al. (2013) SWASHES benchmark library, Int. J. Numer. Meth.
    Fluids 72(3), 269-300.
"""

import numpy as np
import pytest

from jalraksha.solver.core import SWESolver
from jalraksha.solver.types import Grid, create_state

# Gravitational acceleration (m/s^2), matching jalraksha.solver.flux.G.
G = 9.81


# ======================================================================
# Blocking gate 1: lake at rest
# ======================================================================


class TestLakeAtRest:
    """
    Still water must stay still. This is the C-property (Bermudez & Vazquez
    1994) and it is the single most diagnostic test of a shallow-water code:
    a scheme that fails it manufactures currents out of terrain, which on a
    30 m Himalayan DEM means manufacturing a flood.
    """

    @pytest.mark.blocking
    def test_lake_at_rest_flat_bed(self):
        """Still water on a flat bed stays still to machine precision."""
        grid = Grid(nx=50, ny=50, dx=100.0, dy=100.0)
        h_init = np.ones((50, 50))
        b_init = np.zeros((50, 50))

        state = create_state(grid, h_init, b_init=b_init)
        solver = SWESolver(grid, manning_n=0.03, cfl=0.9)

        for _ in range(100):
            state = solver.step(state)

        u_max = float(np.max(np.abs(state.u)))
        v_max = float(np.max(np.abs(state.v)))
        h_error = float(np.max(np.abs(state.h - 1.0)))

        # Flat bed is the easy case: every flux and source term cancels
        # identically, so these are machine-epsilon assertions, not tolerances.
        assert u_max < 1e-12, f"Max u-velocity: {u_max:.3e}"
        assert v_max < 1e-12, f"Max v-velocity: {v_max:.3e}"
        assert h_error < 1e-12, f"Max depth error: {h_error:.3e}"

    @pytest.mark.blocking
    def test_lake_at_rest_random_bathymetry(self):
        """
        Still water over random topography stays still over 1000 steps.

        This is the blocking gate from CLAUDE.md. Random bathymetry means
        every interior face has a bed step, so the Audusse hydrostatic
        reconstruction and the bed-slope source term must cancel at every
        single face. Any sign or factor error shows up here immediately.
        """
        rng = np.random.default_rng(42)
        grid = Grid(nx=50, ny=50, dx=50.0, dy=50.0)

        # 5 m of bed relief, water surface flat at eta = 10 m.
        b_init = rng.uniform(0.0, 5.0, (50, 50))
        h_init = np.maximum(10.0 - b_init, 0.1)

        state = create_state(grid, h_init, b_init=b_init)
        eta_init = state.eta.copy()

        solver = SWESolver(grid, manning_n=0.03, cfl=0.9)
        for _ in range(1000):
            state = solver.step(state)

        vel_max = float(np.max(state.speed))
        eta_error = float(np.max(np.abs(state.eta - eta_init)))

        print(f"Lake-at-rest (random bathy): |V|max={vel_max:.3e} m/s, "
              f"eta error={eta_error:.3e} m")

        assert vel_max < 1e-8, f"Max velocity magnitude: {vel_max:.3e} m/s"
        assert eta_error < 1e-6, f"Max surface elevation error: {eta_error:.3e} m"

    @pytest.mark.blocking
    def test_lake_at_rest_with_dry_islands(self):
        """
        Still water with emergent topography stays still.

        Harder than the random-bathymetry case: some cells are fully dry and
        their neighbours are deep, so the wet/dry face treatment (Liang &
        Marche bed-face limiting) has to hold the shoreline in place. Without
        it, the classic failure is a spurious jet radiating off every island.
        """
        rng = np.random.default_rng(7)
        grid = Grid(nx=60, ny=60, dx=30.0, dy=30.0)

        # Bed spans 0-20 m; water surface at 10 m leaves roughly half dry.
        b_init = rng.uniform(0.0, 20.0, (60, 60))
        h_init = np.maximum(10.0 - b_init, 0.0)
        assert np.any(h_init == 0.0), "test setup must contain dry cells"
        assert np.any(h_init > 0.0), "test setup must contain wet cells"

        state = create_state(grid, h_init, b_init=b_init)
        wet = state.h > 0.0
        eta_init = state.eta.copy()

        solver = SWESolver(grid, manning_n=0.03, cfl=0.9)
        for _ in range(500):
            state = solver.step(state)

        vel_max = float(np.max(state.speed))
        # Only the initially-wet cells have a meaningful eta to preserve;
        # a dry cell's eta is just its bed elevation.
        eta_error = float(np.max(np.abs(state.eta[wet] - eta_init[wet])))

        print(f"Lake-at-rest (dry islands): |V|max={vel_max:.3e} m/s, "
              f"eta error={eta_error:.3e} m")

        assert vel_max < 1e-8, f"Max velocity magnitude: {vel_max:.3e} m/s"
        assert eta_error < 1e-6, f"Max surface elevation error: {eta_error:.3e} m"


# ======================================================================
# Blocking gate 2: mass conservation
# ======================================================================


class TestMassConservation:
    """Volume change < 0.1% over 1000 steps, per CLAUDE.md."""

    @pytest.mark.blocking
    def test_mass_conservation_dam_break_walls(self):
        """
        A dam-break inside a closed box conserves volume.

        Reflective walls are essential here. With transmissive boundaries the
        front leaves the domain and volume *should* drop, so a transmissive
        run tells you nothing about the discretisation. Note also that x0 is
        set negative: with the default x0=0 every cell centre is positive,
        the `x < 0` initial condition is empty, and the test would silently
        divide by a zero initial volume.
        """
        nx = 200
        grid = Grid(nx=nx, ny=1, dx=0.5, dy=1.0, x0=-50.0)

        h_init = np.where(grid.cell_centres_x() < 0.0, 1.0, 0.0)
        h_init = h_init.reshape(1, nx)

        state = create_state(grid, h_init)
        volume_init = state.volume * grid.area
        assert volume_init > 0.0, "initial condition is empty — test is vacuous"

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9, boundary="reflective")
        state_final = state
        for _ in range(1000):
            state_final = solver.step(state_final)

        volume_final = state_final.volume * grid.area
        mass_error = abs(volume_final - volume_init) / volume_init

        print(f"Mass conservation (1000 steps, walls): {mass_error * 100:.6f}%")
        assert mass_error < 1e-3, f"Mass change {mass_error * 100:.4f}% exceeds 0.1%"

    @pytest.mark.blocking
    def test_mass_conservation_2d_sloshing(self):
        """Volume is conserved for 2D sloshing over irregular bathymetry."""
        rng = np.random.default_rng(11)
        grid = Grid(nx=40, ny=40, dx=25.0, dy=25.0)

        b_init = rng.uniform(0.0, 3.0, (40, 40))
        # Tilted initial surface drives genuine 2D flow, not a trivial rest state.
        xx, _ = grid.cell_centres_2d()
        eta_init = 8.0 + 2.0 * (xx - xx.mean()) / (xx.max() - xx.min())
        h_init = np.maximum(eta_init - b_init, 0.0)

        state = create_state(grid, h_init, b_init=b_init)
        volume_init = state.volume * grid.area

        solver = SWESolver(grid, manning_n=0.03, cfl=0.9, boundary="reflective")
        for _ in range(1000):
            state = solver.step(state)

        volume_final = state.volume * grid.area
        mass_error = abs(volume_final - volume_init) / volume_init

        print(f"Mass conservation (2D sloshing): {mass_error * 100:.6f}%")
        assert float(np.max(state.speed)) > 0.1, "sloshing test did not actually move"
        assert mass_error < 1e-3, f"Mass change {mass_error * 100:.4f}% exceeds 0.1%"


class TestTransmissiveDrainage:
    """
    A blob of water on a tilted, transmissive-boundary plane must actually
    LEAVE the domain — a real coverage gap the mass-conservation gate above
    cannot see, since both of its cases use boundary="reflective" by design
    (walls are the correct choice for testing the discretisation in
    isolation). Neither test above can distinguish "conserves volume because
    physics is right" from "conserves volume because nothing can leave"; a
    dam-break domain uses boundary="transmissive" (solver/core.py's own
    default), and this was never separately exercised.

    Added after a real production failure: a Khadakwasla run plateaued at
    ~42% of released volume permanently retained despite transmissive
    boundaries, because the trapping was upstream of the boundary (an
    unbreached dam ridge plus unfilled DEM depressions) rather than at it —
    but that failure mode would have gone unnoticed even longer without a
    test that actually asserts *some* baseline level of drainage happens.
    """

    @pytest.mark.blocking
    def test_water_drains_off_a_tilted_open_plane(self):
        """A pool on a monotonic downhill slope must mostly drain to <1%."""
        grid = Grid(nx=60, ny=60, dx=20.0, dy=20.0)
        xx, _ = grid.cell_centres_2d()
        # Monotonic slope, high at x=0 down to low at the far edge -- a
        # single clear downhill path to the boundary, no interior pits.
        b_init = (xx - grid.x0) * 0.05

        # A pool of water sitting on the HIGH side of the slope.
        h_init = np.where(xx < grid.x0 + grid.nx * grid.dx * 0.25, 3.0, 0.0)

        state = create_state(grid, h_init, b_init=b_init)
        volume_init = state.volume * grid.area
        assert volume_init > 0.0, "initial condition is empty — test is vacuous"

        solver = SWESolver(grid, manning_n=0.03, cfl=0.9, boundary="transmissive")
        for _ in range(2000):
            state = solver.step(state)

        volume_final = state.volume * grid.area
        retained_frac = volume_final / volume_init

        print(f"Transmissive drainage: {retained_frac * 100:.3f}% of volume retained after 2000 steps")
        assert retained_frac < 0.01, (
            f"{retained_frac * 100:.2f}% of the pool is still in the domain after "
            f"2000 steps on an open, monotonic downhill slope with no interior "
            f"pits -- water that should exit is not exiting."
        )

        # The solver's own outflow accumulator must AGREE with the volume drop
        # measured here. Tying the two together is the point: the accumulator is
        # what a production run reports, and this test is the only place its
        # answer is checked against an independently computed one.
        exited = solver.volume_exited_m3
        assert exited == pytest.approx(volume_init - volume_final, rel=1e-6), (
            f"solver reports {exited:.3f} m3 exited but the domain lost "
            f"{volume_init - volume_final:.3f} m3 -- the accumulator and the "
            f"volume balance disagree."
        )
        assert exited / volume_init > 0.99

    @pytest.mark.blocking
    def test_a_closed_box_reports_no_outflow(self):
        """
        The other half of the accumulator's contract, and the one that catches
        it silently reporting drift as drainage.

        With reflective walls the mass flux through the boundary is identically
        zero, so volume_exited_m3 must be ~0. If it is not, the accumulator is
        measuring the scheme's own conservation error and every "X% of volume
        left the domain" claim built on it is inflated by that amount.
        """
        grid = Grid(nx=40, ny=40, dx=20.0, dy=20.0)
        xx, _ = grid.cell_centres_2d()
        h_init = np.where(xx < grid.x0 + grid.nx * grid.dx * 0.5, 2.0, 0.5)

        state = create_state(grid, h_init, b_init=np.zeros((grid.ny, grid.nx)))
        volume_init = state.volume * grid.area

        solver = SWESolver(grid, manning_n=0.03, cfl=0.9, boundary="reflective")
        for _ in range(500):
            state = solver.step(state)

        assert float(np.max(state.speed)) > 0.1, "closed-box test did not actually move"

        leaked = abs(solver.volume_exited_m3) / volume_init
        print(f"Closed box: accumulator reports {leaked * 100:.6f}% of volume 'exited'")
        assert leaked < 1e-3, (
            f"A reflective box reports {leaked * 100:.4f}% of its volume leaving "
            f"through walls that pass identically zero flux. The outflow "
            f"accumulator is picking up discretisation drift and would overstate "
            f"drainage in a transmissive run."
        )


# ======================================================================
# Blocking gate 3: dry-bed robustness
# ======================================================================


class TestDryBedRobustness:
    """No NaN, no negative depth, no division blow-up on a dry bed."""

    @pytest.mark.blocking
    def test_wetting_front_propagation(self):
        """A wetting front advancing over dry bed stays finite for 500 steps."""
        grid = Grid(nx=100, ny=100, dx=10.0, dy=10.0)

        h_init = np.zeros((100, 100))
        h_init[:, :50] = 1.0

        state = create_state(grid, h_init)
        solver = SWESolver(grid, manning_n=0.03, cfl=0.9)

        for step in range(500):
            state = solver.step(state)
            assert state.is_finite(), f"Non-finite value at step {step}"
            assert np.all(state.h >= -1e-12), (
                f"Negative depth at step {step}: {state.h.min():.3e}"
            )

        print(f"Dry-bed robustness: 500 steps, h in "
              f"[{state.h.min():.3e}, {state.h.max():.3f}] m")

    @pytest.mark.blocking
    def test_dam_break_onto_adverse_slope(self):
        """
        Water released against an uphill slope must stop, not tunnel through.

        This catches a subtly wrong bed-slope source term that a flat-bed
        lake-at-rest test cannot: the sign error only shows up when the
        source term has to actively decelerate the flow.
        """
        nx, ny = 150, 1
        grid = Grid(nx=nx, ny=ny, dx=10.0, dy=10.0, x0=0.0)

        x = grid.cell_centres_x()
        # Flat for the first 500 m, then a 10% ramp up to 100 m elevation.
        bed = np.where(x < 500.0, 0.0, 0.10 * (x - 500.0)).reshape(1, nx)
        # 20 m reservoir behind a notional dam at x = 200 m.
        h_init = np.where(x < 200.0, 20.0, 0.0).reshape(1, nx)

        state = create_state(grid, h_init, b_init=bed)
        solver = SWESolver(grid, manning_n=0.03, cfl=0.9, boundary="reflective")
        result = solver.run(state, t_end=600.0)

        eta_final = result.state.eta
        wet = result.state.h > 0.01

        # Nothing may climb above the initial reservoir surface (20 m). A
        # tolerance of 0.5 m allows for the run-up surge at the toe of the ramp.
        max_eta = float(np.max(eta_final[wet]))
        assert result.state.is_finite(), "solution went non-finite on adverse slope"
        assert max_eta < 20.5, f"Water climbed to eta={max_eta:.2f} m above 20 m reservoir"
        # And it must not have vanished either.
        assert result.mass_error < 1e-3, f"Mass error {result.mass_error * 100:.3f}%"


# ======================================================================
# Analytical test 4: Ritter dry-bed dam-break
# ======================================================================


def ritter_exact(x: np.ndarray, t: float, h_left: float = 1.0):
    """
    Ritter (1892) exact solution: dry-bed dam-break, frictionless, flat bed.

    Initial condition: h = h_left for x < 0, h = 0 for x > 0, u = 0.

    Three regions, with c0 = sqrt(g * h_left) and xi = x / t:
      1. xi < -c0            undisturbed reservoir, h = h_left, u = 0
      2. -c0 <= xi <= 2*c0   rarefaction fan,
                             u = (2/3)(xi + c0)
                             c = (2*c0 - xi)/3,  h = c^2 / g
      3. xi > 2*c0           dry bed

    The front therefore advances at 2*c0 (twice the still-water celerity) and
    the depth at the dam site is the classic 4*h_left/9.

    Args:
        x: Cell-centre coordinates (m), dam at x = 0
        t: Time (s), must be > 0
        h_left: Initial reservoir depth (m)

    Returns:
        (h_exact, u_exact) arrays matching the shape of x.
    """
    if t <= 0.0:
        raise ValueError("Ritter solution is only defined for t > 0")

    c0 = np.sqrt(G * h_left)
    xi = np.asarray(x, dtype=float) / t

    h_exact = np.zeros_like(xi)
    u_exact = np.zeros_like(xi)

    reservoir = xi < -c0
    h_exact[reservoir] = h_left
    u_exact[reservoir] = 0.0

    fan = (xi >= -c0) & (xi <= 2.0 * c0)
    xi_fan = xi[fan]
    celerity = (2.0 * c0 - xi_fan) / 3.0
    h_exact[fan] = celerity * celerity / G
    u_exact[fan] = 2.0 * (xi_fan + c0) / 3.0

    # Region 3 (xi > 2*c0) is already zero.
    return h_exact, u_exact


class TestRitterDamBreak:
    """Ritter (1892) 1D dry-bed dam-break."""

    def test_ritter_exact_self_consistency(self):
        """The reference solution itself must satisfy its known landmarks."""
        t = 5.0
        h_left = 1.0
        c0 = np.sqrt(G * h_left)

        # Depth at the dam site is 4/9 of the reservoir depth.
        h_dam, u_dam = ritter_exact(np.array([0.0]), t, h_left)
        assert h_dam[0] == pytest.approx(4.0 * h_left / 9.0, rel=1e-12)
        # Velocity at the dam site is (2/3) c0.
        assert u_dam[0] == pytest.approx(2.0 * c0 / 3.0, rel=1e-12)

        # Just inside the front the depth is small but non-zero; just outside, dry.
        h_edge, _ = ritter_exact(np.array([1.999 * c0 * t, 2.001 * c0 * t]), t, h_left)
        assert 0.0 < h_edge[0] < 1e-4
        assert h_edge[1] == 0.0

        # Just upstream of the rarefaction head the reservoir is undisturbed.
        h_head, _ = ritter_exact(np.array([-1.001 * c0 * t]), t, h_left)
        assert h_head[0] == pytest.approx(h_left, rel=1e-12)

    @pytest.mark.analytical
    def test_ritter_l2_convergence(self):
        """L2 error against the Ritter solution decreases under refinement."""
        h_left = 1.0
        t_end = 5.0
        # The domain must contain the whole wave at t_end, otherwise the
        # "exact" solution does not apply at the boundaries. The rarefaction
        # head reaches -c0*t = -15.7 m and the front reaches 2*c0*t = +31.3 m.
        x_min, x_max = -50.0, 50.0

        errors = []
        grid_sizes = [100, 200, 400]

        for nx in grid_sizes:
            dx = (x_max - x_min) / nx
            grid = Grid(nx=nx, ny=1, dx=dx, dy=1.0, x0=x_min)

            h_init = np.where(grid.cell_centres_x() < 0.0, h_left, 0.0).reshape(1, nx)
            state_init = create_state(grid, h_init)

            solver = SWESolver(grid, manning_n=0.0, cfl=0.9)
            result = solver.run(state_init, t_end)

            h_exact, _ = ritter_exact(grid.cell_centres_x(), t_end, h_left)
            l2_error = float(np.sqrt(np.mean((result.state.h.squeeze() - h_exact) ** 2)))
            errors.append(l2_error)

        rates = [
            np.log(errors[i] / errors[i + 1]) / np.log(2.0)
            for i in range(len(errors) - 1)
        ]
        print(f"Ritter L2 errors: {['%.4e' % e for e in errors]}")
        print(f"Ritter convergence rates: {['%.2f' % r for r in rates]}")

        assert errors[1] < errors[0], "Error must decrease with refinement"
        assert errors[2] < errors[1], "Error must decrease with further refinement"
        # A discontinuous dry front caps the achievable rate below the formal
        # second order of MUSCL; anything above 0.5 indicates real convergence
        # rather than a scheme that has saturated against a threshold floor.
        assert min(rates) > 0.5, f"Convergence has stalled: rates {rates}"

    @pytest.mark.analytical
    def test_ritter_depth_at_dam_site(self):
        """
        Depth at the dam site converges to 4*h0/9 = 0.4444.

        This is the sharpest single-number Ritter check: the value is
        independent of time, so it isolates the scheme's treatment of the
        rarefaction fan from any front-tracking error.
        """
        h_left = 1.0
        t_end = 5.0
        nx = 800
        grid = Grid(nx=nx, ny=1, dx=100.0 / nx, dy=1.0, x0=-50.0)

        h_init = np.where(grid.cell_centres_x() < 0.0, h_left, 0.0).reshape(1, nx)
        state = create_state(grid, h_init)

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9)
        result = solver.run(state, t_end)

        x_cells = grid.cell_centres_x()
        dam_index = int(np.argmin(np.abs(x_cells)))
        h_dam = float(result.state.h[0, dam_index])
        expected = 4.0 * h_left / 9.0

        print(f"Ritter h(dam)={h_dam:.5f}, exact={expected:.5f}, "
              f"rel err={abs(h_dam - expected) / expected:.2%}")
        assert h_dam == pytest.approx(expected, rel=0.02)

    @pytest.mark.analytical
    def test_ritter_front_position(self):
        """
        The wetting front reaches at least 85% of the analytical 2*c0*t.

        A finite-volume front always lags the analytical tip, because the tip
        has h -> 0 and any wet/dry threshold truncates it. The gate is set at
        85% rather than something tighter for that reason; what matters is
        that the lag shrinks under refinement (see the convergence test), not
        that it vanishes.
        """
        h_left = 1.0
        t_end = 5.0
        nx = 800
        grid = Grid(nx=nx, ny=1, dx=100.0 / nx, dy=1.0, x0=-50.0)

        h_init = np.where(grid.cell_centres_x() < 0.0, h_left, 0.0).reshape(1, nx)
        state = create_state(grid, h_init)

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9)
        result = solver.run(state, t_end)

        c0 = np.sqrt(G * h_left)
        front_exact = 2.0 * c0 * t_end

        x_cells = grid.cell_centres_x()
        wet = result.state.h.squeeze() > 1e-4
        front_computed = float(x_cells[wet].max())

        ratio = front_computed / front_exact
        print(f"Ritter front: computed={front_computed:.2f} m, "
              f"exact={front_exact:.2f} m ({ratio:.1%})")

        assert ratio > 0.85, f"Front only reached {ratio:.1%} of analytical position"
        # It must not run ahead of the characteristic either — that would mean
        # information travelling faster than the fastest wave speed.
        assert ratio < 1.02, f"Front overshot to {ratio:.1%} of analytical position"


# ======================================================================
# Analytical test 5: Stoker wet-bed dam-break
# ======================================================================


def stoker_intermediate_depth(h_left: float, h_right: float) -> float:
    """
    Solve for the intermediate (star-region) depth of a wet-bed dam-break.

    The left rarefaction gives     u* = 2 (c_left - c*)
    Rankine-Hugoniot for the shock gives
                                   u* = (h* - h_R) sqrt( (g/2)(h* + h_R)/(h* h_R) )
    Equating them gives one nonlinear equation in h*, with h_R < h* < h_left.

    Solved by bisection so the test has no SciPy dependency (SciPy is not a
    declared runtime dependency of the solver).

    Args:
        h_left: Upstream depth (m)
        h_right: Downstream depth (m), must be > 0 for the Stoker problem

    Returns:
        Intermediate depth h* (m).
    """
    if not h_right > 0.0:
        raise ValueError("Stoker problem requires a wet downstream bed (h_right > 0)")
    if not h_left > h_right:
        raise ValueError("Stoker problem requires h_left > h_right")

    c_left = np.sqrt(G * h_left)

    def residual(h_star: float) -> float:
        c_star = np.sqrt(G * h_star)
        u_rarefaction = 2.0 * (c_left - c_star)
        u_shock = (h_star - h_right) * np.sqrt(
            0.5 * G * (h_star + h_right) / (h_star * h_right)
        )
        return u_rarefaction - u_shock

    # residual(h_right) > 0 and residual(h_left) < 0, so a root is bracketed.
    low, high = h_right, h_left
    for _ in range(200):
        mid = 0.5 * (low + high)
        if residual(mid) > 0.0:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def stoker_exact(x: np.ndarray, t: float, h_left: float, h_right: float):
    """
    Stoker (1957) exact solution: wet-bed dam-break, frictionless, flat bed.

    Four regions, left to right: undisturbed reservoir, rarefaction fan,
    constant star region, undisturbed tailwater behind a shock.

    Args:
        x: Cell-centre coordinates (m), dam at x = 0
        t: Time (s), must be > 0
        h_left, h_right: Initial upstream / downstream depths (m)

    Returns:
        (h_exact, u_exact, shock_speed)
    """
    if t <= 0.0:
        raise ValueError("Stoker solution is only defined for t > 0")

    c_left = np.sqrt(G * h_left)
    h_star = stoker_intermediate_depth(h_left, h_right)
    c_star = np.sqrt(G * h_star)
    u_star = 2.0 * (c_left - c_star)
    shock_speed = h_star * u_star / (h_star - h_right)

    xi = np.asarray(x, dtype=float) / t
    h_exact = np.full_like(xi, h_right)
    u_exact = np.zeros_like(xi)

    reservoir = xi < -c_left
    h_exact[reservoir] = h_left
    u_exact[reservoir] = 0.0

    fan = (xi >= -c_left) & (xi <= u_star - c_star)
    xi_fan = xi[fan]
    celerity = (2.0 * c_left - xi_fan) / 3.0
    h_exact[fan] = celerity * celerity / G
    u_exact[fan] = 2.0 * (xi_fan + c_left) / 3.0

    star = (xi > u_star - c_star) & (xi < shock_speed)
    h_exact[star] = h_star
    u_exact[star] = u_star

    # xi >= shock_speed retains (h_right, 0), already set.
    return h_exact, u_exact, shock_speed


class TestStokerDamBreak:
    """Stoker (1957) 1D wet-bed dam-break — resolves a genuine shock."""

    def test_stoker_reference_solution_is_consistent(self):
        """The star state must satisfy both the rarefaction and shock relations."""
        h_left, h_right = 1.0, 0.1
        h_star = stoker_intermediate_depth(h_left, h_right)

        assert h_right < h_star < h_left

        c_left = np.sqrt(G * h_left)
        c_star = np.sqrt(G * h_star)
        u_from_rarefaction = 2.0 * (c_left - c_star)
        u_from_shock = (h_star - h_right) * np.sqrt(
            0.5 * G * (h_star + h_right) / (h_star * h_right)
        )
        assert u_from_rarefaction == pytest.approx(u_from_shock, rel=1e-9)

    @pytest.mark.analytical
    def test_stoker_star_depth_and_shock_position(self):
        """
        Computed star-region depth and shock position match Stoker.

        The star depth tests the rarefaction/shock balance and the shock
        position tests that HLLC gets the shock speed right — an HLL solver
        without the contact wave typically smears this and biases the speed.
        """
        h_left, h_right = 1.0, 0.1
        t_end = 4.0
        nx = 800
        x_min, x_max = -50.0, 50.0

        grid = Grid(nx=nx, ny=1, dx=(x_max - x_min) / nx, dy=1.0, x0=x_min)
        x_cells = grid.cell_centres_x()

        h_init = np.where(x_cells < 0.0, h_left, h_right).reshape(1, nx)
        state = create_state(grid, h_init)

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9)
        result = solver.run(state, t_end)
        h_num = result.state.h.squeeze()

        h_exact, _, shock_speed = stoker_exact(x_cells, t_end, h_left, h_right)
        h_star = stoker_intermediate_depth(h_left, h_right)
        shock_x_exact = shock_speed * t_end

        # Sample the star region well away from both the fan and the shock.
        c_left = np.sqrt(G * h_left)
        c_star = np.sqrt(G * h_star)
        u_star = 2.0 * (c_left - c_star)
        star_lo = (u_star - c_star) * t_end
        star_mid = 0.5 * (star_lo + shock_x_exact)
        star_window = np.abs(x_cells - star_mid) < 0.15 * (shock_x_exact - star_lo)
        h_star_num = float(np.mean(h_num[star_window]))

        # Shock position: last cell above the midpoint between h_star and h_right.
        threshold = 0.5 * (h_star + h_right)
        shock_x_num = float(x_cells[h_num > threshold].max())

        l2_error = float(np.sqrt(np.mean((h_num - h_exact) ** 2)))

        print(f"Stoker h*: num={h_star_num:.4f}, exact={h_star:.4f}")
        print(f"Stoker shock x: num={shock_x_num:.2f}, exact={shock_x_exact:.2f}")
        print(f"Stoker L2 error: {l2_error:.4e}")

        assert h_star_num == pytest.approx(h_star, rel=0.02)
        assert shock_x_num == pytest.approx(shock_x_exact, abs=3.0 * grid.dx + 0.5)
        assert l2_error < 0.02, f"Stoker L2 error {l2_error:.4e} too large"


# ======================================================================
# Analytical test 6: Thacker parabolic bowl
# ======================================================================


class TestThackerParabolicBowl:
    """
    Thacker (1981) planar-surface oscillation in a parabolic bowl.

    Bed:      b(x) = h0 * (x / a)^2
    Solution: the free surface stays a straight line, pivoting about the bowl
    axis, with spatially uniform velocity:

        omega = sqrt(2 g h0) / a
        u(t)  = -U0 sin(omega t)
        beta(t) = (U0 omega / g) cos(omega t)                 (surface slope)
        eta(x,t) = eta0 - (U0 beta0 / (4 omega)) cos(2 omega t) + beta(t) x

    This is the only analytical test here with a *moving shoreline over a
    curved bed*, which is exactly the configuration a dam-break inundation
    front sees on real terrain. A scheme that is not well-balanced damps the
    oscillation away within a couple of periods.
    """

    @staticmethod
    def _analytic_surface(x, t, h0, a, u0, eta0):
        omega = np.sqrt(2.0 * G * h0) / a
        beta0 = u0 * omega / G
        mean_term = eta0 - (u0 * beta0 / (4.0 * omega)) * np.cos(2.0 * omega * t)
        return mean_term + beta0 * np.cos(omega * t) * x, -u0 * np.sin(omega * t), omega

    def test_thacker_solution_satisfies_swe(self):
        """The reference solution must satisfy the SWE residuals numerically."""
        h0, a, u0, eta0 = 10.0, 1000.0, 2.0, 12.0
        x = np.linspace(-400.0, 400.0, 9)
        dt = 1e-3
        t = 30.0

        eta_m, u_m, omega = self._analytic_surface(x, t - dt, h0, a, u0, eta0)
        eta_0, u_0, _ = self._analytic_surface(x, t, h0, a, u0, eta0)
        eta_p, u_p, _ = self._analytic_surface(x, t + dt, h0, a, u0, eta0)

        bed = h0 * (x / a) ** 2
        h_m, h_c, h_p = eta_m - bed, eta_0 - bed, eta_p - bed

        # Momentum: du/dt + u du/dx + g d(eta)/dx = 0, with du/dx = 0.
        du_dt = (u_p - u_m) / (2.0 * dt)
        _, beta_slope = np.polyfit(x, eta_0, 1)[1], np.polyfit(x, eta_0, 1)[0]
        momentum_residual = np.max(np.abs(du_dt + G * beta_slope))
        assert momentum_residual < 1e-6, f"momentum residual {momentum_residual:.3e}"

        # Continuity: dh/dt + u dh/dx = 0 (u spatially uniform).
        #
        # edge_order=2 is required, not cosmetic. h is exactly quadratic in x
        # (A(t) + beta(t)x - h0 x^2/a^2), so a 3-point one-sided stencil is
        # exact for it, whereas numpy's default edge_order=1 is only
        # first-order and leaves an O(dx) error of h0*dx/a^2 * u ~ 2e-3 at the
        # two end samples — larger than the residual being measured.
        dh_dt = (h_p - h_m) / (2.0 * dt)
        dh_dx = np.gradient(h_c, x, edge_order=2)
        continuity_residual = np.max(np.abs(dh_dt + u_0 * dh_dx))
        assert continuity_residual < 1e-6, (
            f"continuity residual {continuity_residual:.3e}"
        )

        period = 2.0 * np.pi / omega
        assert period == pytest.approx(2.0 * np.pi * a / np.sqrt(2.0 * G * h0))

    @pytest.mark.analytical
    def test_thacker_oscillation_period(self):
        """
        The oscillation period matches 2*pi*a/sqrt(2*g*h0) within 5%.

        The period is the robust observable: amplitude damps under any
        finite-volume discretisation with a wet/dry threshold, but a period
        error means the momentum balance itself is wrong.
        """
        h0, a, u0, eta0 = 10.0, 1000.0, 2.0, 10.0
        omega_exact = np.sqrt(2.0 * G * h0) / a
        period_exact = 2.0 * np.pi / omega_exact

        nx = 400
        # Domain wide enough that the shoreline never reaches the boundary.
        x_min, x_max = -1500.0, 1500.0
        grid = Grid(nx=nx, ny=1, dx=(x_max - x_min) / nx, dy=1.0, x0=x_min)
        x_cells = grid.cell_centres_x()

        bed = h0 * (x_cells / a) ** 2
        eta_init, u_init, _ = self._analytic_surface(x_cells, 0.0, h0, a, u0, eta0)
        h_init = np.maximum(eta_init - bed, 0.0)

        state = create_state(
            grid,
            h_init.reshape(1, nx),
            u_init=np.where(h_init > 0.0, u_init, 0.0).reshape(1, nx),
            b_init=bed.reshape(1, nx),
        )

        # Frictionless: friction would damp the oscillation and confound the
        # period measurement with an amplitude decay.
        solver = SWESolver(grid, manning_n=0.0, cfl=0.9, boundary="reflective")

        # Track the mean velocity of the wet region; it crosses zero every T/2.
        samples_t, samples_u = [], []

        def record(snap):
            wet = snap.h > 0.05
            if np.any(wet):
                samples_t.append(snap.t)
                samples_u.append(float(np.mean(snap.u[wet])))

        result = solver.run(
            state,
            t_end=2.5 * period_exact,
            snapshot_interval=period_exact / 200.0,
            on_snapshot=record,
        )

        times = np.array(samples_t)
        velocities = np.array(samples_u)

        # Zero crossings, linearly interpolated.
        sign_change = np.where(np.sign(velocities[:-1]) != np.sign(velocities[1:]))[0]
        crossings = [
            times[i]
            + (times[i + 1] - times[i])
            * velocities[i]
            / (velocities[i] - velocities[i + 1])
            for i in sign_change
        ]

        print(f"Thacker: exact period={period_exact:.2f} s, "
              f"{len(crossings)} zero crossings at "
              f"{['%.1f' % c for c in crossings]}")

        assert result.state.is_finite(), "Thacker run went non-finite"
        assert len(crossings) >= 3, (
            f"Oscillation died out: only {len(crossings)} zero crossings in 2.5 periods"
        )

        half_periods = np.diff(crossings)
        period_measured = float(2.0 * np.mean(half_periods))
        rel_error = abs(period_measured - period_exact) / period_exact
        print(f"Thacker measured period={period_measured:.2f} s "
              f"({rel_error:.2%} error)")

        assert rel_error < 0.05, (
            f"Period error {rel_error:.2%}: measured {period_measured:.1f} s "
            f"vs exact {period_exact:.1f} s"
        )

    @pytest.mark.analytical
    def test_thacker_shoreline_amplitude_not_over_damped(self):
        """The shoreline excursion retains most of its amplitude after 2 periods."""
        h0, a, u0, eta0 = 10.0, 1000.0, 2.0, 10.0
        period = 2.0 * np.pi * a / np.sqrt(2.0 * G * h0)

        nx = 400
        grid = Grid(nx=nx, ny=1, dx=3000.0 / nx, dy=1.0, x0=-1500.0)
        x_cells = grid.cell_centres_x()
        bed = h0 * (x_cells / a) ** 2

        eta_init, u_init, _ = self._analytic_surface(x_cells, 0.0, h0, a, u0, eta0)
        h_init = np.maximum(eta_init - bed, 0.0)
        state = create_state(
            grid,
            h_init.reshape(1, nx),
            u_init=np.where(h_init > 0.0, u_init, 0.0).reshape(1, nx),
            b_init=bed.reshape(1, nx),
        )

        def right_shoreline(snap):
            wet = snap.h.squeeze() > 0.05
            return float(x_cells[wet].max()) if np.any(wet) else np.nan

        shoreline_initial = right_shoreline(state)

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9, boundary="reflective")

        excursions = []

        def record(snap):
            excursions.append(right_shoreline(snap))

        solver.run(
            state,
            t_end=2.0 * period,
            snapshot_interval=period / 100.0,
            on_snapshot=record,
        )

        excursions = np.array([e for e in excursions if np.isfinite(e)])
        swing = float(excursions.max() - excursions.min())

        # Analytical peak-to-peak shoreline swing, from eta(x,t) = bed(x).
        omega = np.sqrt(2.0 * G * h0) / a
        beta0 = u0 * omega / G
        # At maximum tilt the shoreline sits where h0 x^2/a^2 = eta_mean + beta0 x.
        eta_mean = eta0 - (u0 * beta0 / (4.0 * omega))
        coeff = h0 / (a * a)
        root_plus = (beta0 + np.sqrt(beta0**2 + 4.0 * coeff * eta_mean)) / (2.0 * coeff)
        root_minus = (-beta0 + np.sqrt(beta0**2 + 4.0 * coeff * eta_mean)) / (
            2.0 * coeff
        )
        swing_exact = abs(root_plus - root_minus)

        print(f"Thacker shoreline: initial={shoreline_initial:.1f} m, "
              f"swing={swing:.1f} m, exact swing~{swing_exact:.1f} m")

        # 70% retention over two full periods. Anything much below that means
        # the wet/dry treatment is bleeding energy at the moving shoreline.
        assert swing > 0.70 * swing_exact, (
            f"Shoreline swing {swing:.1f} m is only "
            f"{swing / swing_exact:.0%} of the analytical {swing_exact:.1f} m"
        )


# ======================================================================
# Provenance / honesty checks
# ======================================================================


class TestSolverProvenance:
    """The solver must report what it actually did, not what it aspires to."""

    def test_describe_reports_hllc_and_audusse(self):
        grid = Grid(nx=10, ny=10, dx=30.0, dy=30.0)
        info = SWESolver(grid).describe()

        assert "HLLC" in info["scheme"]
        assert "Audusse" in info["scheme"]
        assert info["precision"] == "float64"
        assert info["velocity_cap_activations"] == 0

    def test_cfl_request_above_ceiling_is_reported_as_clamped(self):
        """A caller passing the 1D textbook CFL of 0.9 must be told it was clamped."""
        grid = Grid(nx=10, ny=10, dx=30.0, dy=30.0)
        info = SWESolver(grid, cfl=0.9).describe()

        assert info["cfl_requested"] == 0.9
        assert info["cfl"] < 0.9
        assert info["cfl_clamped"] is True

    def test_velocity_cap_not_needed_for_a_normal_dam_break(self):
        """
        A well-resolved dam-break must not lean on the velocity safety cap.

        The cap exists so a pathological thin-film spike cannot destroy a run,
        but if it fires during an ordinary case then the reported velocities
        are the cap value rather than physics.
        """
        grid = Grid(nx=200, ny=1, dx=0.5, dy=1.0, x0=-50.0)
        h_init = np.where(grid.cell_centres_x() < 0.0, 1.0, 0.0).reshape(1, 200)
        state = create_state(grid, h_init)

        solver = SWESolver(grid, manning_n=0.0, cfl=0.9)
        solver.run(state, t_end=10.0)

        assert solver.n_velocity_capped == 0, (
            f"Velocity cap fired {solver.n_velocity_capped} times on a plain "
            "Ritter dam-break — reported speeds are not physical"
        )
