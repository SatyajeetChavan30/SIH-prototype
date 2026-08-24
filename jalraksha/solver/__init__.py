"""
JalRaksha solver module (Phase 1+).

Contains 2D shallow-water equation (SWE) implementation:
  - HLLC Riemann solver with transverse-momentum correction
  - MUSCL reconstruction with Audusse hydrostatic method
  - Well-balanced formulation (not surface-gradient)
  - Wet/dry treatment, Manning friction, adaptive CFL

Gated on analytical tests:
  - Ritter dry-bed dam-break (1D exact solution)
  - Stoker wet-bed dam-break (1D exact solution)
  - Thacker parabolic bowl (2D oscillation exact solution)
  - Lake-at-rest: <0.1% velocity over any bathymetry
  - Mass conservation: <0.1% volume loss over 1000 timesteps

Public API (Phase 1 target):
  - jalraksha.solver.core.SWESolver — main solver class
  - jalraksha.solver.flux.hllc_flux() — HLLC scheme
  - jalraksha.solver.types.State — state vector (depth, momentum_x, momentum_y)

See CLAUDE.md for conventions (no fastmath in integrator, metric CRS, etc.)
"""

# Phase 1 implementation TBD
# Placeholder for Phase 0 compatibility
