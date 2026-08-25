"""
Phase 10 Dashboard & Visualization Test Suite.

Tests:
  - TestDashboardPlots: Hydrograph bar plot & hazard breakdown pie chart generation
  - TestDashboardMaps: Leafmap / Folium interactive map configuration
"""

import matplotlib.pyplot as plt
import pytest
from jalraksha.dashboard.plots import plot_arrival_hydrographs, plot_hazard_breakdown
from jalraksha.dashboard.maps import create_inundation_folium_map


class TestDashboardPlots:
    """Test dashboard plot generators."""

    def test_plot_arrival_hydrographs(self):
        arrival_dict = {
            "Koteshwar": {"median": 1800.0, "p05": 1600.0, "p95": 2000.0},
            "Devprayag": {"median": 3600.0, "p05": 3200.0, "p95": 4000.0},
        }

        fig = plot_arrival_hydrographs(arrival_dict)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_plot_hazard_breakdown(self):
        exposed_dict = {
            "Low": {"population": 100.0},
            "Moderate": {"population": 250.0},
            "High": {"population": 400.0},
            "Extreme": {"population": 150.0},
        }

        fig = plot_hazard_breakdown(exposed_dict)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestDashboardMaps:
    """Test interactive map configuration generator."""

    def test_create_inundation_folium_map(self):
        gauges = [{"name": "Koteshwar", "distance_km": 13.0, "lat": 30.34, "lon": 78.53}]
        map_config = create_inundation_folium_map(30.3789, 78.4789, gauges=gauges)

        assert map_config["center"] == [30.3789, 78.4789]
        assert len(map_config["markers"]) == 2
