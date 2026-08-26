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


def _repair_proj_data_path() -> None:
    """
    Point PROJ at rasterio's bundled database if the inherited one is unusable.

    Any machine with PostgreSQL/PostGIS, QGIS, or another GDAL stack installed
    may export a system-wide PROJ_LIB. When that database predates the layout
    rasterio's PROJ expects, every CRS lookup fails with:

        CRSError: The EPSG code is unknown. PROJ: proj_create_from_database:
        ... contains DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6
        is expected. It comes from another PROJ installation.

    which takes out reprojection, and with it the whole terrain pipeline. We
    only override a PROJ_LIB that is actually broken — a valid one, including a
    deliberate override, is left untouched.
    """
    import os
    from pathlib import Path

    configured = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
    if configured and (Path(configured) / "proj.db").exists():
        try:
            import sqlite3

            with sqlite3.connect(f"file:{Path(configured) / 'proj.db'}?mode=ro", uri=True) as conn:
                minor = conn.execute(
                    "SELECT value FROM metadata WHERE key = 'DATABASE.LAYOUT.VERSION.MINOR'"
                ).fetchone()
            if minor is not None and int(minor[0]) >= 6:
                return  # inherited database is fine; leave it alone
        except Exception:
            pass  # unreadable or unexpected schema — fall through and replace

    try:
        import rasterio

        bundled = Path(rasterio.__file__).parent / "proj_data"
    except Exception:
        return
    if (bundled / "proj.db").exists():
        os.environ["PROJ_DATA"] = str(bundled)
        os.environ["PROJ_LIB"] = str(bundled)


_repair_proj_data_path()

# Public API — only import what's stable
# Phase 0: config, cli, cache, dem
# Phase 1+: solver, terrain, export, sph (as they stabilize)
