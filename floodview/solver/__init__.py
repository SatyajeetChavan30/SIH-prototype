"""
Solver core for 2D shallow-water equation (SWE) computations.

Phase 1 responsibility: Implement well-balanced 2D SWE solver with:
- HLLC flux scheme with transverse-momentum correction
- Audusse hydrostatic reconstruction
- MUSCL reconstruction
- Wet/dry treatment
- Manning friction
- Adaptive CFL timestepping

Gated tests:
- Ritter dry-bed dam-break (1D)
- Stoker wet-bed dam-break (1D)
- Thacker parabolic bowl (2D oscillation)
"""

from jalraksha.solver.core import SWESolver
from jalraksha.solver.types import Grid, State

__all__ = ["SWESolver", "Grid", "State"]