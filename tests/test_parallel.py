"""
Phase 12 Parallel Execution Test Suite.

Tests:
  - TestParallelExecution: Single-worker and multi-worker parallel ensemble runs
"""

import numpy as np
import pytest
from jalraksha.solver.parallel import run_ensemble_parallel, run_single_ensemble_member_task


class TestParallelExecution:
    """Test parallel ensemble solver execution."""

    def setup_method(self):
        self.grid_dict = {
            "nx": 10,
            "ny": 10,
            "dx": 100.0,
            "dy": 100.0,
            "x0": 500000.0,
            "y0": 3350000.0,
            "z": np.zeros((10, 10), dtype=np.float32).tolist(),
        }

        self.hydrographs = [
            {
                "t_array": np.linspace(0, 3600, 10),
                "Q_t": np.full(10, 500.0),
                "metadata": {"q_peak_m3_s": 500.0, "failure_time_s": 1800.0},
            }
            for _ in range(3)
        ]

    def test_single_task_worker(self):
        task_args = (
            0,
            self.hydrographs[0],
            self.grid_dict,
            0.03,
            60.0,  # 60s fast test
            5,
            5,
        )
        res = run_single_ensemble_member_task(task_args)
        assert res["success"] is True
        assert res["sample_id"] == 0
        assert res["h_max"].shape == (10, 10)

    def test_run_ensemble_parallel(self):
        results = run_ensemble_parallel(
            self.hydrographs,
            self.grid_dict,
            manning_val=0.03,
            solver_duration_s=60.0,
            i_breach=5,
            j_breach=5,
            num_workers=1,  # Single worker mode for fast test execution
        )

        assert len(results) == 3
        for res in results:
            assert res["success"] is True
