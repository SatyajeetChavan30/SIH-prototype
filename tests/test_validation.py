"""
Phase 8 Validation & Benchmarking Test Suite.

Tests:
  - TestSpatialMetrics: CSI and F1-score for inundation extent
  - TestTimeMetrics: RMSE and Nash-Sutcliffe Efficiency (NSE)
  - TestHistoricalBenchmarks: Malpasset & Chamoli 2021 dataset evaluation
"""

import numpy as np
import pytest
from jalraksha.validation.metrics import compute_csi, compute_f1_score, compute_rmse, compute_nse
from jalraksha.validation.benchmarks import get_malpasset_benchmark, get_chamoli_benchmark, evaluate_benchmark


class TestSpatialMetrics:
    """Test spatial validation metrics (CSI & F1-score)."""

    def test_perfect_csi_and_f1(self):
        obs = np.ones((10, 10), dtype=np.float32)
        sim = np.ones((10, 10), dtype=np.float32)

        csi = compute_csi(obs, sim, threshold=0.1)
        f1 = compute_f1_score(obs, sim, threshold=0.1)

        assert csi == 1.0
        assert f1 == 1.0

    def test_disjoint_inundation_extent(self):
        obs = np.zeros((10, 10), dtype=np.float32)
        sim = np.zeros((10, 10), dtype=np.float32)
        obs[0:5, 0:5] = 1.0  # Top left
        sim[5:10, 5:10] = 1.0  # Bottom right

        csi = compute_csi(obs, sim, threshold=0.1)
        f1 = compute_f1_score(obs, sim, threshold=0.1)

        assert csi == 0.0
        assert f1 == 0.0

    def test_partial_overlap_csi(self):
        obs = np.zeros((10, 10), dtype=np.float32)
        sim = np.zeros((10, 10), dtype=np.float32)
        obs[0:6, 0:6] = 1.0  # 36 cells wet
        sim[0:4, 0:4] = 1.0  # 16 cells wet (all inside obs)

        # TP = 16, FP = 0, FN = 20 -> CSI = 16 / (16 + 0 + 20) = 16/36 = 0.444
        csi = compute_csi(obs, sim, threshold=0.1)
        assert np.isclose(csi, 16.0 / 36.0, atol=1e-3)


class TestTimeMetrics:
    """Test time-series validation metrics (RMSE & NSE)."""

    def test_perfect_rmse_and_nse(self):
        obs = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        sim = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)

        rmse = compute_rmse(obs, sim)
        nse = compute_nse(obs, sim)

        assert rmse == 0.0
        assert nse == 1.0

    def test_rmse_and_nse_calculation(self):
        obs = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        sim = np.array([12.0, 18.0, 32.0, 38.0], dtype=np.float32)  # Diff = [+2, -2, +2, -2]

        rmse = compute_rmse(obs, sim)
        nse = compute_nse(obs, sim)

        assert np.isclose(rmse, 2.0, atol=1e-2)
        assert 0.9 < nse < 1.0


class TestHistoricalBenchmarks:
    """Test Malpasset & Chamoli benchmark evaluations."""

    def test_malpasset_benchmark_dataset(self):
        bench = get_malpasset_benchmark()
        assert bench["dam_name"] == "Malpasset"
        assert len(bench["gauges"]) == 7

    def test_chamoli_benchmark_dataset(self):
        bench = get_chamoli_benchmark()
        assert bench["event_name"] == "Chamoli 2021"
        assert len(bench["gauges"]) == 4

    def test_evaluate_benchmark_matching(self):
        bench = get_malpasset_benchmark()
        sim_gauges = [
            {"arrival_time_s": g["arrival_time_s"]} for g in bench["gauges"]
        ]
        res = evaluate_benchmark(sim_gauges, bench)
        assert res["arrival_time_rmse_s"] == 0.0
        assert res["nse_score"] == 1.0
        assert res["mean_travel_error_pct"] == 0.0
