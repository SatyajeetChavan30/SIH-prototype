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
        # dam_id was added after this pin was written: it carries the registry
        # key into define_downstream_gauges so a run reports arrival times at
        # its OWN downstream towns. It is a new key, not a changed value —
        # every solver input below is unchanged.
        "dam_id": "tehri",
        # Also added after this pin was written. Emitted so every caller gets
        # the DEM-backed extent, not just the HTTP layer — a library-side caller
        # previously ran with no domain cap at all.
        "domain_radius_km": 60.0,
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


def test_khadakwasla_to_dam_config_now_succeeds():
    """
    INVERTED 2026-08-28. This test previously asserted that to_dam_config()
    RAISES, because height_m/storage_mm3/dam_type were None for want of a
    primary source. They are now filled in (user-supplied, still tagged
    UNVETTED in the source), so the solver path is open and the old assertion
    would be asserting a bug.

    The guard itself is NOT weakened — see the two tests below: the loud-failure
    machinery is still exercised, and the UNVETTED tag is still pinned.
    """
    config = KHADAKWASLA.to_dam_config()
    # Revised from the first pass (51.3 m / 33.5 MCM): 51.3 m was a 1961
    # PLANNED stage never attained, and 33.5 MCM was partial live storage
    # where the regressions need gross. 39.6 m is above deepest foundation
    # (NRLD convention); 85.31 MCM is gross (live 55.91 + dead).
    assert config["height_m"] == pytest.approx(39.6)
    assert config["storage_mm3"] == pytest.approx(85.31)
    # "masonry" is not a valid dam_type in hardening.py; a masonry gravity dam
    # is recorded as "gravity".
    assert config["dam_type"] == "gravity"
    # dam_id must travel with the config, or define_downstream_gauges() cannot
    # find this dam's corridor and silently falls back to reporting no gauges.
    assert config["dam_id"] == "khadakwasla"


def test_to_dam_config_still_raises_when_a_solver_field_is_unknown():
    """
    The loud-failure path is the reason these fields are Optional at all. It
    must keep working for the next preset added without a vetted source, so
    exercise it directly rather than relying on Khadakwasla to stay unvetted.
    """
    import dataclasses

    unvetted = dataclasses.replace(KHADAKWASLA, height_m=None, storage_mm3=None)
    with pytest.raises(PresetError, match="height_m"):
        unvetted.to_dam_config()


def test_khadakwasla_structural_figures_are_still_marked_unvetted():
    """
    51.3 m / 33.5 MCM / gravity are user-supplied. No primary CWC, NRLD or
    Maharashtra WRD citation was obtained, and the sources that were offered
    came via India-WRIS, which CLAUDE.md forbids.

    Numbers that look vetted because nothing says otherwise are exactly what
    CLAUDE.md's unvetted-coefficient rule exists to prevent, so pin the tag to
    the source. Delete this test only together with the tag, and only when a
    primary register entry is actually in hand.
    """
    import inspect

    import jalraksha.presets as presets

    source = inspect.getsource(presets)
    khadakwasla_block = source[source.index("KHADAKWASLA = DamPreset("):]
    khadakwasla_block = khadakwasla_block[: khadakwasla_block.index("height_m=39.6")]
    assert "UNVETTED" in khadakwasla_block


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


def test_khadakwasla_demo_dam_entry_publishes_the_solver_fields():
    """
    INVERTED 2026-08-28, deliberately, as the old test asked: this previously
    asserted all three were null. They are now user-supplied values, still
    tagged UNVETTED in the preset source (pinned separately by
    test_khadakwasla_structural_figures_are_still_marked_unvetted).

    Pinned against the preset rather than against literals, so the API and the
    library cannot drift apart on figures this sensitive.
    """
    entry = _demo_dams()["khadakwasla"]
    assert entry["height_m"] == KHADAKWASLA.height_m == pytest.approx(39.6)
    assert entry["storage_mm3"] == KHADAKWASLA.storage_mm3 == pytest.approx(85.31)
    assert entry["dam_type"] == KHADAKWASLA.dam_type == "gravity"


def test_demo_dam_entries_publish_their_own_gauge_corridor():
    """
    GET /dams carries each dam's downstream towns so the dashboard can draw the
    right ones on selection. An empty list is meaningful and must stay empty:
    bhakra/idukki/hirakud have no surveyed corridor, and filling them with
    Tehri's towns is precisely what the old duplicated gauge lists did.
    """
    from jalraksha.presets import get_gauges

    dams = _demo_dams()
    assert len(dams["khadakwasla"]["gauges"]) == len(get_gauges("khadakwasla")) == 7
    assert len(dams["tehri"]["gauges"]) == 4
    for dam_id in ("bhakra", "idukki", "hirakud"):
        assert dams[dam_id]["gauges"] == [], dam_id


def test_tehri_demo_dam_entry_still_agrees_with_the_preset():
    """Tehri's entry is hand-written; this catches it drifting from the preset."""
    entry = _demo_dams()["tehri"]
    for field in ("lat", "lon", "height_m", "storage_mm3", "dam_type"):
        assert entry[field] == getattr(TEHRI, field), f"{field} drifted"


# ─── Downstream gauge corridors ────────────────────────────────────────────
# These used to be six hardcoded copies of the Tehri corridor, applied to every
# dam. A Khadakwasla run therefore reported arrival times at Himalayan towns
# ~1,500 km outside its own domain.


def test_tehri_corridor_survived_the_move_from_run_py():
    """
    The four Tehri gauges moved out of jalraksha/run.py into the registry.
    run.py's own comment records that these coordinates were previously wrong
    enough that the flood never reached Koteshwar, so pin them exactly: a typo
    during the move would silently reintroduce that bug.
    """
    from jalraksha.presets import get_gauges

    gauges = {g.name: g for g in get_gauges("tehri")}
    assert list(gauges) == ["Koteshwar", "Devprayag", "Rishikesh", "Haridwar"]
    assert gauges["Koteshwar"].lat == pytest.approx(30.3167)
    assert gauges["Koteshwar"].lon == pytest.approx(78.4833)
    assert gauges["Haridwar"].distance_km == pytest.approx(58.4)


def test_khadakwasla_corridor_is_the_pune_towns_ordered_by_distance():
    from jalraksha.presets import get_gauges

    gauges = get_gauges("khadakwasla")
    assert len(gauges) == 7
    assert [g.name for g in gauges][:2] == ["Deccan Gymkhana", "Swargate"]
    # Ordered ascending so the dashboard table reads down the corridor.
    distances = [g.distance_km for g in gauges]
    assert distances == sorted(distances)
    # Not the Tehri corridor, which is the failure this registry exists to stop.
    assert "Koteshwar" not in {g.name for g in gauges}


def _great_circle_km(lat1, lon1, lat2, lon2):
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def test_khadakwasla_declared_distances_match_the_great_circle():
    """This corridor declares STRAIGHT-LINE distances, so they must be exact."""
    from jalraksha.presets import get_gauges

    for gauge in get_gauges("khadakwasla"):
        actual = _great_circle_km(
            KHADAKWASLA.lat, KHADAKWASLA.lon, gauge.lat, gauge.lon
        )
        assert actual == pytest.approx(gauge.distance_km, abs=0.2), gauge.name


def test_mula_mutha_corridor_is_inside_the_domain_and_baramati_is_not():
    """
    The six Mula-Mutha gauges must be solvable; Baramati knowingly is not.

    Pinning the split rather than "all gauges are inside" on purpose. The
    domain was briefly widened to 100 km to swallow Baramati, which pushed the
    grid far outside the cached DEM and left build_domain filling 92% of cells
    with interpolated NoData — water propagating over invented terrain. A gauge
    correctly reported as out-of-domain is worth more than one brought in-domain
    over fill.
    """
    from jalraksha.presets import get_gauges

    inside, outside = [], []
    for gauge in get_gauges("khadakwasla"):
        d = _great_circle_km(KHADAKWASLA.lat, KHADAKWASLA.lon, gauge.lat, gauge.lon)
        (inside if d <= KHADAKWASLA.domain_radius_km else outside).append(gauge.name)

    assert len(inside) == 6
    assert outside == ["Baramati"]


def test_domain_radius_does_not_exceed_the_cached_dem():
    """
    The guard that would have caught the 92%-NoData run.

    A domain larger than its DEM does not fail — build_domain fills the gap and
    the solver happily runs on it — so nothing downstream notices. Assert the
    relationship directly instead. Skipped when the DEM is not staged, since
    that is a cache state, not a code defect.
    """
    import pathlib

    import rasterio

    dem = pathlib.Path("data/dem") / KHADAKWASLA.dem_filename()
    if not dem.exists():
        pytest.skip(f"{dem} not cached")

    with rasterio.open(dem) as src:
        bounds = src.bounds
    # The clip is stored in degrees; convert to km at this latitude.
    import math

    width_km = (bounds.right - bounds.left) * 111.32 * math.cos(
        math.radians(KHADAKWASLA.lat)
    )
    height_km = (bounds.top - bounds.bottom) * 110.57
    usable_radius_km = min(width_km, height_km) / 2.0

    assert KHADAKWASLA.domain_radius_km <= usable_radius_km, (
        f"domain_radius_km={KHADAKWASLA.domain_radius_km} exceeds the cached "
        f"DEM's usable radius of {usable_radius_km:.0f} km — the solver would "
        f"run on interpolated fill. Fetch a larger DEM before widening."
    )


def test_baramati_carries_its_off_corridor_caveat():
    """
    Baramati sits on the Karha/Nira, not the Mula-Mutha that carries this dam's
    flood. It is inside the domain, so a null arrival there is a correct result
    rather than a domain-extent artifact — and that distinction only reaches a
    reader if the note travels with the gauge.
    """
    from jalraksha.presets import get_gauges

    baramati = next(g for g in get_gauges("khadakwasla") if g.name == "Baramati")
    assert baramati.note and "OFF-CORRIDOR" in baramati.note


def test_get_gauges_returns_empty_rather_than_another_dams_towns():
    from jalraksha.presets import get_gauges

    assert get_gauges("bhakra") == ()
    assert get_gauges(None) == ()


def test_khadakwasla_surface_area_reaches_the_storage_curve():
    """
    The whole point of carrying surface_area_km2: without it
    reservoir_storage_curve falls back to storage_exponent=3.0, a cone, and
    Khadakwasla is a broad shallow pool (mean depth 5.8 m over 14.72 km2).
    b sets the drawdown rate, and therefore the routed peak and the recession
    limb, so silently reverting to a cone here would be a quiet 2x error in
    reservoir shape that nothing else would catch.
    """
    from jalraksha.terrain.breach import reservoir_storage_curve

    config = KHADAKWASLA.to_dam_config()
    assert config["surface_area_km2"] == pytest.approx(14.72)

    _k, exponent = reservoir_storage_curve(
        config["storage_mm3"], config["height_m"], config["surface_area_km2"]
    )
    assert exponent == pytest.approx(6.83, abs=0.05)
    # The value it would have used with the area unknown.
    _k, cone = reservoir_storage_curve(config["storage_mm3"], config["height_m"])
    assert cone == pytest.approx(3.0)


def test_khadakwasla_frl_is_still_derived_from_the_dem():
    """
    No published FRL exists for this dam. The sourced review offers ~585 m MSL
    but that is its own DEM estimate, and it contradicts itself with local
    gauge readings of ~508-512 m. estimate_pool_surface_m measures the pool
    at runtime (this repository read 580.0 m), so a literal here would replace
    a measurement with a guess.
    """
    assert KHADAKWASLA.frl_m is None
    assert "UNVETTED" in KHADAKWASLA.frl_source
