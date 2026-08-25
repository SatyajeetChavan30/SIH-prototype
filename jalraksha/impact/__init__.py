"""
Phase 6: Impact Analysis & Loss-of-Life Estimation Package.

Modules:
  - hazard: FD2320 hazard rating calculation & hazard categorization
  - damage: JRC depth-damage functions for economic loss estimation
  - population: Population exposure & Population at Risk (PAR) analysis
  - fatality: Graham (1989), Jonkman (2008), DeKay-McClelland (1993) loss-of-life models
"""

from jalraksha.impact.hazard import compute_fd2320_hazard_rating, categorize_hazard_zones
from jalraksha.impact.damage import compute_depth_damage, calculate_economic_loss
from jalraksha.impact.population import compute_population_exposure, compute_par
from jalraksha.impact.fatality import estimate_loss_of_life_graham, estimate_loss_of_life_jonkman

__all__ = [
    "compute_fd2320_hazard_rating",
    "categorize_hazard_zones",
    "compute_depth_damage",
    "calculate_economic_loss",
    "compute_population_exposure",
    "compute_par",
    "estimate_loss_of_life_graham",
    "estimate_loss_of_life_jonkman",
]
