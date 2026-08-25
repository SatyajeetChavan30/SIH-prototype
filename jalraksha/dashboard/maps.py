"""
Interactive Map Visualization Module (Phase 10).

Provides Folium / Leafmap interactive spatial map rendering with gauge markers
and flood inundation bounds.
"""

from typing import Dict, List, Optional


def create_inundation_folium_map(
    dam_lat: float = 30.3789,
    dam_lon: float = 78.4789,
    gauges: Optional[List[Dict]] = None,
    zoom_start: int = 10,
) -> Dict:
    """
    Construct Leafmap / Folium map configuration dictionary for interactive rendering.

    Args:
        dam_lat: Dam latitude
        dam_lon: Dam longitude
        gauges: List of gauge dicts
        zoom_start: Initial zoom level

    Returns:
        Dict with map configuration parameters & marker data
    """
    markers = [
        {
            "name": "Breach Location",
            "lat": dam_lat,
            "lon": dam_lon,
            "color": "red",
            "icon": "exclamation-triangle",
        }
    ]

    if gauges:
        for g in gauges:
            markers.append({
                "name": f"Gauge: {g['name']} ({g['distance_km']} km)",
                "lat": g["lat"],
                "lon": g["lon"],
                "color": "blue",
                "icon": "flag",
            })

    return {
        "center": [dam_lat, dam_lon],
        "zoom": zoom_start,
        "markers": markers,
        "tile_layer": "OpenStreetMap",
    }
