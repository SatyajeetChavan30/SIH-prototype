"""
Phase 7 SPH near-field test suite.

WHAT CHANGED AND WHY. This file used to test `SPHNearFieldSolver` from
jalraksha/sph/core.py — a class that was not SPH. It had no kernel, no
neighbour search and no density evolution; `step()` applied the same
acceleration to every particle and discarded the Tait pressure it computed. Its
tests passed because they asserted only that particles moved, which ballistic
motion satisfies. The class is gone and those tests with it:

    test_tait_pressure_computation      - removed; the EOS is now PySPH's
    test_solver_step_updates_positions  - removed; replaced by the physical
                                          gates below, which a ballistic
                                          integrator could not pass

The near-field solver is now jalraksha.sph.pysph_runner, wrapping PySPH's
WCSPHScheme. The gates here check properties a correct SPH scheme must have and
a fake cannot fake: an energy bound derived from the available head, hydrostatic
equilibrium in still water, determinism, and responsiveness to terrain and dam
geometry.

References:
  - Monaghan, J.J. (1994) "Simulating Free Surface Flows with SPH",
    J. Comput. Phys. 110(2):399-406.
  - Ramachandran et al. (2021) "PySPH", ACM TOMS 47(4):1-38.
"""

import numpy as np
import pytest

from jalraksha.sph.domain import NearFieldDomain, generate_near_field_particles
from jalraksha.sph.coupling import handoff_swe_to_sph, extract_sph_free_surface
from jalraksha.sph.pysph_runner import (
    SPHUnavailableError,
    hydrostatic_density,
    is_pysph_available,
    orient_downhill,
    run_near_field_sph,
    run_still_water_validation,
)

PYSPH_OK, PYSPH_DETAIL = is_pysph_available()
requires_pysph = pytest.mark.skipif(
    not PYSPH_OK, reason=f"PySPH unavailable: {PYSPH_DETAIL}")


def _valley(ny=8, nx=8, cell=10.0, slope=1.5, walls=0.4):
    """A small V-shaped valley falling toward +y — the test terrain."""
    j = np.arange(ny)[:, None]
    i = np.arange(nx)[None, :]
    return 300.0 - j * slope + walls * (i - (nx - 1) / 2.0) ** 2


def _small_run(bed=None, reservoir_depth_m=6.0, **kw):
    """One deliberately tiny near-field run, sized to stay test-fast."""
    if bed is None:
        bed = _valley()
    params = dict(
        bed_elevation=bed, cell_size_m=10.0,
        reservoir_depth_m=reservoir_depth_m,
        breach_width_m=20.0, q_peak_m3_s=800.0,
        duration_s=0.8, dam_name="TestDam", target_particles=400,
    )
    params.update(kw)
    return run_near_field_sph(**params)


@pytest.fixture(scope="module")
def baseline_run():
    if not PYSPH_OK:
        pytest.skip(f"PySPH unavailable: {PYSPH_DETAIL}")
    return _small_run()


# ─── TestNearFieldDomain ──────────────────────────────────────────────────────

class TestNearFieldDomain:
    """Particle seeding (jalraksha/sph/domain.py) — unchanged by the PySPH work."""

    def test_domain_particle_generation(self):
        domain = NearFieldDomain(
            center_x=500000.0, center_y=3350000.0, domain_size_m=100.0,
            particle_spacing_m=10.0, water_depth_m=20.0, bed_elevation_m=100.0,
        )
        res = domain.generate()

        assert res["num_fluid"] > 0
        assert res["num_boundary"] > 0
        assert len(domain.x) == res["num_fluid"] + res["num_boundary"]
        assert np.all(domain.rho == 1000.0)

    def test_factory_function(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0,
            particle_spacing_m=10.0)
        assert domain.num_fluid > 0
        assert domain.num_boundary > 0


# ─── TestSWESPHCoupling ───────────────────────────────────────────────────────

class TestSWESPHCoupling:
    """One-way SWE -> SPH handoff and free-surface extraction."""

    def test_handoff_swe_to_sph(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0,
            particle_spacing_m=10.0)
        domain = handoff_swe_to_sph(
            q_breach_m3_s=500.0, h_breach_m=5.0, near_field_domain=domain,
            breach_width_m=50.0)

        # u = Q / (h * w) = 500 / (5 * 50) = 2.0 m/s
        fluid_mask = domain.pid == 0
        assert np.max(domain.u[fluid_mask]) >= 2.0

    def test_extract_sph_free_surface(self):
        domain = generate_near_field_particles(
            center_x=1000.0, center_y=2000.0, domain_size_m=50.0,
            particle_spacing_m=10.0)
        xs, ys, depth_2d = extract_sph_free_surface(domain, grid_res_m=10.0)

        assert len(xs) > 0 and len(ys) > 0
        assert depth_2d.shape == (len(ys), len(xs))
        assert np.max(depth_2d) > 0.0


# ─── TestDownhillOrientation ──────────────────────────────────────────────────

class TestDownhillOrientation:
    """
    +y must point downstream before any near-field geometry is built along it.

    A DEM window arrives in compass order (row 0 = south), which says nothing
    about which way the river runs. Releasing a reservoir uphill produces a
    stalled surge and numbers that still look plausible.
    """

    @pytest.mark.parametrize("rot_in", [0, 1, 2, 3])
    def test_any_input_orientation_ends_up_downhill(self, rot_in):
        bed = np.rot90(_valley(ny=12, nx=12, walls=0.0), rot_in)
        oriented, _ = orient_downhill(bed)
        drop = oriented[0, :].mean() - oriented[-1, :].mean()
        assert drop > 0, "bed must fall toward +y after orientation"

    def test_orientation_preserves_elevations(self):
        bed = _valley(ny=10, nx=10)
        oriented, _ = orient_downhill(bed)
        # A rotation, not a resample: the multiset of elevations is unchanged.
        assert np.allclose(np.sort(bed.ravel()), np.sort(oriented.ravel()))


# ─── TestHydrostaticDensity ───────────────────────────────────────────────────

class TestHydrostaticDensity:
    """Initial density must already carry the hydrostatic pressure."""

    def test_surface_is_reference_density(self):
        z = np.array([10.0])
        assert hydrostatic_density(z, np.array([10.0]), c0=100.0)[0] == pytest.approx(1000.0)

    def test_density_increases_with_depth(self):
        z = np.array([10.0, 5.0, 0.0])
        rho = hydrostatic_density(z, np.full(3, 10.0), c0=100.0)
        assert rho[0] < rho[1] < rho[2]

    def test_inverts_the_tait_equation(self):
        # Round-trip: rho -> p via Tait must recover rho*g*(surface - z).
        c0, gamma = 100.0, 7.0
        z = np.array([0.0, 2.0, 4.0])
        surface = np.full(3, 8.0)
        rho = hydrostatic_density(z, surface, c0=c0)
        B = 1000.0 * c0 ** 2 / gamma
        p = B * ((rho / 1000.0) ** gamma - 1.0)
        assert np.allclose(p, 1000.0 * 9.81 * (surface - z), rtol=1e-6)


# ─── TestPySPHNearField ───────────────────────────────────────────────────────

@requires_pysph
class TestPySPHNearField:
    """Physical gates on the real near-field run."""

    def test_produces_particles_and_provenance(self, baseline_run):
        assert baseline_run["n_fluid"] > 0
        assert baseline_run["engine"] == "PySPH_WCSPH"
        assert "PySPH" in baseline_run["engine_label"]
        assert baseline_run["particle_volume_m3"] > 0

    def test_all_positions_finite(self, baseline_run):
        for axis in ("x", "y", "z", "u", "v", "w"):
            assert np.all(np.isfinite(baseline_run[axis])), f"{axis} has non-finite values"

    def test_respects_the_energy_bound(self, baseline_run):
        """
        No particle may exceed sqrt(2*g*H) for the head available to it.

        This is the gate that caught two real defects: an unwalled reservoir
        whose water ran off the upstream edge and free-fell, and statistics
        computed over particles that had left the terrain entirely through the
        open downstream boundary. Both reported speeds well above this bound.
        """
        assert baseline_run["max_speed_m_s"] <= baseline_run["energy_bound_m_s"], (
            f"max speed {baseline_run['max_speed_m_s']:.1f} m/s exceeds the "
            f"available-head bound {baseline_run['energy_bound_m_s']:.1f} m/s"
        )

    def test_most_particles_stay_over_the_terrain(self, baseline_run):
        escaped_fraction = baseline_run["n_escaped"] / baseline_run["n_fluid"]
        assert escaped_fraction < 0.25, (
            f"{escaped_fraction:.0%} of particles left the domain; the "
            f"near-field window is too small or the run too long"
        )

    def test_surge_front_advances_downstream(self, baseline_run):
        front = baseline_run["front_position_m"]
        assert len(front) > 1
        assert front[-1] >= front[0], "the surge front must not retreat upstream"

    def test_reports_no_gauge_arrivals(self, baseline_run):
        """
        A near-field domain cannot reach a gauge 13 km away, so it must not
        claim to. The fabricated result this replaced reported arrivals at all
        four Tehri gauges.
        """
        assert baseline_run["reaches_downstream_gauges"] is False
        assert "gauge_arrivals" not in baseline_run

    def test_states_one_way_coupling(self, baseline_run):
        assert "one-way" in baseline_run["coupling"].lower()

    def test_is_deterministic(self):
        """
        Same inputs, same particles. The np.random stand-in this replaced
        produced a different field on every call, which is the single clearest
        sign a "result" is not a simulation.
        """
        a = _small_run()
        b = _small_run()
        assert np.array_equal(a["x"], b["x"])
        assert np.array_equal(a["y"], b["y"])
        assert np.array_equal(a["z"], b["z"])

    def test_responds_to_terrain(self, baseline_run):
        """A different valley must give a different flood."""
        steeper = _small_run(bed=_valley(slope=6.0))
        assert steeper["n_fluid"] > 0
        assert not np.array_equal(steeper["z"], baseline_run["z"]), (
            "changing the terrain did not change the particle field"
        )

    def test_responds_to_reservoir_depth(self, baseline_run):
        """A different dam must give a different flood."""
        deeper = _small_run(reservoir_depth_m=12.0)
        assert deeper["available_head_m"] > baseline_run["available_head_m"]
        assert deeper["n_fluid"] != baseline_run["n_fluid"] or not np.array_equal(
            deeper["z"], baseline_run["z"])


# ─── TestSPHUnavailable ───────────────────────────────────────────────────────

class TestSPHUnavailable:
    """With no PySPH there must be no result — not a substitute for one."""

    def test_raises_rather_than_fabricating(self, monkeypatch):
        import jalraksha.sph.pysph_runner as runner

        monkeypatch.setattr(runner, "is_pysph_available",
                            lambda: (False, "ImportError: no module named pysph"))
        with pytest.raises(SPHUnavailableError) as excinfo:
            _small_run()
        assert "pysph" in str(excinfo.value).lower()


# ─── TestStillWaterGate ───────────────────────────────────────────────────────

@requires_pysph
@pytest.mark.slow
class TestStillWaterGate:
    """
    Hydrostatic gate — the SPH counterpart of the SWE lake-at-rest test.

    Still water in a closed tank is an equilibrium. A scheme with a broken
    pressure gradient, or boundary particles that do not support the column,
    fails immediately. Run small here so it stays inside the default suite; the
    pressure-gradient half of the check needs more resolution than that allows
    and reports "not measured" rather than a meaningless number, so it is
    asserted only when it was actually measurable.
    """

    def test_water_at_rest_stays_at_rest(self):
        result = run_still_water_validation(
            depth_m=3.0, spacing_m=0.5, duration_s=0.6, tank_cells=8)

        assert result["all_finite"], "still water produced non-finite values"
        # Residual motion is the WCSPH startup transient, not flow. The bar is
        # that it stays small compared with the speed a collapse would produce:
        # sqrt(2*g*3) = 7.7 m/s.
        assert result["max_speed_m_s"] < 1.0, (
            f"still water is moving at {result['max_speed_m_s']:.2f} m/s")
        assert result["density_error_pct"] < 2.0, (
            f"density drifted {result['density_error_pct']:.2f}% from rho0")
        assert abs(result["surface_drop_m"]) < 0.5, "the free surface collapsed"

    def test_pressure_is_hydrostatic_when_measurable(self):
        result = run_still_water_validation(
            depth_m=3.0, spacing_m=0.5, duration_s=0.6, tank_cells=8)

        if result["slope_error_pct"] is None:
            pytest.skip(f"pressure gradient not measurable here: {result['slope_note']}")
        # Standard WCSPH carries well-known pressure noise without a density
        # filter (delta-SPH), so this is a loose bound on dp/d(depth) against
        # rho*g rather than a tight one. At production resolution (0.4 m over a
        # 6 m column, 4 s) the measured error is about 3%.
        assert result["slope_error_pct"] < 40.0, (
            f"dp/d(depth) is {result['slope_error_pct']:.1f}% from rho*g "
            f"({result['slope_note']})")
