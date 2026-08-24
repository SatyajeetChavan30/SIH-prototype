"""
Configuration loading and validation for JalRaksha.

Phase 0 responsibility: Load config from file, CLI args, or environment.
Validate metric CRS, dam location, and approved data sources.

Config schema:
  - dam_location: (lat, lon) in metric CRS (EPSG:32643 for India)
  - dam_height: float (metres)
  - gross_storage: float (million cubic metres)
  - breach_mode: str ('overtopping', 'piping', 'seepage')
  - output_dir: path (cache location for DEM, results)
  - manning_n: float (friction coefficient; default 0.03)
  - time_step: float (seconds; validated by CFL)

Constraints (from CLAUDE.md):
  - Metric CRS only (never degrees)
  - No India-WRIS, Bhuvan, CartoDEM sources
  - Unvetted coefficients flagged with TODO + source requirement
  - Offline-first: all data fetched once, cached locally

Example:
  config = load_config("jalraksha.yaml")
  validate_metric_crs(config)
  cache_dir = setup_cache(config['output_dir'])
"""

from pathlib import Path
from typing import Dict, Any, Optional
import json
import yaml  # To be added to pyproject.toml


class ConfigError(Exception):
    """Raised when config validation fails."""

    pass


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from file.

    Args:
        config_path: Path to jalraksha.yaml or jalraksha.json.
                     If None, uses default ./jalraksha.yaml

    Returns:
        Parsed config dict.

    Raises:
        ConfigError: If file missing, invalid, or constraint violated.
    """
    if config_path is None:
        config_path = Path("jalraksha.yaml")
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        if config_path.suffix == ".yaml" or config_path.suffix == ".yml":
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        elif config_path.suffix == ".json":
            with open(config_path, "r") as f:
                config = json.load(f)
        else:
            raise ConfigError(f"Unsupported format: {config_path.suffix}")
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ConfigError(f"Failed to parse {config_path}: {e}")

    validate_config(config)
    return config


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate config against JalRaksha constraints.

    Raises:
        ConfigError: If constraint violated.
    """
    required_keys = ["dam_location", "dam_height", "gross_storage"]
    for key in required_keys:
        if key not in config:
            raise ConfigError(f"Missing required key: {key}")

    # Validate metric CRS (must be EPSG:32643 or equivalent UTM, never degrees)
    if "crs" in config:
        crs_str = config["crs"]
        if "32643" not in crs_str and "UTM" not in crs_str.upper():
            raise ConfigError(f"CRS must be metric (EPSG:32643 or UTM equivalent), got: {crs_str}")

    # Validate dam location is numeric
    try:
        lat, lon = config["dam_location"]
        float(lat), float(lon)
    except (TypeError, ValueError):
        raise ConfigError(f"dam_location must be (lat, lon) numeric pair")

    # Validate dam height and storage are positive
    if config["dam_height"] <= 0:
        raise ConfigError("dam_height must be > 0")
    if config["gross_storage"] <= 0:
        raise ConfigError("gross_storage must be > 0")

    # Check for forbidden data sources
    forbidden = ["india-wris", "bhuvan", "cartoudem"]
    config_str = str(config).lower()
    for source in forbidden:
        if source in config_str:
            raise ConfigError(f"Forbidden data source referenced: {source}")

    # Flag unvetted coefficients (Manning's n, breach regression params, etc.)
    if "manning_n" in config:
        # TODO: Validate Manning's n source from literature.md
        pass

    print(
        f"[OK] Config validated: dam={config.get('dam_name', 'unnamed')}, "
        f"height={config['dam_height']}m, storage={config['gross_storage']}Mm³"
    )


def setup_cache(output_dir: Optional[str] = None) -> Path:
    """
    Set up local cache directory for DEM and data.

    Args:
        output_dir: Cache root directory. If None, uses ./data/

    Returns:
        Path to cache directory.
    """
    if output_dir is None:
        cache_dir = Path("./data")
    else:
        cache_dir = Path(output_dir)

    # Create subdirectories for different data types
    (cache_dir / "dem").mkdir(parents=True, exist_ok=True)
    (cache_dir / "gee").mkdir(parents=True, exist_ok=True)
    (cache_dir / "results").mkdir(parents=True, exist_ok=True)

    print(f"[OK] Cache directory ready: {cache_dir}")
    return cache_dir
