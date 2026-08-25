"""
Impact analysis module for dam-break simulations.

Phase 6+: Convert hazard results to economic and social impact metrics.

Outputs:
- PAR (Population Affected Ratio) calculations
- Depth-damage curves for economic loss
- FD2320 hazard classification (see hazard.py)
"""

from jalraksha.impact.hazard import HazardClassifier
from jalraksha.impact.damage import DepthDamageAnalyzer
from jalraksha.impact.population import PopulationEstimator

__all__ = [
    "HazardClassifier",
    "DepthDamageAnalyzer",
    "PopulationEstimator"
]