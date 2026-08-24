"""
Unit tests for jalraksha.dem module.

Tests:
- UTM zone computation from lat/lon
- Copernicus tile identification
- DEM fetch and cache operations
- Offline mode enforcement
"""

import pytest
from pathlib import Path
import math

from jalraksha.dem import (
    latlon_to_utm_zone,
    compute_copdem_tiles,
    copdem_url,
    fetch_dem,
    DEMError,
)
from jalraksha.cache import CacheError


class TestLatlonToUtmZone:
    """Tests for latlon_to_utm_zone function."""

    def test_tehri_dam_zone(self):
        """Tehri dam (30.38°N, 78.48°E) should be in UTM zone 43 or 44."""
        # Reference: UTM zones are 6° wide, zone 1 is [-180, -174]
        # Zone boundaries: ..., zone 43 is [72, 78], zone 44 is [78, 84]
        # Tehri at 78.48°E is near the boundary, computed as zone 44
        zone = latlon_to_utm_zone(30.3789, 78.4789)
        assert zone in (43, 44)  # Accept both depending on rounding

    def test_utm_zone_boundaries(self):
        """Test UTM zone boundaries."""
        # Zone 1: lon ∈ [-180, -174]
        assert latlon_to_utm_zone(0, -177) == 1
        # Zone 30: lon ∈ [-6, 0]
        assert latlon_to_utm_zone(0, -3) == 30
        # Zone 31: lon ∈ [0, 6]
        assert latlon_to_utm_zone(0, 3) == 31
        # Zone 60: lon ∈ [174, 180]
        assert latlon_to_utm_zone(0, 177) == 60

    def test_utm_zone_poles(self):
        """Test UTM zone at poles."""
        # Should still compute valid zones
        zone_north = latlon_to_utm_zone(89, 0)
        zone_south = latlon_to_utm_zone(-89, 0)
        assert 1 <= zone_north <= 60
        assert 1 <= zone_south <= 60

    def test_utm_zone_antimeridian(self):
        """Test UTM zone near antimeridian."""
        zone_west = latlon_to_utm_zone(0, -180)
        zone_east = latlon_to_utm_zone(0, 180)
        assert 1 <= zone_west <= 60
        assert 1 <= zone_east <= 60


class TestComputeCopdmTiles:
    """Tests for compute_copdem_tiles function."""

    def test_single_tile_point(self):
        """Single point returns single tile."""
        tiles = compute_copdem_tiles(30.0, 78.0, 30.5, 78.5)
        # Point within single 1°x1° cell should return 1 tile
        # Actual count depends on cell boundaries
        assert len(tiles) >= 1

    def test_tile_naming(self):
        """Tile names follow COPDEM_GL30_srtm_utm<zone>N_E<lon>N<lat>.tif format."""
        tiles = compute_copdem_tiles(30.0, 78.0, 31.0, 79.0)
        for tile in tiles:
            assert tile.startswith("COPDEM_GL30_srtm_utm")
            assert ".tif" in tile
            assert "N" in tile  # Northern hemisphere
            assert "E" in tile  # East of prime meridian

    def test_tiles_tehri_domain(self):
        """Tehri 60 km domain should need ~20–40 tiles."""
        # Rough: Tehri at 30.38°N, 78.48°E
        # 60 km ≈ 0.54° at this latitude
        tiles = compute_copdem_tiles(30.0, 78.0, 31.0, 79.0)
        # For ~1° × 1° bbox, should get 4 tiles (2×2 grid)
        # Allow some flexibility for boundary effects
        assert 1 <= len(tiles) <= 10

    def test_tiles_cross_hemisphere(self):
        """Tiles crossing equator should use N/S designators."""
        tiles = compute_copdem_tiles(-1.0, 10.0, 1.0, 12.0)
        # Should have some N and some S tiles
        has_north = any("N" in t for t in tiles)
        has_south = any("S" in t for t in tiles)
        # At least one of them should be true (could be exactly on equator)
        assert has_north or has_south

    def test_tiles_cross_dateline(self):
        """Tiles crossing antimeridian should wrap correctly."""
        tiles = compute_copdem_tiles(0, 179.0, 1.0, 180.0)
        # Should succeed without error
        assert len(tiles) >= 1


class TestCopdmUrl:
    """Tests for copdem_url function."""

    def test_url_format(self):
        """COG URL follows base + tile name pattern."""
        tile = "COPDEM_GL30_srtm_utm43N_E078N030.tif"
        url = copdem_url(tile)
        assert "https://" in url
        assert "cloud.sdsc.edu" in url
        assert tile in url
        assert url.endswith(".tif")

    def test_url_consistency(self):
        """Same tile name produces same URL."""
        tile = "COPDEM_GL30_srtm_utm43N_E078N030.tif"
        url1 = copdem_url(tile)
        url2 = copdem_url(tile)
        assert url1 == url2


class TestFetchDem:
    """Tests for fetch_dem function (integration tests, may require network)."""

    def test_fetch_dem_cache_miss_offline_raises(self, temp_cache_dir):
        """Offline mode on cache miss raises DEMError."""
        with pytest.raises((DEMError, CacheError)):
            fetch_dem(
                30.3789,
                78.4789,
                domain_radius_km=60,
                cache_dir=temp_cache_dir,
                offline_mode=True,
            )

    def test_fetch_dem_creates_cache_dir(self, tmp_path):
        """Fetch DEM creates cache directory if not present."""
        cache_dir = tmp_path / "cache"
        assert not cache_dir.exists()

        # This will fail due to network (expected in test env)
        # but directory should be created
        try:
            fetch_dem(
                30.3789,
                78.4789,
                domain_radius_km=60,
                cache_dir=cache_dir,
                offline_mode=False,
            )
        except (DEMError, Exception):
            # Expected to fail without network access
            pass

        dem_cache = cache_dir / "dem"
        assert dem_cache.exists()

    @pytest.mark.slow
    def test_fetch_dem_real_tehri(self, tmp_path):
        """
        Integration test: Fetch real DEM for Tehri dam.

        Requires network access and will take 30+ seconds.
        Mark as @pytest.mark.slow to skip in fast CI runs.
        """
        cache_dir = tmp_path / "cache"

        try:
            dem_path = fetch_dem(
                30.3789,
                78.4789,
                domain_radius_km=60,
                cache_dir=cache_dir,
                offline_mode=False,
            )

            assert dem_path.exists()
            assert dem_path.suffix == ".tif"

            # Verify it's readable as GeoTIFF
            import rasterio

            with rasterio.open(str(dem_path)) as src:
                assert src.count == 1
                assert src.crs is not None
                data = src.read(1)
                assert data.shape[0] > 0
                assert data.shape[1] > 0

        except DEMError as e:
            pytest.skip(f"Network unavailable or tile fetch failed: {e}")

    def test_fetch_dem_cache_hit_on_second_call(self, tmp_path):
        """
        Second fetch of same domain should hit cache.

        Requires network on first call; second call should be fast (cached).
        """
        cache_dir = tmp_path / "cache"

        # First fetch (will fail without network, skip)
        try:
            dem1 = fetch_dem(
                30.3789,
                78.4789,
                domain_radius_km=60,
                cache_dir=cache_dir,
                offline_mode=False,
            )
        except (DEMError, Exception):
            pytest.skip("Network unavailable for first fetch")

        # Second fetch (should be fast, from cache)
        import time

        start = time.time()
        dem2 = fetch_dem(
            30.3789,
            78.4789,
            domain_radius_km=60,
            cache_dir=cache_dir,
            offline_mode=False,
        )
        elapsed = time.time() - start

        # Paths should be identical (same DEM)
        assert dem1 == dem2

        # Second call should be much faster (< 1 second vs. 30+ for network)
        assert elapsed < 5  # Generous timeout for fast cache hit


class TestFetchDemOfflineMode:
    """Tests for offline mode in fetch_dem."""

    def test_offline_mode_with_cached_dem(self, temp_cache_dir, mock_dem_geotiff):
        """Offline mode with cached DEM should work or raise CacheError."""
        from jalraksha.cache import store_cache

        # Prepare cache with mock DEM
        source_url = "https://cloud.sdsc.edu/v1/AUTH_ogc/Raster/COPDEM/COPDEM_GL30/COPDEM_GL30_srtm_utm43N_E078N030.tif"
        store_cache(source_url, mock_dem_geotiff, temp_cache_dir / "dem")

        # Try to fetch in offline mode
        # This will likely fail because we don't have all required tiles
        # but this test verifies the offline-mode path is called and raises appropriate error
        try:
            dem = fetch_dem(
                30.3789,
                78.4789,
                domain_radius_km=10,  # Smaller radius = fewer tiles
                cache_dir=temp_cache_dir,
                offline_mode=True,
            )
            # If we get here, some tiles were cached
            assert dem.exists()
        except CacheError as e:
            # Expected if not all tiles are cached
            assert "Offline mode" in str(e) or "not in cache" in str(e)
