"""
Data cache management for JalRaksha.

Phase 0 responsibility: Offline-first design — fetch data once, cache locally, all reads from cache.
Cache versioning by (source_url, timestamp, md5_hash).
Metadata stored in JSON format for transparency.

Contract:
  - After first fetch, all data reads from cache (no network calls in solver/export)
  - Cache miss → fetch from source, store locally with metadata, return path
  - Cache hit → return cached path
  - Offline mode: read from cache only, fail if not present

Implementation:
  - check_cache(source_url, cache_dir) → (hit: bool, cached_path: Path)
  - store_cache(source_url, source_data, cache_dir, metadata) → (cache_path: Path, metadata_path: Path)
  - clear_cache(cache_dir) → None
  - get_cache_metadata(cache_dir) → {source_url: {timestamp, hash, path}}
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from datetime import datetime


class CacheError(Exception):
    """Raised when cache operations fail."""

    pass


def _compute_hash(data: bytes, algorithm: str = "md5") -> str:
    """Compute hash digest of binary data."""
    hasher = hashlib.new(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def check_cache(
    source_url: str, cache_dir: Path, offline_mode: bool = False
) -> Tuple[bool, Optional[Path]]:
    """
    Check if data is cached locally.

    Args:
        source_url: Remote source URL (e.g., Copernicus DEM COG URL)
        cache_dir: Local cache directory
        offline_mode: If True, only return cache hit (no fetch on miss)

    Returns:
        (hit: bool, cached_path: Path or None)
        If hit=True, cached_path is the local file path.
        If hit=False and offline_mode=False, return (False, None) to signal fetch needed.
        If hit=False and offline_mode=True, raise CacheError (offline, no cache).

    Raises:
        CacheError: If offline_mode=True and cache miss occurs
    """
    cache_dir = Path(cache_dir)
    metadata_path = cache_dir / "CACHE_METADATA.json"

    if not metadata_path.exists():
        if offline_mode:
            raise CacheError(f"Offline mode: no cache metadata at {metadata_path}")
        return (False, None)

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        if offline_mode:
            raise CacheError(f"Offline mode: cannot read cache metadata: {e}")
        return (False, None)

    if source_url not in metadata:
        if offline_mode:
            raise CacheError(
                f"Offline mode: source {source_url} not in cache. Available: {list(metadata.keys())}"
            )
        return (False, None)

    cached_entry = metadata[source_url]
    cached_path = Path(cached_entry["path"])

    if not cached_path.exists():
        if offline_mode:
            raise CacheError(f"Offline mode: cached file missing at {cached_path}")
        # Cache entry stale; signal re-fetch
        return (False, None)

    # Verify hash if available
    if "hash" in cached_entry and cached_entry["hash"]:
        try:
            with open(cached_path, "rb") as f:
                data_hash = _compute_hash(f.read())
            if data_hash != cached_entry["hash"]:
                print(
                    f"⚠ Cache hash mismatch for {source_url}: "
                    f"expected {cached_entry['hash']}, got {data_hash}. Re-fetching."
                )
                if offline_mode:
                    raise CacheError(f"Offline mode: cache hash mismatch, cannot re-fetch")
                return (False, None)
        except IOError as e:
            if offline_mode:
                raise CacheError(f"Offline mode: cannot verify cache hash: {e}")
            return (False, None)

    print(
        f"[OK] Cache hit: {source_url}\n"
        f"  Timestamp: {cached_entry.get('timestamp', 'unknown')}\n"
        f"  Path: {cached_path}"
    )
    return (True, cached_path)


def store_cache(
    source_url: str,
    cached_file_path: Path,
    cache_dir: Path,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, Path]:
    """
    Register a cached file in metadata.

    Args:
        source_url: Remote source URL
        cached_file_path: Local path where file is stored (should already exist)
        cache_dir: Cache root directory
        metadata: Optional extra metadata (e.g., {"format": "GeoTIFF", "crs": "EPSG:32643"})

    Returns:
        (cache_path: Path, metadata_path: Path)

    Raises:
        CacheError: If cached_file_path does not exist
    """
    cached_file_path = Path(cached_file_path)
    cache_dir = Path(cache_dir)

    if not cached_file_path.exists():
        raise CacheError(f"Cached file does not exist: {cached_file_path}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = cache_dir / "CACHE_METADATA.json"

    # Load existing metadata
    if metadata_path.exists():
        try:
            with open(metadata_path, "r") as f:
                cache_metadata = json.load(f)
        except json.JSONDecodeError:
            cache_metadata = {}
    else:
        cache_metadata = {}

    # Compute file hash
    with open(cached_file_path, "rb") as f:
        file_data = f.read()
    file_hash = _compute_hash(file_data)

    # Record entry
    cache_metadata[source_url] = {
        "path": str(cached_file_path),
        "timestamp": datetime.utcnow().isoformat(),
        "hash": file_hash,
        "size_bytes": len(file_data),
        "source_url": source_url,
        **(metadata or {}),
    }

    # Write metadata
    with open(metadata_path, "w") as f:
        json.dump(cache_metadata, f, indent=2)

    print(
        f"[OK] Cached: {source_url}\n"
        f"  Path: {cached_file_path}\n"
        f"  Hash: {file_hash}\n"
        f"  Size: {len(file_data) / 1e6:.1f} MB"
    )
    return (cached_file_path, metadata_path)


def clear_cache(cache_dir: Path) -> None:
    """
    Clear all cached data.

    Args:
        cache_dir: Cache root directory

    Raises:
        CacheError: If directory cannot be removed
    """
    cache_dir = Path(cache_dir)

    if not cache_dir.exists():
        print(f"Cache directory does not exist: {cache_dir}")
        return

    try:
        import shutil

        shutil.rmtree(cache_dir)
        print(f"[OK] Cache cleared: {cache_dir}")
    except Exception as e:
        raise CacheError(f"Failed to clear cache: {e}")


def get_cache_metadata(cache_dir: Path) -> Dict[str, Any]:
    """
    Retrieve all cache metadata.

    Args:
        cache_dir: Cache root directory

    Returns:
        Dictionary mapping source_url → {path, timestamp, hash, size_bytes, ...}

    Raises:
        CacheError: If metadata cannot be read
    """
    cache_dir = Path(cache_dir)
    metadata_path = cache_dir / "CACHE_METADATA.json"

    if not metadata_path.exists():
        return {}

    try:
        with open(metadata_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise CacheError(f"Cannot parse cache metadata: {e}")


def list_cache(cache_dir: Path) -> None:
    """
    Print cache contents in human-readable format.

    Args:
        cache_dir: Cache root directory
    """
    metadata = get_cache_metadata(cache_dir)

    if not metadata:
        print(f"Cache is empty: {cache_dir}")
        return

    print(f"\nCache contents ({cache_dir}):")
    print(f"{'─' * 80}")
    for source_url, entry in metadata.items():
        print(f"URL: {source_url}")
        print(f"  Path: {entry.get('path', 'unknown')}")
        print(f"  Timestamp: {entry.get('timestamp', 'unknown')}")
        print(f"  Hash (MD5): {entry.get('hash', 'unknown')}")
        print(f"  Size: {entry.get('size_bytes', 0) / 1e6:.1f} MB")
        if "format" in entry:
            print(f"  Format: {entry['format']}")
        print()
