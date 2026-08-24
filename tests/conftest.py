"""
Pytest fixtures and configuration for JalRaksha tests.

Provides:
- temp_cache_dir: Temporary directory for cache operations
- sample_config: Sample configuration dict for Tehri dam
- mock_dem_geotiff: Mock GeoTIFF array for testing without network
"""

import pytest
from pathlib import Path
import tempfile
import json

import numpy as np
import rasterio
from rasterio.transform import Affine


@pytest.fixture
def temp_cache_dir(tmp_path):
    """
    Temporary cache directory for testing.

    Returns:
        Path object pointing to a temporary directory
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def sample_config():
    """
    Sample configuration for Tehri dam (demo case).

    Returns:
        Dict with dam parameters
    """
    return {
        "dam_name": "Tehri",
        "dam_location": (30.3789, 78.4789),  # lat, lon
        "dam_height": 260.0,  # metres
        "gross_storage": 3540.0,  # million m³
        "crs": "EPSG:32643",  # UTM zone 43N (India)
        "breach_mode": "overtopping",
        "manning_n": 0.03,  # Concrete spillway (placeholder, source: TODO)
    }


@pytest.fixture
def mock_dem_geotiff(temp_cache_dir):
    """
    Create a mock GeoTIFF DEM for testing without network fetch.

    Generates a 100 × 100 cell synthetic DEM:
    - Elevation: Gaussian hill at center + random noise
    - CRS: WKT string (avoids PROJ database version conflicts)
    - Resolution: 100 m/cell
    - Bounds: arbitrary (UTM coords around Tehri dam)

    Returns:
        Path to mock GeoTIFF file
    """
    dem_dir = temp_cache_dir / "dem"
    dem_dir.mkdir(parents=True, exist_ok=True)

    # Create synthetic elevation data
    nx, ny = 100, 100
    x = np.linspace(0, 10000, nx)  # 10 km extent
    y = np.linspace(0, 10000, ny)
    xx, yy = np.meshgrid(x, y)

    # Gaussian hill at center
    cx, cy = 5000, 5000
    elev = 500 + 200 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (1000**2))

    # Add random noise
    np.random.seed(42)
    elev += np.random.normal(0, 10, elev.shape)

    # Ensure no negative elevations
    elev = np.maximum(elev, 100)

    # Create GeoTIFF
    mock_dem_path = dem_dir / "mock_dem.tif"

    # Transform: upper-left corner at (340000, 3367000) UTM 43N, 100 m resolution
    transform = Affine(100, 0, 340000, 0, -100, 3367000)

    # UTM 43N WKT (avoids PROJ database version conflicts)
    utm43n_wkt = (
        'PROJCS["WGS 84 / UTM zone 43N",'
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
        'PROJECTION["Transverse_Mercator"],'
        'PARAMETER["latitude_of_origin",0],'
        'PARAMETER["central_meridian",75],'
        'PARAMETER["scale_factor",0.9996],'
        'PARAMETER["false_easting",500000],'
        'PARAMETER["false_northing",0],'
        'UNIT["metre",1,AUTHORITY["EPSG","9001"]]]'
    )

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": nx,
        "height": ny,
        "count": 1,
        "crs": utm43n_wkt,
        "transform": transform,
        "compress": "deflate",
    }

    with rasterio.open(str(mock_dem_path), "w", **profile) as dst:
        dst.write(elev.astype("float32"), 1)

    return mock_dem_path


@pytest.fixture
def sample_cache_metadata(temp_cache_dir):
    """
    Create sample cache metadata for testing cache operations.

    Returns:
        Path to metadata JSON file
    """
    metadata = {
        "https://example.com/dem_tile_1.tif": {
            "path": str(temp_cache_dir / "dem" / "tile_1.tif"),
            "timestamp": "2026-08-24T12:00:00",
            "hash": "abc123def456",
            "size_bytes": 1000000,
            "format": "GeoTIFF",
        }
    }

    metadata_path = temp_cache_dir / "CACHE_METADATA.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f)

    return metadata_path
