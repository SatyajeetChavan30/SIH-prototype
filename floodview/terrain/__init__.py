"""
Terrain processing module for dam-break simulations.

Phase 2–3: Terrain conditioning and breach modeling.

Builds domain from DEM, computes breach location, generates hydrographs.
"""

from jalraksha.terrain.domain import build_domain, compute_breach_location, latlon_to_utm, compute_utm_zone
from jalraksha.terrain.breach import synthesize_breach_ensemble, ensemble_statistics

__all__ = [
    "build_domain",
    "compute_breach_location",
    "latlon_to_utm",
    "compute_utm_zone",
    "synthesize_breach_ensemble",
    "ensemble_statistics"
]