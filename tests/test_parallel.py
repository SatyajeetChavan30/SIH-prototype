"""
Phase 12 Parallel Execution Test Suite.

Tests:
  - run_ensemble_member: one member integrates and reports success
  - run_ensemble: sequential and pooled dispatch
  - the property that matters most — parallel results are IDENTICAL to
    sequential ones. An earlier version of solver/parallel.py reimplemented the
    time-stepping loop with its own simplified breach injection, so the two
    paths silently computed different physics; both now call the same worker.
"""

import numpy as np
import pytest

from jalraksha.run import hydrograph_discharge
from jalraksha.solver.backend import cuda_probe
from jalraksha.solver.parallel import INJECTION_CFL_RTOL, run_ensemble, run_ensemble_member
from jalraksha.solver.types import Grid, create_state


def _domain(n=12, dx=100.0):
    """Small sloping domain so injected water has somewhere to run."""
    grid = Grid(nx=n, ny=n, dx=dx, dy=dx, x0=500000.0, y0=3350000.0, crs="EPSG:32644")
    # Bed falls toward -y so the flood propagates away from the breach cell.
    bed = np.tile(np.linspace(100.0, 0.0, n)[:, None], (1, n))
    state = create_state(
        grid, h_init=np.zeros((n, n), dtype=np.float64), b_init=bed
    )
    manning = np.full((n, n), 0.03, dtype=np.float64)
    return grid, state, manning


def _hydrographs(count=3):
    return [
        {
            "t_array": np.linspace(0, 3600, 10),
            "Q_t": np.full(10, 500.0),
            "metadata": {"q_peak_m3_s": 500.0 + i, "failure_time_s": 1800.0},
        }
        for i in range(count)
    ]


class TestParallelExecution:
    """Test ensemble solver execution, sequential and pooled."""

    def test_single_member_runs(self):
        grid, state, manning = _domain()
        res = run_ensemble_member(
            0, _hydrographs(1)[0], grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=60.0,
        )
        assert res["success"] is True, res.get("error")
        assert res["sample_id"] == 0
        assert res["h_max"].shape == (grid.ny, grid.nx)
        assert res["t_arrival"].shape == (grid.ny, grid.nx)

    def test_injected_water_is_conserved_into_the_domain(self):
        """A mass source must actually add water — it previously set only velocity."""
        grid, state, manning = _domain()
        res = run_ensemble_member(
            0, _hydrographs(1)[0], grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=120.0,
        )
        assert res["h_max"].max() > 0.0, "no water entered the domain"

    def test_run_ensemble_sequential(self):
        grid, state, manning = _domain()
        results = run_ensemble(
            _hydrographs(3), grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=60.0, n_workers=1,
        )
        assert len(results) == 3
        assert [r["sample_id"] for r in results] == [0, 1, 2]
        assert all(r["success"] for r in results)

    def test_failures_are_reported_not_dropped(self):
        """A failed member must still appear in the results, flagged."""
        grid, state, manning = _domain()
        bad = {"t_array": np.linspace(0, 10, 3), "metadata": {}}  # missing "Q_t"
        results = run_ensemble(
            [bad], grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=10.0, n_workers=1,
        )
        assert len(results) == 1
        assert results[0]["success"] is False
        assert "error" in results[0]

    def test_snapshots_only_for_the_selected_member(self):
        grid, state, manning = _domain()
        results = run_ensemble(
            _hydrographs(3), grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=60.0,
            snapshot_sample_id=1, snapshot_times=np.linspace(0, 60, 4),
            n_workers=1,
        )
        assert not results[0]["depth_series"]
        assert len(results[1]["depth_series"]) >= 1
        assert not results[2]["depth_series"]
        # Snapshots are float32: they only feed keyframe PNGs, and float64
        # arrays are twice the payload across a process boundary.
        assert results[1]["depth_series"][0]["depth"].dtype == np.float32

    @pytest.mark.slow
    def test_parallel_matches_sequential(self):
        """The blocking property: pooled dispatch must not change the answer."""
        grid, state, manning = _domain()
        hydrographs = _hydrographs(2)
        # CPU on both sides: this pins the process pool against the in-process
        # loop. The GPU path has its own comparison in TestGpuEnsemble.
        kwargs = dict(
            i_breach=6, j_breach=6, solver_duration_s=60.0, backend="cpu",
        )
        seq = run_ensemble(hydrographs, grid, state, manning, n_workers=1, **kwargs)
        par = run_ensemble(hydrographs, grid, state, manning, n_workers=2, **kwargs)

        assert len(seq) == len(par)
        for a, b in zip(seq, par):
            assert a["success"] and b["success"]
            np.testing.assert_array_equal(a["h_max"], b["h_max"])
            np.testing.assert_array_equal(a["t_arrival"], b["t_arrival"])

    def test_snapshot_times_are_strictly_increasing(self):
        """
        One solver step can span several requested snapshot times. It must then
        record ONE frame, not one per time crossed — the latter stamps every
        frame with the same t_sim, and jalraksha.export.xdmf_export rejects a
        series whose times are not strictly increasing.

        Requesting many closely-spaced snapshots over a short run forces the
        overlap this guards.
        """
        grid, state, manning = _domain()
        results = run_ensemble(
            _hydrographs(1), grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=60.0,
            snapshot_sample_id=0, snapshot_times=np.linspace(0, 60, 40),
            n_workers=1,
        )
        times = [snap["time_s"] for snap in results[0]["depth_series"]]
        assert times, "no snapshots recorded"
        assert all(b > a for a, b in zip(times, times[1:])), (
            f"snapshot times not strictly increasing: {times}"
        )


def _valley(ny=60, nx=48, dx=100.0, members=3):
    """A sloping valley with a rough, varying bed, big enough for real fronts."""
    grid = Grid(nx=nx, ny=ny, dx=dx, dy=dx, x0=500000.0, y0=3350000.0, crs="EPSG:32644")
    yy, xx = np.mgrid[0:ny, 0:nx]
    bed = 200.0 - 0.005 * yy * dx + 0.05 * np.abs(xx - nx / 2) * dx
    state = create_state(grid, h_init=np.zeros((ny, nx)), b_init=bed)
    manning = np.random.default_rng(1).uniform(0.03, 0.06, (ny, nx))
    hydrographs = []
    for i in range(members):
        q_peak = 1000.0 + 1000.0 * i
        hydrographs.append({
            "t_array": np.array([0.0, 120.0, 400.0, 900.0]),
            "Q_t": np.array([0.0, q_peak, 0.3 * q_peak, 0.0]),
            "metadata": {"q_peak_m3_s": q_peak, "failure_time_s": 120.0},
        })
    return grid, state, manning, hydrographs


@pytest.mark.skipif(not cuda_probe()[0], reason="CUDA backend unavailable")
class TestGpuEnsemble:
    """
    The GPU batched ensemble is a second implementation of the member loop, so
    this is the blocking property that binds it to the first: same inputs, same
    answers. Not bit-identical (FMA contraction, libdevice pow; see
    solver/flux_cuda.py), so the tolerances sit about six orders of magnitude
    above the measured round-off difference and far below any physical one.
    """

    def _compare(self, grid, state, manning, hydrographs, **kwargs):
        cpu = run_ensemble(hydrographs, grid, state, manning, n_workers=1, backend="cpu", **kwargs)
        gpu = run_ensemble(hydrographs, grid, state, manning, backend="cuda", **kwargs)
        assert len(cpu) == len(gpu)
        for a, b in zip(cpu, gpu, strict=True):
            assert a["success"] and b["success"], (a.get("error"), b.get("error"))
            assert a["sample_id"] == b["sample_id"]
            assert a["n_steps"] == b["n_steps"]
            # One clock, and the same injection-step decisions, on both backends.
            assert b["t_end_s"] == pytest.approx(a["t_end_s"], rel=1e-9)
            assert a["injection_step_retries"] == b["injection_step_retries"]
            assert a["injection_step_overruns"] == b["injection_step_overruns"] == 0
            np.testing.assert_allclose(b["h_max"], a["h_max"], rtol=1e-9, atol=1e-12)
            np.testing.assert_allclose(b["v_max"], a["v_max"], rtol=1e-9, atol=1e-10)
            # The same cells wet, at the same times to round-off. Not bit-equal:
            # t_sim is a running sum of timesteps that differ by an ulp between
            # backends.
            assert np.array_equal(np.isfinite(a["t_arrival"]), np.isfinite(b["t_arrival"]))
            wet = np.isfinite(a["t_arrival"])
            if wet.any():
                assert np.max(np.abs(a["t_arrival"][wet] - b["t_arrival"][wet])) < 1e-6
            for key in ("volume_released_m3", "volume_exited_m3", "volume_retained_m3"):
                assert b[key] == pytest.approx(a[key], rel=1e-9, abs=1e-6), key
            assert a["solver_backend"] == "cpu" and b["solver_backend"] == "cuda"
        return cpu, gpu

    def test_matches_cpu_on_the_small_domain(self):
        grid, state, manning = _domain()
        self._compare(
            grid, state, manning, _hydrographs(3),
            i_breach=6, j_breach=6, solver_duration_s=120.0,
        )

    def test_matches_cpu_on_a_valley_with_fronts(self):
        grid, state, manning, hydrographs = _valley()
        self._compare(
            grid, state, manning, hydrographs,
            i_breach=grid.nx // 2, j_breach=3, solver_duration_s=600.0,
        )

    def test_snapshots_match_cpu(self):
        grid, state, manning = _domain()
        cpu, gpu = self._compare(
            grid, state, manning, _hydrographs(3),
            i_breach=6, j_breach=6, solver_duration_s=60.0,
            snapshot_sample_id=1, snapshot_times=np.linspace(0, 60, 40),
        )
        frames_cpu, frames_gpu = cpu[1]["depth_series"], gpu[1]["depth_series"]
        assert [f["time_s"] for f in frames_gpu] == pytest.approx([f["time_s"] for f in frames_cpu])
        for a, b in zip(frames_cpu, frames_gpu, strict=True):
            assert b["depth"].dtype == np.float32
            np.testing.assert_allclose(b["depth"], a["depth"], atol=1e-6)
        assert not gpu[0]["depth_series"] and not gpu[2]["depth_series"]

    def test_malformed_hydrograph_fails_the_same_way(self):
        grid, state, manning = _domain()
        bad = {"t_array": np.linspace(0, 10, 3), "metadata": {}}  # missing "Q_t"
        results = run_ensemble(
            [bad] + _hydrographs(1), grid, state, manning,
            i_breach=6, j_breach=6, solver_duration_s=10.0, backend="cuda",
        )
        assert results[0]["success"] is False and "Q_t" in results[0]["error"]
        assert results[1]["success"] is True


class TestBackendFallback:
    """A GPU failure must fall back to the CPU, loudly, and say so in every result."""

    def _force_gpu_failure(self, monkeypatch):
        import sys
        import types

        from jalraksha.solver import backend as backend_module

        monkeypatch.setattr(backend_module, "cuda_probe", lambda: (True, "forced", "Fake GPU"))
        broken = types.ModuleType("jalraksha.solver.ensemble_cuda")

        def run_ensemble_gpu(*args, **kwargs):
            raise RuntimeError("simulated CUDA out-of-memory")

        broken.run_ensemble_gpu = run_ensemble_gpu
        monkeypatch.setitem(sys.modules, "jalraksha.solver.ensemble_cuda", broken)
        monkeypatch.delenv(backend_module.ENV_VAR, raising=False)

    def test_auto_falls_back_to_cpu_with_the_reason(self, monkeypatch):
        self._force_gpu_failure(monkeypatch)
        grid, state, manning = _domain()
        with pytest.warns(UserWarning, match="GPU ensemble failed"):
            results = run_ensemble(
                _hydrographs(2), grid, state, manning,
                i_breach=6, j_breach=6, solver_duration_s=30.0, n_workers=1,
            )
        assert all(r["success"] for r in results)
        assert all(r["solver_backend"] == "cpu" for r in results)
        assert all("simulated CUDA out-of-memory" in r["solver_backend_reason"] for r in results)

    def test_explicit_cuda_request_raises_instead(self, monkeypatch):
        self._force_gpu_failure(monkeypatch)
        grid, state, manning = _domain()
        with pytest.raises(RuntimeError, match="simulated CUDA out-of-memory"):
            run_ensemble(
                _hydrographs(1), grid, state, manning,
                i_breach=6, j_breach=6, solver_duration_s=30.0, backend="cuda",
            )


def _triangular_hydrograph(q_peak=2000.0):
    """Starts at zero, so the left-Riemann bound below is the whole error."""
    return {
        "t_array": np.array([0.0, 120.0, 400.0, 900.0]),
        "Q_t": np.array([0.0, q_peak, 0.3 * q_peak, 0.0]),
        "metadata": {"q_peak_m3_s": q_peak, "failure_time_s": 120.0},
    }


class TestMemberTimestep:
    """
    ONE timestep per iteration. The member clock, the injected volume and the
    solver step must all advance by the same dt, and that dt must be CFL-valid
    for the state the solver actually integrates, which is the state AFTER the
    injection.

    They used to be three different numbers (docs/validation_findings.md §11):
    the clock ran up to 2.6% ahead of the integrated physics, so arrival times
    read late, and the breach over-injected by up to 1.2%.
    """

    DURATION_S = 600.0

    def _run_recorded(self, monkeypatch, hydrograph):
        from jalraksha.solver import core

        steps = []  # (t at step start, dt used, CFL limit of the state stepped)
        original_advance = core.SWESolver._advance

        def recording_advance(solver, state, dt):
            steps.append((state.t, dt, solver.compute_cfl_timestep(state)))
            return original_advance(solver, state, dt)

        monkeypatch.setattr(core.SWESolver, "_advance", recording_advance)
        grid, state, manning, _ = _valley(members=1)
        result = run_ensemble_member(
            0, hydrograph, grid, state, manning,
            i_breach=grid.nx // 2, j_breach=3, solver_duration_s=self.DURATION_S,
        )
        assert result["success"], result.get("error")
        return result, steps, grid

    def test_member_clock_is_the_integrated_physics_time(self, monkeypatch):
        result, steps, _ = self._run_recorded(monkeypatch, _triangular_hydrograph())
        assert result["t_end_s"] == pytest.approx(sum(dt for _, dt, _ in steps), rel=1e-12)
        # Every step starts where the previous one ended: there is one clock.
        clock = 0.0
        for t_start, dt, _ in steps:
            assert t_start == pytest.approx(clock, rel=1e-12, abs=1e-12)
            clock += dt

    def test_every_step_is_cfl_valid_for_the_state_it_integrates(self, monkeypatch):
        result, steps, _ = self._run_recorded(monkeypatch, _triangular_hydrograph(20000.0))
        worst = max(dt / limit for _, dt, limit in steps)
        assert worst <= 1.0 + INJECTION_CFL_RTOL, f"a step ran at {worst:.9f}x its CFL limit"
        assert result["injection_step_overruns"] == 0
        assert result["injection_step_retries"] > 0, "test setup must exercise the shrink"

    def test_released_volume_is_the_hydrograph_over_the_integrated_time(self, monkeypatch):
        hydrograph = _triangular_hydrograph()
        result, steps, _ = self._run_recorded(monkeypatch, hydrograph)
        t_arr, q_arr = hydrograph["t_array"], hydrograph["Q_t"]

        # Exactly what the scheme integrates: the discharge at each step's start
        # time, held for that step's dt.
        discrete = sum(hydrograph_discharge(t, dt, q_arr, t_arr) * dt for t, dt, _ in steps)
        assert result["volume_released_m3"] == pytest.approx(discrete, rel=1e-9)

        # That is the continuous integral over the integrated time to within the
        # left-Riemann bound, 0.5 * max|dQ/dt| * sum(dt^2).
        t = np.linspace(0.0, result["t_end_s"], 400001)
        exact = float(np.trapezoid(np.interp(t, t_arr, q_arr), t))
        max_slope = float(np.max(np.abs(np.diff(q_arr) / np.diff(t_arr))))
        bound = 0.5 * max_slope * sum(dt * dt for _, dt, _ in steps)
        assert abs(result["volume_released_m3"] - exact) <= bound + 1e-9 * exact
