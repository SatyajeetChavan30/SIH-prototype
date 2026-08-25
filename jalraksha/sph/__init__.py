"""
Phase 7: SPH Near-Field Coupling Package.

Implements 3D/2D Smoothed Particle Hydrodynamics (SPH) near-field breach simulation
and 1-way SWE -> SPH coupling handoff.

Modules:
  - domain: Near-field particle generation from terrain DEM & dam geometry
  - core: SPH near-field particle solver execution (PySPH / NumPy fallback)
  - coupling: 1-way SWE -> SPH boundary handoff interface
"""

from jalraksha.sph.domain import generate_near_field_particles, NearFieldDomain
from jalraksha.sph.core import SPHNearFieldSolver, run_near_field_sph
from jalraksha.sph.coupling import handoff_swe_to_sph, extract_sph_free_surface

__all__ = [
    "generate_near_field_particles",
    "NearFieldDomain",
    "SPHNearFieldSolver",
    "run_near_field_sph",
    "handoff_swe_to_sph",
    "extract_sph_free_surface",
]
