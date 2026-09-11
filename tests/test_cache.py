"""
Unit tests for jalraksha.cache module.

Tests:
- Cache miss/hit logic
- Hash verification
- Offline mode enforcement
- Metadata read/write
- Cache listing
"""

import pytest
from pathlib import Path
import json

from jalraksha.cache import (
    check_cache,
    store_cache,
    clear_cache,
    get_cache_metadata,
    list_cache,
    CacheError,
)


class TestCheckCache:
    """Tests for check_cache function."""

    def test_cache_miss_empty_dir(self, temp_cache_dir):
        """Check cache on empty directory returns miss."""
        hit, path = check_cache("https://example.com/data.tif", temp_cache_dir)
        assert hit is False
        assert path is None

    def test_cache_miss_offline_mode_raises(self, temp_cache_dir):
        """Offline mode on cache miss raises CacheError."""
        with pytest.raises(CacheError, match="Offline mode"):
            check_cache("https://example.com/data.tif", temp_cache_dir, offline_mode=True)

    def test_cache_hit_with_metadata(self, temp_cache_dir, mock_dem_geotiff):
        """Check cache with valid metadata returns hit."""
        source_url = "https://example.com/dem.tif"

        # Store cache entry
        store_cache(source_url, mock_dem_geotiff, temp_cache_dir)

        # Check cache
        hit, path = check_cache(source_url, temp_cache_dir)
        assert hit is True
        assert path == mock_dem_geotiff

    def test_cache_hit_offline_mode(self, temp_cache_dir, mock_dem_geotiff):
        """Offline mode on cache hit succeeds."""
        source_url = "https://example.com/dem.tif"
        store_cache(source_url, mock_dem_geotiff, temp_cache_dir)

        hit, path = check_cache(source_url, temp_cache_dir, offline_mode=True)
        assert hit is True
        assert path == mock_dem_geotiff

    def test_cache_hit_missing_file_signals_refetch(self, temp_cache_dir):
        """Cache hit with missing file signals re-fetch."""
        source_url = "https://example.com/dem.tif"
        nonexistent_path = temp_cache_dir / "dem" / "missing.tif"

        # Manually create metadata pointing to missing file
        metadata = {
            source_url: {
                "path": str(nonexistent_path),
                "timestamp": "2026-08-24T00:00:00",
                "hash": "abc123",
            }
        }
        metadata_path = temp_cache_dir / "CACHE_METADATA.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        hit, path = check_cache(source_url, temp_cache_dir, offline_mode=False)
        assert hit is False

    def test_cache_hit_hash_mismatch_signals_refetch(self, temp_cache_dir, mock_dem_geotiff):
        """Cache hit with hash mismatch signals re-fetch (and warns)."""
        source_url = "https://example.com/dem.tif"

        # Store cache entry
        store_cache(source_url, mock_dem_geotiff, temp_cache_dir)

        # Corrupt metadata hash
        metadata_path = temp_cache_dir / "CACHE_METADATA.json"
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        metadata[source_url]["hash"] = "corrupted_hash_value"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        hit, path = check_cache(source_url, temp_cache_dir, offline_mode=False)
        assert hit is False


class TestStoreCache:
    """Tests for store_cache function."""

    def test_store_cache_creates_metadata(self, temp_cache_dir, mock_dem_geotiff):
        """Store cache creates metadata entry."""
        source_url = "https://example.com/dem.tif"
        cache_path, metadata_path = store_cache(source_url, mock_dem_geotiff, temp_cache_dir)

        assert cache_path == mock_dem_geotiff
        assert metadata_path.exists()

        metadata = get_cache_metadata(temp_cache_dir)
        assert source_url in metadata
        assert metadata[source_url]["path"] == str(mock_dem_geotiff)
        assert "hash" in metadata[source_url]
        assert "timestamp" in metadata[source_url]
        assert "size_bytes" in metadata[source_url]

    def test_store_cache_nonexistent_file_raises(self, temp_cache_dir):
        """Store cache with nonexistent file raises CacheError."""
        nonexistent = temp_cache_dir / "nonexistent.tif"
        with pytest.raises(CacheError, match="does not exist"):
            store_cache("https://example.com/data.tif", nonexistent, temp_cache_dir)

    def test_store_cache_multiple_entries(self, temp_cache_dir, mock_dem_geotiff):
        """Store cache appends multiple entries to metadata."""
        url1 = "https://example.com/dem1.tif"
        url2 = "https://example.com/dem2.tif"

        # Duplicate mock file for second entry
        mock2 = temp_cache_dir / "mock2.tif"
        mock2.write_bytes(mock_dem_geotiff.read_bytes())

        store_cache(url1, mock_dem_geotiff, temp_cache_dir)
        store_cache(url2, mock2, temp_cache_dir)

        metadata = get_cache_metadata(temp_cache_dir)
        assert url1 in metadata
        assert url2 in metadata

    def test_store_cache_with_extra_metadata(self, temp_cache_dir, mock_dem_geotiff):
        """Store cache with extra metadata fields."""
        source_url = "https://example.com/dem.tif"
        extra = {"format": "GeoTIFF", "crs": "EPSG:32643", "tile": "N030E078"}

        store_cache(source_url, mock_dem_geotiff, temp_cache_dir, metadata=extra)

        cached_metadata = get_cache_metadata(temp_cache_dir)
        for key, val in extra.items():
            assert cached_metadata[source_url][key] == val


class TestClearCache:
    """Tests for clear_cache function."""

    def test_clear_cache_removes_directory(self, temp_cache_dir, mock_dem_geotiff):
        """Clear cache removes entire directory."""
        source_url = "https://example.com/dem.tif"
        store_cache(source_url, mock_dem_geotiff, temp_cache_dir)

        assert temp_cache_dir.exists()
        clear_cache(temp_cache_dir)
        assert not temp_cache_dir.exists()

    def test_clear_cache_nonexistent_dir(self, tmp_path):
        """Clear cache on nonexistent directory does not raise."""
        nonexistent = tmp_path / "nonexistent_cache"
        # Should not raise
        clear_cache(nonexistent)


class TestGetCacheMetadata:
    """Tests for get_cache_metadata function."""

    def test_get_cache_metadata_empty_dir(self, temp_cache_dir):
        """Get metadata on empty directory returns empty dict."""
        metadata = get_cache_metadata(temp_cache_dir)
        assert metadata == {}

    def test_get_cache_metadata_retrieves_entries(self, temp_cache_dir, mock_dem_geotiff):
        """Get metadata retrieves all cached entries."""
        url1 = "https://example.com/dem1.tif"
        url2 = "https://example.com/dem2.tif"

        mock2 = temp_cache_dir / "mock2.tif"
        mock2.write_bytes(mock_dem_geotiff.read_bytes())

        store_cache(url1, mock_dem_geotiff, temp_cache_dir)
        store_cache(url2, mock2, temp_cache_dir)

        metadata = get_cache_metadata(temp_cache_dir)
        assert len(metadata) == 2
        assert url1 in metadata
        assert url2 in metadata

    def test_get_cache_metadata_corrupt_file_raises(self, temp_cache_dir):
        """Get metadata with corrupt JSON raises CacheError."""
        metadata_path = temp_cache_dir / "CACHE_METADATA.json"
        metadata_path.write_text("{ invalid json")

        with pytest.raises(CacheError, match="Cannot parse"):
            get_cache_metadata(temp_cache_dir)


class TestListCache:
    """Tests for list_cache function."""

    def test_list_cache_empty(self, temp_cache_dir, capsys):
        """List cache on empty directory prints message."""
        list_cache(temp_cache_dir)
        captured = capsys.readouterr()
        assert "empty" in captured.out.lower()

    def test_list_cache_populated(self, temp_cache_dir, mock_dem_geotiff, capsys):
        """List cache prints entries."""
        source_url = "https://example.com/dem.tif"
        store_cache(source_url, mock_dem_geotiff, temp_cache_dir)

        list_cache(temp_cache_dir)
        captured = capsys.readouterr()
        assert source_url in captured.out
        assert "Path:" in captured.out
        assert "Hash" in captured.out
