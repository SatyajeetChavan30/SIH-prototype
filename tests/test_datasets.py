"""
The dataset catalogue lists what is on disk, and only that.

The failure this guards against is a data-centre screen that reads as an
inventory while describing intentions: a row for a dataset the system *would*
fetch is worse than no row, because it is exactly the question an operator asks
before going offline.

The other two rules here are licence rules. A path naming a source this project
must not redistribute (FABDEM, MERIT, OSM) is flagged rather than listed
quietly, and a raster written before the Earth Engine aggregation fix is
labelled superseded rather than deleted — it is still on disk, and runs that
used it are still in the database.

Offline by construction: a temp DATA_DIR, no fetch, no network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

pytest.importorskip("jalraksha_service", reason="API service not importable")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    from jalraksha_service import datasets
    from jalraksha_service.config import settings

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", root, raising=False)
    # The engine probes glob Program Files; this suite is about files on disk.
    monkeypatch.setattr(datasets, "engine_rows", lambda: [])
    return root


def _rows(**kwargs):
    from jalraksha_service.datasets import dataset_rows

    return dataset_rows(**kwargs)


def _write(path: Path, content: bytes = b"tif") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestWhatIsListed:
    def test_an_empty_data_directory_lists_nothing(self, data_dir):
        payload = _rows(start_hashing=False)
        assert payload["rows"] == []
        assert payload["total_bytes"] == 0

    def test_only_files_that_exist_appear(self, data_dir):
        _write(data_dir / "dem" / "dem_18.44_73.77_clipped.tif")
        paths = [row["path"] for row in _rows(start_hashing=False)["rows"]]
        assert paths == ["dem/dem_18.44_73.77_clipped.tif"]

    def test_a_dem_tile_is_labelled_as_a_window_not_a_tile(self, data_dir):
        _write(data_dir / "dem" / "Copernicus_DSM_COG_10_N18_00_E073_00_DEM.tif")
        row = _rows(start_hashing=False)["rows"][0]
        assert "WINDOW" in row["note"]
        assert row["licence"].startswith("Copernicus")

    def test_an_updated_dem_says_it_is_not_a_survey(self, data_dir):
        _write(data_dir / "dem" / "updated" / "dem_30.52_79.61_obscond.tif")
        row = _rows(start_hashing=False)["rows"][0]
        assert row["family"] == "dem_updated"
        assert "NOT A SURVEY" in row["product"]

    def test_sizes_and_times_are_the_files_own(self, data_dir):
        path = _write(data_dir / "dem" / "mosaic_18.44_73.77.tif", b"x" * 1234)
        row = _rows(start_hashing=False)["rows"][0]
        assert row["bytes"] == 1234 == path.stat().st_size
        assert row["modified_at"]


class TestLicences:
    def test_a_forbidden_source_is_flagged(self, data_dir):
        _write(data_dir / "dem" / "merit_hydro_patch.tif")
        row = _rows(start_hashing=False)["rows"][0]
        assert row["redistribution"] == "forbidden"
        assert "merit" in row["redistribution_reason"]

    def test_an_approved_source_is_not_flagged(self, data_dir):
        _write(data_dir / "dem" / "dem_18.44_73.77_clipped.tif")
        assert _rows(start_hashing=False)["rows"][0]["redistribution"] == "approved"


class TestSuperseded:
    def _ghsl_dir(self, data_dir, name="epsg32643_100_200_10x10"):
        return data_dir / "gee" / "ghsl" / name

    def test_a_v1_only_directory_is_superseded(self, data_dir):
        directory = self._ghsl_dir(data_dir)
        _write(directory / "ghsl_pop_2020_epsg32643.tif")
        (directory / "ghsl_manifest.json").write_text(json.dumps({"aggregation": "sum"}))
        row = _rows(start_hashing=False)["rows"][0]
        assert row["superseded"] is True
        assert "row 37" in row["note"]

    def test_a_v2_raster_is_not_superseded(self, data_dir):
        directory = self._ghsl_dir(data_dir)
        _write(directory / "ghsl_pop_2020_epsg32643_areacorrected.tif")
        (directory / "ghsl_manifest_v2.json").write_text(
            json.dumps({"aggregation": "density", "fetched_at": "2026-09-07T00:00:00Z"}))
        row = _rows(start_hashing=False)["rows"][0]
        assert row["superseded"] is False
        assert row["fetched_at"] == "2026-09-07T00:00:00Z"

    def test_the_old_raster_beside_a_new_one_is_still_labelled(self, data_dir):
        """Both files stay on disk; only the pre-fix one carries the warning."""
        directory = self._ghsl_dir(data_dir)
        _write(directory / "ghsl_pop_2020_epsg32643.tif")
        _write(directory / "ghsl_pop_2020_epsg32643_areacorrected.tif")
        (directory / "ghsl_manifest.json").write_text(json.dumps({}))
        (directory / "ghsl_manifest_v2.json").write_text(json.dumps({}))
        rows = {Path(row["path"]).name: row for row in _rows(start_hashing=False)["rows"]}
        assert rows["ghsl_pop_2020_epsg32643.tif"]["superseded"] is True
        assert rows["ghsl_pop_2020_epsg32643_areacorrected.tif"]["superseded"] is False


class TestHashing:
    def test_the_catalogue_answers_before_hashing_finishes(self, data_dir):
        _write(data_dir / "dem" / "dem_18.44_73.77_clipped.tif", b"y" * 4096)
        payload = _rows(start_hashing=False)
        assert payload["rows"][0]["sha256"] is None
        assert payload["hashing"]["pending"] == 1

    def test_a_cached_hash_is_served_and_matches_the_file(self, data_dir):
        import hashlib

        from jalraksha_service import datasets

        content = b"z" * 2048
        path = _write(data_dir / "dem" / "dem_18.44_73.77_clipped.tif", content)
        datasets._hash_missing([path])
        row = _rows(start_hashing=False)["rows"][0]
        assert row["sha256"] == hashlib.sha256(content).hexdigest()

    def test_the_cache_is_keyed_so_a_changed_file_is_rehashed(self, data_dir):
        from jalraksha_service import datasets

        path = _write(data_dir / "dem" / "dem_18.44_73.77_clipped.tif", b"a" * 64)
        datasets._hash_missing([path])
        first = _rows(start_hashing=False)["rows"][0]["sha256"]

        path.write_bytes(b"b" * 128)  # different size, so a different cache key
        assert _rows(start_hashing=False)["rows"][0]["sha256"] is None
        datasets._hash_missing([path])
        assert _rows(start_hashing=False)["rows"][0]["sha256"] != first

    def test_progress_is_checkpointed_rather_than_written_once_at_the_end(
            self, data_dir, monkeypatch):
        """
        A pass over this machine's 2.8 GB takes ~25 s. Writing the cache only at
        the end meant any process that exited first - a CLI, a test, a restart -
        discarded every hash it had just computed, which is how the first
        version of this module measured "hashed 0" three times in a row.
        """
        from jalraksha_service import datasets

        paths = [_write(data_dir / "dem" / f"dem_{i}.tif", bytes([i]) * 32) for i in range(20)]
        monkeypatch.setattr(datasets, "_CHECKPOINT_EVERY", 4)

        writes = []
        real_store = datasets._store_hashes
        monkeypatch.setattr(datasets, "_store_hashes",
                            lambda hashes: (writes.append(len(hashes)), real_store(hashes))[1])

        datasets._hash_missing(paths)

        assert len(writes) >= 5, f"expected periodic checkpoints, saw {writes}"
        assert writes[0] <= 4, "the first checkpoint must land early, not at the end"
        cached = json.loads((data_dir / datasets.CACHE_PATH_NAME).read_text())
        assert len(cached) == 20

    def test_one_unreadable_file_does_not_stop_the_pass(self, data_dir, monkeypatch):
        from jalraksha_service import datasets

        good = _write(data_dir / "dem" / "good.tif", b"g" * 32)
        bad = _write(data_dir / "dem" / "bad.tif", b"b" * 32)
        real = datasets._sha256_file
        monkeypatch.setattr(
            datasets, "_sha256_file",
            lambda path: (_ for _ in ()).throw(OSError("locked")) if path == bad else real(path))

        datasets._hash_missing([bad, good])

        rows = {Path(r["path"]).name: r for r in _rows(start_hashing=False)["rows"]}
        assert rows["good.tif"]["sha256"] is not None
        assert rows["bad.tif"]["sha256"] is None
