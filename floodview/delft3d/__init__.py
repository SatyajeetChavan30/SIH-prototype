"""
Delft3D Flexible Mesh Integration Package.

Provides:
  - setup: Generate Delft3D FM input files (.mdu, grid, BCs) from FloodView config
  - runner: Execute dflowfm binary or fallback to built-in SWE solver
  - comparison: Side-by-side SPH vs Delft3D result comparison

Two-tier architecture:
  Tier A: Real Delft3D FM binary (if found on PATH)
  Tier B: Built-in SWE solver fallback (same Saint-Venant equations)

Both tiers expose identical Python interfaces.
"""

from floodview.delft3d.runner import run_delft3d_simulation
from floodview.delft3d.comparison import compare_sph_vs_delft3d

__all__ = ["run_delft3d_simulation", "compare_sph_vs_delft3d"]
