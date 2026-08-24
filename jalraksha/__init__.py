"""
JalRaksha: Dam-break inundation modelling system.

Combines 2D shallow-water equation (SWE) solver for far-field propagation
with 3D Smoothed Particle Hydrodynamics (SPH) for violent near-field dynamics.
Uses exclusively open data (Copernicus DEM, Google Earth Engine, CWC dam registers).

Public API:
  - jalraksha.cli — Command-line interface
  - jalraksha.config — Configuration loading and validation
  - jalraksha.cache — Data cache management
  - jalraksha.dem — DEM fetch and processing
  - jalraksha.solver.core — 2D SWE solver (Phase 1+)
  - jalraksha.export — Output formats (GeoTIFF, Shapefile, KML)

Phases:
  Phase 0: CLI, cache, DEM fetch (this module's scope)
  Phase 1: Solver core (HLLC flux, Audusse reconstruction)
  Phase 2–3: Terrain conditioning, breach regressions
  Phase 4: End-to-end dam-break pipeline
  Phase 5+: Export, impact, SPH, GEE, dashboard

For detailed constraints and testing strategy, see CLAUDE.md.
"""

__version__ = "0.0.1-alpha"
__author__ = "JalRaksha Team (SIH 2026)"

# Public API — only import what's stable
# Phase 0: config, cli, cache, dem
# Phase 1+: solver, terrain, export, sph (as they stabilize)
