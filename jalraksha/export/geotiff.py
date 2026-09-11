"""
Cloud-Optimized GeoTIFF (COG) export for dam-break simulation rasters.

Phase 5: Export module for h_max, v_max, t_arrival, and other simulation outputs.

Implements:
  - export_raster_to_cog(): Single raster → COG file
  - export_ensemble_to_cogs(): Ensemble results → multiple COGs (median, p05, p95)
  - validate_cog(): Validate COG integrity

All outputs use EPSG:32643 (UTM 43N for India) or local UTM zone.
Format: 32-bit float, DEFLATE compression, 512x512 blocksize (Cloud Optimized).

References:
  Spec §5: Export formats
  Spec §9.1: COG specifications
  GeoTIFF Cloud Optimized spec: https://www.cogeo.org/
"""

import numpy as np
import rasterio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import warnings

from jalraksha.export.georef import grid_affine, to_north_up

# PROJ's data path is repaired once, in jalraksha/__init__.py, BEFORE rasterio
# is imported — which is the only point at which it can be repaired, since PROJ
# resolves its search path when the native library loads and ignores later
# changes to os.environ. This module used to pop PROJ_LIB/PROJ_DATA here
# instead. That ran far too late to help, and worse, it discarded the corrected
# path the package init had just installed.


def export_raster_to_cog(
    raster_data: np.ndarray,
    output_path: str,
    grid_dict: Dict,
    crs_epsg: int = 32643,
    data_name: str = "raster",
    metadata_tags: Optional[Dict] = None,
    compress: str = "deflate",
    blocksize: int = 512,
) -> str:
    """
    Export a single 2D raster array to Cloud-Optimized GeoTIFF.

    Args:
        raster_data: 2D numpy array [ny, nx] (32-bit float)
        output_path: Output file path (must end in .tif)
        grid_dict: Dict with keys:
            - "nx": int, number of cells in x
            - "ny": int, number of cells in y
            - "dx": float, cell size in x (m)
            - "dy": float, cell size in y (m)
            - "x0": float, origin x (m)
            - "y0": float, origin y (m)
        crs_epsg: EPSG code (default 32643 = UTM 43N for Tehri)
        data_name: Name of variable (e.g., "h_max", "t_arrival")
        metadata_tags: Dict of metadata to embed in GeoTIFF
        compress: Compression method ("deflate", "lzw", "zstd", or None)
        blocksize: COG blocksize in pixels (default 512)

    Returns:
        Path to output COG file

    Raises:
        ValueError: If raster_data shape doesn't match grid
    """
    output_path = str(output_path)

    # Validate dimensions
    ny_expected = grid_dict["ny"]
    nx_expected = grid_dict["nx"]
    ny_actual, nx_actual = raster_data.shape

    if (ny_actual, nx_actual) != (ny_expected, nx_expected):
        raise ValueError(
            f"Raster shape {(ny_actual, nx_actual)} does not match grid "
            f"({ny_expected}, {nx_expected})"
        )

    # Georeferencing comes from export/georef.py, which is the single definition
    # of how a solver grid maps to the world. Two things it fixes that were wrong
    # when this transform was built inline here: Grid.x0/y0 are the domain's
    # lower-left CORNER (not the centre of cell 0), and solver arrays are
    # SOUTH-UP while rasters are north-up. Together those errors placed the
    # exported raster a full domain-height south of its own terrain, upside-down
    # — invisible to any check short of opening the file over a basemap.
    transform = grid_affine(grid_dict)

    # Prepare metadata
    if metadata_tags is None:
        metadata_tags = {}

    metadata_tags = dict(metadata_tags)  # don't mutate caller's dict
    metadata_tags.update({
        "VARIABLE": data_name,
        "CREATION_DATE": datetime.utcnow().isoformat(),
        "CRS": f"EPSG:{crs_epsg}",
        "UNIT": "m" if data_name in ["h_max", "h_min", "depth"] else (
            "m/s" if "velocity" in data_name else "s"
        ),
    })

    # Build rasterio profile
    profile = {
        "driver": "GTiff",
        "dtype": rasterio.float32,
        "nodata": np.nan,
        "width": nx_actual,
        "height": ny_actual,
        "count": 1,
        "crs": f"EPSG:{crs_epsg}",
        "transform": transform,
        "compress": compress,
        "BLOCKXSIZE": blocksize,
        "BLOCKYSIZE": blocksize,
        "TILED": True,  # Required for COG
    }

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(output_path, "w", **profile) as dst:
        # Flip south-up solver rows into north-up raster rows; grid_affine()
        # above assumes exactly this pairing.
        dst.write(to_north_up(raster_data).astype(np.float32), 1)

        # Write metadata tags
        for key, val in metadata_tags.items():
            dst.update_tags(**{key: str(val)})

    return output_path


def export_ensemble_to_cogs(
    results_ensemble: List[Dict],
    grid_dict: Dict,
    output_dir: str,
    dam_name: str = "Dam",
    crs_epsg: int = 32643,
) -> Dict[str, str]:
    """
    Export ensemble results to COGs: median, p05, p95 for h_max, v_max, t_arrival.

    Args:
        results_ensemble: List of result dicts from solver, each containing:
            {
                "h_max": np.ndarray [ny, nx],
                "v_max": np.ndarray [ny, nx],
                "t_arrival": np.ndarray [ny, nx],
                "metadata": {...}
            }
        grid_dict: Grid definition (see export_raster_to_cog)
        output_dir: Output directory for COGs
        dam_name: Dam name (for metadata)
        crs_epsg: EPSG code for CRS

    Returns:
        Dict mapping variable_percentile -> file path
    """
    ny = grid_dict["ny"]
    nx = grid_dict["nx"]

    n_members = len(results_ensemble)

    # Aggregate ensembles
    h_max_ensemble = np.array([r.get("h_max", np.zeros((ny, nx))) for r in results_ensemble])
    v_max_ensemble = np.array([r.get("v_max", np.zeros((ny, nx))) for r in results_ensemble])
    t_arrival_ensemble = np.array([
        r.get("t_arrival", np.inf * np.ones((ny, nx))) for r in results_ensemble
    ])

    # Compute percentiles for h_max and v_max
    h_max_median = np.median(h_max_ensemble, axis=0)
    h_max_p05 = np.percentile(h_max_ensemble, 5, axis=0)
    h_max_p95 = np.percentile(h_max_ensemble, 95, axis=0)

    v_max_median = np.median(v_max_ensemble, axis=0)
    v_max_p05 = np.percentile(v_max_ensemble, 5, axis=0)
    v_max_p95 = np.percentile(v_max_ensemble, 95, axis=0)

    # For t_arrival, replace inf with NaN before percentiles
    t_arrival_clean = t_arrival_ensemble.copy()
    t_arrival_clean[np.isinf(t_arrival_clean)] = np.nan
    t_arrival_median = np.nanmedian(t_arrival_clean, axis=0)
    t_arrival_p05 = np.nanpercentile(t_arrival_clean, 5, axis=0)
    t_arrival_p95 = np.nanpercentile(t_arrival_clean, 95, axis=0)

    # Build metadata base
    metadata_base = {
        "DAM": dam_name,
        "ENSEMBLE_SIZE": n_members,
        "EXPORT_DATE": datetime.utcnow().isoformat(),
    }

    raster_paths = {}

    # h_max COGs
    for percentile, data, suffix in [
        (50, h_max_median, "median"),
        (5, h_max_p05, "p05"),
        (95, h_max_p95, "p95"),
    ]:
        metadata = {**metadata_base, "PERCENTILE": percentile}
        path = export_raster_to_cog(
            data,
            f"{output_dir}/h_max_{suffix}_cog.tif",
            grid_dict,
            crs_epsg=crs_epsg,
            data_name=f"h_max_p{percentile}",
            metadata_tags=metadata,
        )
        raster_paths[f"h_max_{suffix}"] = path

    # v_max COGs
    for percentile, data, suffix in [
        (50, v_max_median, "median"),
        (5, v_max_p05, "p05"),
        (95, v_max_p95, "p95"),
    ]:
        metadata = {**metadata_base, "PERCENTILE": percentile}
        path = export_raster_to_cog(
            data,
            f"{output_dir}/v_max_{suffix}_cog.tif",
            grid_dict,
            crs_epsg=crs_epsg,
            data_name=f"v_max_p{percentile}",
            metadata_tags=metadata,
        )
        raster_paths[f"v_max_{suffix}"] = path

    # t_arrival COGs
    for percentile, data, suffix in [
        (50, t_arrival_median, "median"),
        (5, t_arrival_p05, "p05"),
        (95, t_arrival_p95, "p95"),
    ]:
        metadata = {**metadata_base, "PERCENTILE": percentile}
        path = export_raster_to_cog(
            data,
            f"{output_dir}/t_arrival_{suffix}_cog.tif",
            grid_dict,
            crs_epsg=crs_epsg,
            data_name=f"t_arrival_p{percentile}",
            metadata_tags=metadata,
        )
        raster_paths[f"t_arrival_{suffix}"] = path

    return raster_paths


def validate_cog(cog_path: str) -> bool:
    """
    Validate that a file is a proper Cloud-Optimized GeoTIFF.

    Returns True if the file:
      - Opens successfully with rasterio
      - Has a defined CRS
      - Is tiled (COG requirement)
    """
    try:
        with rasterio.open(cog_path) as src:
            if src.crs is None:
                warnings.warn(f"{cog_path}: No CRS defined")
                return False
            if not src.profile.get("tiled"):
                warnings.warn(f"{cog_path}: Not tiled (COG requirement)")
                return False

            return True
    except Exception as e:
        warnings.warn(f"{cog_path}: Failed to open as COG: {e}")
        return False


# Backwards-compatible alias expected by tests and export/__init__.py.
export_cog = export_raster_to_cog
