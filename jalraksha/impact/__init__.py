"""
Impact analysis module for dam-break simulations.

Phase 6+: Convert hazard results to economic and social impact metrics.

Outputs:
- PAR (Population Affected Ratio) calculations
- Depth-damage curves for economic loss, against a fetched exposure layer
- FD2320 hazard classification (see hazard.py)

``DepthDamageAnalyzer`` was exported here until its coefficients were found to
be attributed to a study that exists in no bibliography in this project. It is
deleted, not renamed; :func:`~jalraksha.impact.damage.estimate_sector_damage`
replaces it and takes its exposure from the catchment rather than from three
fixed constants. See ``damage.py``'s module docstring.
"""

from jalraksha.impact.damage import (
    HUIZINGA_2017_VERIFIED,
    SECTORS,
    DepthDamageCurveUnverified,
    UnknownSectorError,
    calculate_economic_loss,
    compute_depth_damage,
    estimate_sector_damage,
)
from jalraksha.impact.hazard import HazardClassifier
from jalraksha.impact.population import PopulationEstimator

__all__ = [
    "HazardClassifier",
    "PopulationEstimator",
    "SECTORS",
    "compute_depth_damage",
    "calculate_economic_loss",
    "estimate_sector_damage",
    "UnknownSectorError",
    "DepthDamageCurveUnverified",
    "HUIZINGA_2017_VERIFIED",
]
