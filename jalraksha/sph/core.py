"""
Near-field SPH entry point (Phase 7).

WHAT USED TO BE HERE. `SPHNearFieldSolver` and a `run_near_field_sph` built on
it. Neither was SPH. There was no kernel, no neighbour search, no continuity
equation and no pressure gradient: `step()` applied the same acceleration
vector (0.5g, 0, -g) to every fluid particle and threw away the Tait pressure
it had just computed. Particles therefore moved on ballistic arcs that were
independent of each other, of the free surface, and of the terrain.

That is a worse failure than the np.random block it would have replaced in the
service layer, because ballistic trajectories look like a simulation. Under
CLAUDE.md's no-silent-fallback rule the code was deleted rather than kept as a
"fallback" — a plausible-looking wrong answer is the outcome that rule exists
to prevent.

The real implementation is jalraksha.sph.pysph_runner, which runs PySPH's
WCSPHScheme (Wendland quintic kernel, Tait equation of state, Monaghan
artificial viscosity, dynamic boundary particles) and raises
SPHUnavailableError rather than substituting anything when PySPH cannot run.
"""

from jalraksha.sph.pysph_runner import (  # noqa: F401  (re-export)
    SPHUnavailableError,
    is_pysph_available,
    run_near_field_sph,
    run_still_water_validation,
)

__all__ = [
    "SPHUnavailableError",
    "is_pysph_available",
    "run_near_field_sph",
    "run_still_water_validation",
]
