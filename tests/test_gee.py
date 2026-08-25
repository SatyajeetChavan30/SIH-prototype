"""
Phase 9 Google Earth Engine & Open Data Test Suite.

Tests:
  - TestGEEAuth: Session initialization & offline fallback mode
  - TestSARFloodMapping: Sentinel-1 SAR change detection & thresholding
  - TestGHSLPopulation: Population density grid retrieval & distribution
"""

import numpy as np
import pytest
from jalraksha.gee.auth import init_gee, is_gee_available
from jalraksha.gee.sar import process_sentinel1_sar_flood
from jalraksha.gee.population import fetch_ghsl_population_grid


class TestGEEAuth:
    """Test GEE session initialization & offline fallback."""

    def test_init_gee_offline_fallback(self):
        success, msg = init_gee(offline_fallback=True)
        assert isinstance(success, bool)
        assert isinstance(msg, str)

    def test_is_gee_available(self):
        avail = is_gee_available()
        assert isinstance(avail, bool)


class TestSARFloodMapping:
    """Test Sentinel-1 SAR flood processing."""

    def test_sar_flood_output_structure(self):
        bbox = (78.4, 30.3, 78.6, 30.5)
        res = process_sentinel1_sar_flood(bbox, grid_shape=(30, 30))

        assert "water_mask" in res
        assert "backscatter_delta_db" in res
        assert res["water_mask"].shape == (30, 30)
        assert res["water_mask"].dtype == bool
        assert res["source"] is not None

    def test_thresholding_logic(self):
        bbox = (78.4, 30.3, 78.6, 30.5)
        res = process_sentinel1_sar_flood(bbox, threshold_db=-3.0, grid_shape=(20, 20))

        # Check threshold consistency
        mask = res["water_mask"]
        delta = res["backscatter_delta_db"]
        assert np.all(mask == (delta <= -3.0))


class TestGHSLPopulation:
    """Test GHSL population grid fetching."""

    def test_ghsl_population_structure(self):
        bbox = (78.4, 30.3, 78.6, 30.5)
        res = fetch_ghsl_population_grid(bbox, grid_shape=(40, 40))

        assert "population_grid" in res
        assert "total_population" in res
        assert res["population_grid"].shape == (40, 40)
        assert res["total_population"] > 0.0
        assert np.all(res["population_grid"] >= 0.0)
