"""
Phase 10: Dashboard & Visualization Package.

Implements Streamlit web UI, Leafmap interactive maps, and hydrograph/hazard plotting.

Modules:
  - app: Streamlit main dashboard application entry point
  - maps: Leafmap / Folium interactive spatial map renderer
  - plots: Matplotlib / Plotly hydrograph & hazard distribution charts
"""

from jalraksha.dashboard.plots import plot_arrival_hydrographs, plot_hazard_breakdown
from jalraksha.dashboard.maps import create_inundation_folium_map

__all__ = [
    "plot_arrival_hydrographs",
    "plot_hazard_breakdown",
    "create_inundation_folium_map",
]
