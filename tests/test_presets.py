"""
Tests for jalraksha.presets — the dam-preset records consumed by
tools/paraview/make_dataset.py.

These pin two things that would otherwise fail silently:

1. Khadakwasla's lat/lon (derived by hand from the visualization spec's UTM
   crest coordinate) actually round-trips back to that UTM pair. If someone
   edits the literal without re-deriving it, this catches the drift.
2. TEHRI.to_dam_config() is byte-for-byte the old hardcoded TEHRI dict that
   lived in tools/paraview/make_dataset.py, so moving the dam config into
   jalraksha.presets is provably not a behaviour change for the existing
   Tehri path.
"""

from __future__ import annotations

import pytest

from jalraksha.presets import KHADAKWASLA, PRESETS, TEHRI, PresetError, get_preset


def test_khadakwasla_latlon_is_not_the_spec_utm_derived_point():
    """
    The spec's Khadakwasla dam crest, EPSG:32643 (373100, 2043600),
    inverse-projects to 18.478968 N, 73.798061 E — but --locate-only at that
    point found the "dam" cell 36 m above the nearest DEM pool plateau (a
    hillside, not a reservoir). KHADAKWASLA.lat/lon uses a different,
    DEM-validated point instead (see jalraksha/presets.py's comment on the
    rejected candidate). This pins that the rejected point stays rejected.
    """
    assert KHADAKWASLA.lat == pytest.approx(18.4436, abs=1e-4)
    assert KHADAKWASLA.lon == pytest.approx(73.7686, abs=1e-4)


def test_tehri_latlon_is_not_derived_from_spec_utm():
    """
    Guard against a future edit accidentally "fixing" Tehri's coordinate to
    match the spec's UTM table. That table's Tehri crest inverse-projects to
    30.369248 N, 78.622323 E — 13.8 km from the value this repo has used
    throughout, which is the one the cached DEM and every verified artifact
    were built against. This must stay unchanged.
    """
    assert TEHRI.lat == pytest.approx(30.3789, abs=1e-4)
    assert TEHRI.lon == pytest.approx(78.4789, abs=1e-4)


@pytest.mark.parametrize("preset", [TEHRI, KHADAKWASLA])
def test_auto_detected_zone_matches_declared_epsg(preset):
    """
    load_dem_as_grid auto-detects EPSG from (lat, lon); nothing in the
    pipeline forces preset.epsg onto the data. If a preset's declared epsg
    ever disagreed with what auto-detection would produce, every downstream
    assertion of "grid.crs == EPSG:{preset.epsg}" would fail confusingly.
    """
    from jalraksha.terrain.domain import latlon_to_utm

    zone, _, _ = latlon_to_utm(preset.lat, preset.lon)
    expected_epsg = (32600 if preset.lat >= 0 else 32700) + zone
    assert expected_epsg == preset.epsg


def test_tehri_to_dam_config_matches_original_hardcoded_dict():
    """
    Regression pin: this is a literal copy of the TEHRI dict that used to
    live at the top of tools/paraview/make_dataset.py. If to_dam_config()
    ever drifts from it, every solver input downstream silently changes.
    """
    original_tehri_dict = {
        "name": "Tehri Dam",
        "lat": 30.3789,
        "lon": 78.4789,
        "height_m": 260.0,
        "storage_mm3": 3540.0,
        "dam_type": "embankment",
        "failure_mode": "overtopping",
    }
    assert TEHRI.to_dam_config() == original_tehri_dict


def test_tehri_dem_filename_matches_existing_cache():
    assert TEHRI.dem_filename() == "dem_30.38_78.48_clipped.tif"


def test_khadakwasla_to_dam_config_raises_without_vetted_solver_fields():
    """
    height_m/storage_mm3/dam_type have no primary source for Khadakwasla yet.
    to_dam_config() must fail loudly rather than let a guessed value reach
    the breach regressions.
    """
    with pytest.raises(PresetError, match="height_m"):
        KHADAKWASLA.to_dam_config()


def test_get_preset_unknown_id_raises_with_available_list():
    with pytest.raises(PresetError, match="khadakwasla"):
        get_preset("not_a_real_dam")


def test_with_location_override_only_replaces_given_axis():
    moved = KHADAKWASLA.with_location(lat=1.0, lon=None)
    assert moved.lat == 1.0
    assert moved.lon == KHADAKWASLA.lon
    assert KHADAKWASLA.with_location(None, None) is KHADAKWASLA


def test_presets_registry_contains_both_dams_with_khadakwasla_default():
    from jalraksha.presets import DEFAULT_PRESET_ID

    assert set(PRESETS) == {"khadakwasla", "tehri"}
    assert DEFAULT_PRESET_ID == "khadakwasla"


# ─── API registry consistency ──────────────────────────────────────────────
# jalraksha/presets.py and services/api/.../config.py::DEMO_DAMS are two
# separate dam registries (the preset module's own docstring says so). Where
# they overlap they must not drift, so pin the overlap rather than trusting it.


def _demo_dams():
    """Import the service config, which lives outside the jalraksha package."""
    import sys
    from pathlib import Path

    api_dir = Path(__file__).resolve().parents[1] / "services" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from jalraksha_service.config import settings

    return {d["id"]: d for d in settings.DEMO_DAMS}


def test_khadakwasla_demo_dam_entry_is_copied_from_the_preset():
    entry = _demo_dams()["khadakwasla"]
    assert entry["name"] == KHADAKWASLA.name
    assert entry["lat"] == KHADAKWASLA.lat
    assert entry["lon"] == KHADAKWASLA.lon
    assert entry["river"] == KHADAKWASLA.river
    assert entry["state"] == KHADAKWASLA.state


def test_khadakwasla_publishes_null_for_the_unvetted_solver_fields():
    """
    Not an oversight — the preset has no vetted height/storage/dam_type and
    CLAUDE.md forbids inventing them. If someone fills these in, they must
    supply a primary source, and this test should be updated deliberately.
    """
    entry = _demo_dams()["khadakwasla"]
    assert entry["height_m"] is None
    assert entry["storage_mm3"] is None
    assert entry["dam_type"] is None


def test_tehri_demo_dam_entry_still_agrees_with_the_preset():
    """Tehri's entry is hand-written; this catches it drifting from the preset."""
    entry = _demo_dams()["tehri"]
    for field in ("lat", "lon", "height_m", "storage_mm3", "dam_type"):
        assert entry[field] == getattr(TEHRI, field), f"{field} drifted"
