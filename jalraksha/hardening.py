"""
Phase 11: Hardening — Input Validation, Error Recovery & CLI Robustness.

Centralised guard functions for all user-facing inputs:
  - Dam parameter range checks (height, storage, lat/lon)
  - DEM path existence and rasterio readability
  - Ensemble size / solver duration bounds
  - Graceful error messages instead of raw stack traces

All validators raise HardeningError (a ValueError subclass) with a
human-readable message so the CLI can catch it cleanly.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


class HardeningError(ValueError):
    """Raised when user-supplied input fails a validation check."""

    pass


# ── Dam parameter bounds ──────────────────────────────────────────────────────
DAM_HEIGHT_MIN_M = 10.0      # Minimum dam height (m)
DAM_HEIGHT_MAX_M = 400.0     # Maximum dam height (m)  — tallest is ~300 m
DAM_STORAGE_MIN_MCM = 0.1    # Minimum gross storage (MCM)
DAM_STORAGE_MAX_MCM = 100_000.0  # Maximum gross storage (MCM)

LAT_MIN = -90.0
LAT_MAX = 90.0
LON_MIN = -180.0
LON_MAX = 180.0

ENSEMBLE_SIZE_MIN = 1
ENSEMBLE_SIZE_MAX = 10_000
SOLVER_DURATION_MIN_S = 60.0        # At least 1 minute
SOLVER_DURATION_MAX_S = 7 * 24 * 3600  # At most 1 week


def validate_dam_config(config: Dict[str, Any]) -> None:
    """
    Validate all fields of a dam configuration dictionary.

    Args:
        config: Dict with keys: name, lat, lon, height_m, storage_mm3,
                dam_type, failure_mode.

    Raises:
        HardeningError: If any field is missing or out of range.
    """
    required_keys = ["name", "lat", "lon", "height_m", "storage_mm3"]
    for key in required_keys:
        if key not in config:
            raise HardeningError(
                f"Missing required dam config key: '{key}'. "
                f"Expected keys: {required_keys}"
            )

    name = config["name"]
    if not isinstance(name, str) or not name.strip():
        raise HardeningError("Dam 'name' must be a non-empty string.")

    lat = config["lat"]
    if not isinstance(lat, (int, float)) or not (LAT_MIN <= lat <= LAT_MAX):
        raise HardeningError(
            f"Dam latitude {lat!r} out of range [{LAT_MIN}, {LAT_MAX}]. "
            "Use decimal degrees."
        )

    lon = config["lon"]
    if not isinstance(lon, (int, float)) or not (LON_MIN <= lon <= LON_MAX):
        raise HardeningError(
            f"Dam longitude {lon!r} out of range [{LON_MIN}, {LON_MAX}]. "
            "Use decimal degrees."
        )

    height = config["height_m"]
    if not isinstance(height, (int, float)) or not (DAM_HEIGHT_MIN_M <= height <= DAM_HEIGHT_MAX_M):
        raise HardeningError(
            f"Dam height {height!r} m out of plausible range "
            f"[{DAM_HEIGHT_MIN_M}, {DAM_HEIGHT_MAX_M}] m."
        )

    storage = config["storage_mm3"]
    if not isinstance(storage, (int, float)) or not (DAM_STORAGE_MIN_MCM <= storage <= DAM_STORAGE_MAX_MCM):
        raise HardeningError(
            f"Dam storage {storage!r} MCM out of range "
            f"[{DAM_STORAGE_MIN_MCM}, {DAM_STORAGE_MAX_MCM}] MCM."
        )

    valid_failure_modes = {"overtopping", "piping", "seismic", "foundation", "other"}
    failure_mode = config.get("failure_mode", "overtopping")
    if failure_mode not in valid_failure_modes:
        raise HardeningError(
            f"Unsupported failure_mode '{failure_mode}'. "
            f"Valid modes: {sorted(valid_failure_modes)}"
        )

    valid_dam_types = {"embankment", "concrete", "arch", "rockfill", "gravity", "other"}
    dam_type = config.get("dam_type", "embankment")
    if dam_type not in valid_dam_types:
        raise HardeningError(
            f"Unsupported dam_type '{dam_type}'. "
            f"Valid types: {sorted(valid_dam_types)}"
        )


def validate_ensemble_params(
    ensemble_size: int,
    solver_duration_s: float,
    target_resolution: float,
) -> None:
    """
    Validate simulation ensemble and solver parameters.

    Args:
        ensemble_size: Number of Monte Carlo members.
        solver_duration_s: Simulation wall-clock time in seconds.
        target_resolution: Grid cell size in metres.

    Raises:
        HardeningError: On any out-of-bounds value.
    """
    if not isinstance(ensemble_size, int) or not (ENSEMBLE_SIZE_MIN <= ensemble_size <= ENSEMBLE_SIZE_MAX):
        raise HardeningError(
            f"ensemble_size={ensemble_size!r} must be an integer in "
            f"[{ENSEMBLE_SIZE_MIN}, {ENSEMBLE_SIZE_MAX}]."
        )

    if not isinstance(solver_duration_s, (int, float)) or not (
        SOLVER_DURATION_MIN_S <= solver_duration_s <= SOLVER_DURATION_MAX_S
    ):
        raise HardeningError(
            f"solver_duration_s={solver_duration_s!r} s out of range "
            f"[{SOLVER_DURATION_MIN_S}, {SOLVER_DURATION_MAX_S}] s."
        )

    if not isinstance(target_resolution, (int, float)) or target_resolution <= 0 or target_resolution > 5000:
        raise HardeningError(
            f"target_resolution={target_resolution!r} m must be a positive "
            "number ≤ 5000 m."
        )


def validate_dem_path(dem_path: Optional[str]) -> None:
    """
    Verify the DEM path exists and is a readable raster file.

    Args:
        dem_path: Path to GeoTIFF DEM or None (offline/synthetic mode).

    Raises:
        HardeningError: If the path does not exist or cannot be opened.
    """
    if dem_path is None:
        return  # None = synthetic/offline mode, always valid

    if not isinstance(dem_path, str):
        raise HardeningError(f"dem_path must be a string or None, got {type(dem_path)}.")

    if not os.path.exists(dem_path):
        raise HardeningError(
            f"DEM file not found: '{dem_path}'. "
            "Run `jalraksha cache --list` to see cached files, "
            "or omit --dem-path to use synthetic terrain."
        )

    # Check it's a raster file (avoid importing rasterio unless path exists)
    raster_extensions = {".tif", ".tiff", ".geotiff", ".vrt", ".nc", ".hdf5", ".h5"}
    ext = os.path.splitext(dem_path)[1].lower()
    if ext not in raster_extensions:
        raise HardeningError(
            f"DEM path '{dem_path}' does not have a recognised raster extension. "
            f"Supported: {sorted(raster_extensions)}"
        )


def validate_output_dir(output_dir: str) -> str:
    """
    Ensure output directory exists (creates it if needed) and is writable.

    Args:
        output_dir: Path to desired output directory.

    Returns:
        Absolute path to the output directory.

    Raises:
        HardeningError: If the directory cannot be created or is read-only.
    """
    output_dir = os.path.abspath(output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise HardeningError(
            f"Cannot create output directory '{output_dir}': {exc}"
        ) from exc

    # Quick write-access test
    test_file = os.path.join(output_dir, ".jalraksha_write_test")
    try:
        with open(test_file, "w") as fh:
            fh.write("ok")
        os.remove(test_file)
    except OSError as exc:
        raise HardeningError(
            f"Output directory '{output_dir}' is not writable: {exc}"
        ) from exc

    return output_dir


def safe_run(func, *args, context: str = "", **kwargs):
    """
    Execute a callable and convert unexpected exceptions to HardeningError
    with a context-enriched message.

    Args:
        func: Callable to execute.
        *args: Positional arguments.
        context: Human-readable description of the operation (for error messages).
        **kwargs: Keyword arguments.

    Returns:
        Return value of func(*args, **kwargs).

    Raises:
        HardeningError: Wrapping any unexpected exception.
    """
    try:
        return func(*args, **kwargs)
    except HardeningError:
        raise  # Already a hardening error — don't double-wrap
    except MemoryError as exc:
        raise HardeningError(
            f"{context}: Out of memory. "
            "Try reducing ensemble_size or increasing target_resolution (coarser grid)."
        ) from exc
    except FileNotFoundError as exc:
        raise HardeningError(f"{context}: File not found — {exc}") from exc
    except Exception as exc:
        raise HardeningError(
            f"{context}: Unexpected error — {type(exc).__name__}: {exc}"
        ) from exc


def check_forbidden_sources(text: str) -> List[str]:
    """
    Scan a string for references to geo-fenced or forbidden data sources.

    Per AGENTS.md critical constraints: India-WRIS, ffs.india-water.gov.in,
    Bhuvan, CartoDEM are forbidden.

    Args:
        text: Any string (URL, config value, etc.) to check.

    Returns:
        List of forbidden source names found (empty if clean).
    """
    forbidden = [
        "india-wris",
        "ffs.india-water.gov.in",
        "bhuvan",
        "cartodem",
        "mullaperiyar",  # Explicitly forbidden dam
        "fabdem",        # CC BY-NC-SA — not redistribution-compatible
        "merit",         # CC BY-NC — not redistribution-compatible
    ]
    lower_text = text.lower()
    found = [src for src in forbidden if src in lower_text]
    return found
