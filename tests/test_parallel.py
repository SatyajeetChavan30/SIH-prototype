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

from jalraksha.solver.parallel import run_ensemble, run_ensemble_member
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
        kwargs = dict(
            i_breach=6, j_breach=6, solver_duration_s=60.0,
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
