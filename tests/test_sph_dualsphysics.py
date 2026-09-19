"""
DualSPHysics near-field engine (jalraksha/sph/dualsphysics_runner.py) and the
engine dispatcher (jalraksha/sph/engine.py).

The pure parts — install discovery, the .bi4 writer/reader round trip, backend
and engine selection — run everywhere. Everything that starts DualSPHysics is
skipped when no install is found, which is the normal state on CI's Linux job:
the release is ~1 GB, LGPL, and deliberately never committed.

As in test_sph.py, the backend is PINNED in every run so these gates cannot
silently follow whatever hardware the machine has, and the GPU and CPU builds
are each held to their own physics, never bit-compared: DualSPHysics's GPU path
integrates "Pos-Cell" and its CPU path "Pos-Double".
"""

import numpy as np
import pytest

from jalraksha.sph import dualsphysics_runner as dsph
from jalraksha.sph import engine
from jalraksha.sph.geometry import SPHUnavailableError

INSTALLED, INSTALL_DETAIL = dsph.is_dualsphysics_available()
requires_dualsphysics = pytest.mark.skipif(not INSTALLED, reason=INSTALL_DETAIL)


def _gpu_ok():
    if not INSTALLED:
        return False, INSTALL_DETAIL
    ok, reason, _ = dsph.probe_dualsphysics_gpu()
    return ok, reason


def _valley(ny=30, nx=30, cell=10.0, slope=1.5, walls=0.04):
    j = np.arange(ny)[:, None]
    i = np.arange(nx)[None, :]
    return 300.0 - j * slope + walls * (i - (nx - 1) / 2.0) ** 2


# ─── install discovery ────────────────────────────────────────────────────────


class TestInstallDiscovery:
    def test_a_wrong_configured_directory_is_reported_not_searched_around(self, monkeypatch, tmp_path):
        monkeypatch.setenv(dsph.DUALSPHYSICS_DIR_ENV, str(tmp_path / "nope"))
        paths, detail = dsph.resolve_dualsphysics()
        assert paths is None
        assert "nope" in detail and "configured" in detail

    def test_an_incomplete_install_names_what_is_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv(dsph.DUALSPHYSICS_DIR_ENV, str(tmp_path))
        paths, detail = dsph.resolve_dualsphysics()
        assert paths is None
        assert "incomplete" in detail

    def test_resolve_backend_raises_without_an_install(self, monkeypatch, tmp_path):
        monkeypatch.setenv(dsph.DUALSPHYSICS_DIR_ENV, str(tmp_path / "nope"))
        with pytest.raises(SPHUnavailableError):
            dsph.resolve_dsph_backend("auto")


# ─── .bi4 format ──────────────────────────────────────────────────────────────


class TestCaseFiles:
    def test_written_initial_state_reads_back_exactly(self, tmp_path):
        """
        The writer must produce what DualSPHysics reads, and the reader must read
        what DualSPHysics writes; both use one format, so a round trip checks the
        shared encoding (types, lengths, array layout) without the program.
        """
        bound = np.array([[0.0, 0.0, -0.5], [1.0, 0.0, -0.5]])
        fluid = np.array([[0.25, 0.5, 0.5], [0.75, 0.5, 0.5], [0.5, 0.25, 1.0]])
        vel = np.array([[0.0, 1.5, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        rho = np.array([1001.0, 1001.0, 1000.5])
        dsph.write_case(tmp_path, [("bed", bound)], fluid, vel, rho, 0.5, 50.0, 1.0, 0.1)
        part = dsph.read_part_file(tmp_path / "Case.bi4", ("Idp", "Posd", "Vel", "Rhop"))
        arrays = part["arrays"]
        assert list(arrays["Idp"]) == [0, 1, 2, 3, 4]
        np.testing.assert_array_equal(arrays["Pos"], np.vstack([bound, fluid]))
        np.testing.assert_allclose(arrays["Vel"][2:], vel)
        np.testing.assert_allclose(arrays["Rhop"], [1000.0, 1000.0, *rho])
        assert part["values"]["Npok"] == 5

    def test_case_xml_declares_the_blocks_and_the_scheme(self, tmp_path):
        bound = np.zeros((4, 3))
        walls = np.ones((2, 3))
        fluid = np.full((3, 3), 2.0)
        dsph.write_case(tmp_path, [("bed", bound), ("walls", walls)], fluid, np.zeros_like(fluid),
                        np.full(3, 1000.0), 1.0, 40.0, 15.0, 0.375)
        xml = (tmp_path / "Case.xml").read_text(encoding="utf-8")
        assert '<particles np="9" nb="6"' in xml
        assert '<fixed mkbound="0" mk="10" begin="0" count="4" />' in xml
        assert '<fixed mkbound="1" mk="11" begin="4" count="2" />' in xml
        assert '<fluid mkfluid="0" mk="1" begin="6" count="3" />' in xml
        assert '"TimeMax" value="15.0"' in xml
        # B is written from the SAME c0 the hydrostatic densities used.
        assert f'<b value="{40.0 ** 2 * 1000.0 / 7.0!r}"' in xml

    def test_bed_boundary_closes_terrain_steps(self):
        """A column next to a 10-spacing drop must reach below its neighbour."""
        bed = np.zeros((3, 3))
        bed[1, 1] = 10.0
        points = dsph._bed_boundary(bed, 1.0)
        under_peak = points[(points[:, 0] == 1.0) & (points[:, 1] == 1.0)]
        assert under_peak[:, 2].min() < 0.0
        assert under_peak.shape[0] == 11

    def test_reservoir_has_a_level_surface_and_stays_upstream(self):
        bed = _valley(ny=20, nx=10)
        fluid, surface = dsph._reservoir(bed, 2.0, dam_row=5, reservoir_depth_m=8.0)
        assert fluid[:, 1].max() <= 4 * 2.0
        assert fluid[:, 2].max() <= surface


# ─── backend and engine selection ────────────────────────────────────────────


class TestSelection:
    def _installed(self, monkeypatch, gpu_ok):
        monkeypatch.delenv(dsph.SPH_BACKEND_ENV, raising=False)
        monkeypatch.setattr(dsph, "resolve_dualsphysics",
                            lambda custom_dir=None: ({"dir": "d", "gpu_exe": "g.exe", "cpu_exe": "c.exe"}, "fake"))
        monkeypatch.setattr(dsph, "probe_dualsphysics_gpu",
                            lambda custom_dir=None: (gpu_ok, "probe says so", "Fake GPU" if gpu_ok else None))

    def test_auto_takes_the_gpu_and_names_the_device(self, monkeypatch):
        self._installed(monkeypatch, True)
        choice = dsph.resolve_dsph_backend("auto")
        assert choice["sph_backend"] == "gpu" and choice["use_gpu"]
        assert choice["exe"] == "g.exe" and "Fake GPU" in choice["label"]

    def test_prefer_gpu_degrades_to_the_cpu_build_with_the_reason(self, monkeypatch):
        self._installed(monkeypatch, False)
        choice = dsph.resolve_dsph_backend("prefer_gpu")
        assert choice["sph_backend"] == "cpu" and not choice["use_gpu"]
        assert choice["exe"] == "c.exe" and "probe says so" in choice["reason"]

    def test_strictness_is_decided_by_the_final_request(self, monkeypatch):
        """
        JALRAKSHA_SPH_BACKEND=gpu must be as strict as backend="gpu". It was not:
        the call sites treated any set variable as non-strict.
        """
        self._installed(monkeypatch, True)
        assert dsph.resolve_dsph_backend("gpu")["strict"] is True
        assert dsph.resolve_dsph_backend("auto")["strict"] is False
        monkeypatch.setenv(dsph.SPH_BACKEND_ENV, "gpu")
        assert dsph.resolve_dsph_backend("auto")["strict"] is True

    def test_a_strict_gpu_request_raises(self, monkeypatch):
        self._installed(monkeypatch, False)
        with pytest.raises(SPHUnavailableError, match="probe says so"):
            dsph.resolve_dsph_backend("gpu")

    def test_environment_override_beats_a_dashboard_preference(self, monkeypatch):
        self._installed(monkeypatch, True)
        monkeypatch.setenv(dsph.SPH_BACKEND_ENV, "cpu")
        assert dsph.resolve_dsph_backend("prefer_gpu")["sph_backend"] == "cpu"

    def test_unknown_backend_is_rejected(self, monkeypatch):
        self._installed(monkeypatch, True)
        with pytest.raises(ValueError):
            dsph.resolve_dsph_backend("tpu")

    def test_engine_auto_prefers_dualsphysics(self, monkeypatch):
        monkeypatch.delenv(engine.SPH_ENGINE_ENV, raising=False)
        monkeypatch.setattr(dsph, "is_dualsphysics_available", lambda custom_dir=None: (True, "fake dsph"))
        assert engine.resolve_sph_engine()["engine"] == "dualsphysics"

    def test_engine_auto_falls_back_to_pysph_and_says_why(self, monkeypatch):
        from jalraksha.sph import pysph_runner

        monkeypatch.delenv(engine.SPH_ENGINE_ENV, raising=False)
        monkeypatch.setattr(dsph, "is_dualsphysics_available", lambda custom_dir=None: (False, "not installed"))
        monkeypatch.setattr(pysph_runner, "is_pysph_available", lambda: (True, "PySPH fake"))
        chosen = engine.resolve_sph_engine()
        assert chosen["engine"] == "pysph" and "not installed" in chosen["reason"]

    def test_an_explicit_engine_that_cannot_run_raises(self, monkeypatch):
        monkeypatch.setenv(engine.SPH_ENGINE_ENV, "dualsphysics")
        monkeypatch.setattr(dsph, "is_dualsphysics_available", lambda custom_dir=None: (False, "not installed"))
        with pytest.raises(SPHUnavailableError, match="not installed"):
            engine.resolve_sph_engine()

    def test_unknown_engine_is_rejected(self, monkeypatch):
        monkeypatch.setenv(engine.SPH_ENGINE_ENV, "sphinx")
        with pytest.raises(ValueError):
            engine.resolve_sph_engine()

    def test_run_backend_maps_to_one_sph_control(self):
        # cuda is STRICT for SPH, as it is for the SWE ensemble.
        assert engine.sph_backend_for_solver("cuda") == "gpu"
        assert engine.sph_backend_for_solver("cpu") == "cpu"
        assert engine.sph_backend_for_solver(None) == "auto"
        assert engine.sph_backend_for_solver("tpu") == "auto"

    def test_gpu_spellings_reach_pysph_as_opencl(self):
        assert engine._backend_for_engine("pysph", "prefer_gpu") == "prefer_opencl"
        assert engine._backend_for_engine("pysph", "gpu") == "opencl"
        assert engine._backend_for_engine("dualsphysics", "prefer_gpu") == "prefer_gpu"


# ─── running DualSPHysics ─────────────────────────────────────────────────────


@requires_dualsphysics
class TestStillWater:
    @pytest.mark.parametrize("backend", ["gpu", "cpu"])
    def test_water_at_rest_stays_at_rest(self, backend):
        if backend == "gpu":
            ok, reason = _gpu_ok()
            if not ok:
                pytest.skip(reason)
        result = dsph.run_still_water_validation(
            depth_m=1.2, spacing_m=0.1, duration_s=0.3, tank_cells=10, backend=backend)
        assert result["sph_backend"] == backend
        assert result["all_finite"]
        assert result["n_excluded"] == 0
        # The thresholds of test_sph.py's GPU still-water gate.
        assert result["max_speed_m_s"] < 1.0
        assert result["density_error_pct"] < 2.0
        assert abs(result["surface_drop_m"]) < 0.5
        mode = result["solver_run_mode"]
        assert ("GPU" in mode) if backend == "gpu" else ("OpenMP" in mode)


@pytest.fixture(scope="module")
def gpu_near_field():
    ok, reason = _gpu_ok()
    if not ok:
        pytest.skip(reason)
    return dsph.run_near_field_sph(
        _valley(), 10.0, reservoir_depth_m=12.0, breach_width_m=60.0, q_peak_m3_s=3000.0,
        duration_s=3.0, dam_name="TestDsph", target_particles=15_000, backend="gpu")


class TestNearField:
    def test_it_ran_on_the_gpu_and_says_so(self, gpu_near_field):
        r = gpu_near_field
        assert r["engine"] == "DualSPHysics"
        assert r["sph_backend"] == "gpu"
        assert "GPU" in r["solver_run_mode"]
        assert "CUDA" in r["engine_label"]

    def test_energy_bound_holds(self, gpu_near_field):
        r = gpu_near_field
        assert 0.0 < r["max_speed_m_s"] <= r["energy_bound_m_s"]

    def test_front_advances_downstream(self, gpu_near_field):
        front = gpu_near_field["front_position_m"]
        assert len(front) >= 10
        assert front[-1] > front[0]

    def test_the_result_contract_matches_pysph(self, gpu_near_field):
        """Every key the service layer and the comparison read must be present."""
        required = {
            "x", "y", "z", "u", "v", "w", "particle_spacing_m", "particle_volume_m3",
            "particle_mass_kg", "n_fluid", "n_boundary", "front_time_s", "front_position_m",
            "front_speed_m_s", "max_depth_m", "max_speed_m_s", "n_escaped", "n_in_domain",
            "available_head_m", "energy_bound_m_s", "front_exited_domain", "domain_length_m",
            "domain_width_m", "duration_s", "reservoir_depth_m", "u_inflow_m_s", "wall_clock_s",
            "dam_name", "bed_drop_m", "orientation_rot90", "engine", "engine_label",
            "sph_backend", "sph_backend_label", "sph_backend_reason",
            "reaches_downstream_gauges", "coupling",
        }
        assert required <= set(gpu_near_field)
        assert gpu_near_field["reaches_downstream_gauges"] is False
        assert gpu_near_field["x"].size == gpu_near_field["n_fluid"] - gpu_near_field["n_excluded"]

    def test_particle_snapshots_are_not_left_behind(self, gpu_near_field):
        from pathlib import Path

        data = Path(gpu_near_field["output_dir"]) / "data"
        assert not list(data.glob("Part_*.bi4"))
        assert (Path(gpu_near_field["output_dir"]) / "Run.out").is_file()


@requires_dualsphysics
def test_a_gpu_side_failure_reruns_on_the_cpu_build(monkeypatch, tmp_path):
    """
    A GPU run that fails for a GPU reason must still produce the near-field
    result — on the CPU build, with the reason — unless the GPU was demanded.
    """
    calls = []
    real_execute = dsph._execute

    def fake_execute(exe, case_dir, out_dir, use_gpu, timeout_s):
        calls.append(use_gpu)
        if use_gpu:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "Run.out").write_text("*** Exception: There are no available CUDA devices.\n")
            return 1, ""
        return real_execute(exe, case_dir, out_dir, use_gpu, timeout_s)

    paths, _ = dsph.resolve_dualsphysics()
    monkeypatch.setattr(dsph, "_execute", fake_execute)
    monkeypatch.setattr(dsph, "resolve_dsph_backend", lambda requested=None, custom_dir=None: {
        "sph_backend": "gpu", "exe": paths["gpu_exe"], "use_gpu": True,
        "label": "GPU (CUDA, fake)", "reason": "fake", "strict": False})
    result = dsph.run_still_water_validation(
        depth_m=0.6, spacing_m=0.1, duration_s=0.05, tank_cells=6, backend="prefer_gpu")
    assert calls == [True, False]
    assert result["sph_backend"] == "cpu"
    assert "no available CUDA devices" in result["sph_backend_reason"]


@requires_dualsphysics
@pytest.mark.parametrize("how", ["argument", "environment"])
def test_a_strict_gpu_run_that_fails_is_never_rerun_on_the_cpu(monkeypatch, how):
    """A GPU-only run that fails partway is an error, however the GPU was demanded."""
    calls = []

    def failing_gpu(exe, case_dir, out_dir, use_gpu, timeout_s):
        calls.append(use_gpu)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "Run.out").write_text("*** Exception: CUDA error: out of memory\n")
        return 1, ""

    monkeypatch.setattr(dsph, "_execute", failing_gpu)
    monkeypatch.setattr(dsph, "probe_dualsphysics_gpu",
                        lambda custom_dir=None: (True, "fake probe", "Fake GPU"))
    if how == "environment":
        monkeypatch.setenv(dsph.SPH_BACKEND_ENV, "gpu")
        backend = "auto"
    else:
        monkeypatch.delenv(dsph.SPH_BACKEND_ENV, raising=False)
        backend = "gpu"
    with pytest.raises(SPHUnavailableError, match="not rerun on the CPU"):
        dsph.run_still_water_validation(
            depth_m=0.6, spacing_m=0.1, duration_s=0.05, tank_cells=6, backend=backend)
    assert calls == [True]
