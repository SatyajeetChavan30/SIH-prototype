"""
Phase 7: SPH Near-Field Coupling Package.

Implements 3D/2D Smoothed Particle Hydrodynamics (SPH) near-field breach simulation
and 1-way SWE -> SPH coupling handoff.

Modules:
  - domain: Near-field particle generation from terrain DEM & dam geometry
  - engine: picks the SPH engine (DualSPHysics when installed, else PySPH)
    and dispatches to it; the entry points below come from here
  - dualsphysics_runner: near-field run in DualSPHysics v5.4 (native CUDA)
  - pysph_runner: real WCSPH near-field execution via PySPH (reference engine)
  - geometry: engine-neutral near-field geometry and result checks
  - core: thin re-export of the engine entry points (the hand-rolled solver
    that used to live here was not SPH and was removed - see its docstring)
  - coupling: 1-way SWE -> SPH boundary handoff interface
"""

from jalraksha.sph.domain import generate_near_field_particles, NearFieldDomain
from jalraksha.sph.engine import (
    resolve_sph_engine,
    run_near_field_sph,
    run_still_water_validation,
)
from jalraksha.sph.geometry import SPHUnavailableError
from jalraksha.sph.pysph_runner import is_pysph_available
from jalraksha.sph.coupling import handoff_swe_to_sph, extract_sph_free_surface

__all__ = [
    "generate_near_field_particles",
    "NearFieldDomain",
    "SPHUnavailableError",
    "is_pysph_available",
    "resolve_sph_engine",
    "run_near_field_sph",
    "run_still_water_validation",
    "handoff_swe_to_sph",
    "extract_sph_free_surface",
]
