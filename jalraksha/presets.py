"""
Dam presets — the single source of truth for which dam a run is about.

Phase 0: pure data. This module imports nothing from the rest of ``jalraksha``,
so it can be imported forward by Phase 2 (``terrain.domain``), Phase 4
(``run.py``), and by ``tools/`` without ever creating a cycle (see
Architecture Rule 2 in CLAUDE.md: phases build on earlier phases only).

Why this exists: before this module, ``tools/paraview/make_dataset.py`` carried
a module-level ``TEHRI = {...}`` dict used unconditionally at five call sites,
with no way to select a different dam. CLAUDE.md's Rule 5 (Configuration
Isolation) says configuration is data, not code, and every coefficient needs a
source citation — a hardcoded dict inside a CLI tool is exactly the violation
that rule exists to prevent.

NOTE on a separate, unrelated preset list: ``services/api/jalraksha_service/
config.py::DEMO_DAMS`` is a different list of dicts (tehri, bhakra, idukki)
bound to a live HTTP API and a pydantic ``DamPreset`` schema. It is NOT merged
with this module — it has zero consumers in ``paraview/`` or ``tools/
paraview/``, and unifying them here would risk the running service for no
benefit to the visualization pipeline. If they are ever unified, the service
should derive from this module (service -> library), never the reverse.

A CAUTIONARY NOTE ON COORDINATES: the visualization spec that motivated this
module gave Tehri's dam crest as UTM 44N (271500, 3362100). Projected back to
lat/lon that is 30.369248 N, 78.622323 E — 13.8 km from the coordinate this
repository has used throughout (30.3789 N, 78.4789 E), which is the one the
cached DEM, the downstream gauge geometry, and every verified artifact are
built on. TEHRI's lat/lon below is therefore deliberately NOT derived from
that spec table. Khadakwasla's coordinate below IS derived from its spec UTM
pair (there is no pre-existing repo value to defer to instead), so it carries
the same unknown error bar — see ``tools/paraview/make_dataset.py --locate-
only`` for the DEM-based sanity check before trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Optional, Tuple


class PresetError(Exception):
    """Raised when a preset is asked for data it does not have."""


@dataclass(frozen=True)
class DamPreset:
    """
    Everything a make_dataset.py run needs to know about one dam.

    The identity/solver fields below are exactly what ``build_domain()`` and
    ``run_dam_break_ensemble()`` read out of their ``dam_config`` argument —
    see ``to_dam_config()``. Nothing about call signatures changes; this
    dataclass only replaces where the values come from.
    """

    # --- identity / solver inputs -----------------------------------------
    dam_id: str
    name: str
    lat: float
    lon: float
    # Unknown for a preset without a vetted primary source: leave None. Any
    # code path that needs these (the breach regressions, via
    # to_dam_config()) must fail loudly rather than substitute a guess.
    height_m: Optional[float]
    storage_mm3: Optional[float]
    dam_type: Optional[str]
    failure_mode: str

    # --- domain -------------------------------------------------------------
    region: str  # human label, used in captions and provenance
    domain_radius_km: float
    epsg: int  # EXPECTED CRS. Asserted against the CRS load_dem_as_grid
               # auto-detects from (lat, lon); never used to force it.

    # --- static reservoir (Phase 3) ------------------------------------------
    # None => derive a fill level from the DEM's own impounded pool surface at
    # runtime (see tools/paraview/reservoir.py::estimate_pool_surface_m)
    # rather than inventing a published figure.
    frl_m: Optional[float]
    crest_m: Optional[float]
    frl_source: str  # provenance string — printed on every run, stored in
                      # the XDMF's provenance field data
    render_freeboard_m: float  # RENDERING parameter only, not hydrology:
                                # frl = pool_surface + render_freeboard_m
                                # when frl_m is None (see reservoir.py).
    barrier_freeboard_m: float  # crest = frl + barrier_freeboard_m when
                                 # crest_m is None.
    barrier_halfwidth_m: float  # how far the intact-dam barrier wall extends
                                 # either side of the dam, perpendicular to
                                 # flow. Must span the valley or the fill
                                 # leaks around the wall's ends.
    direction_search_radius_cells: Tuple[int, int]  # (min, max) radius, in
        # cells, that reservoir.py's _downhill_direction scans to find the
        # flow direction. (5, 12) — 500 m-1.2 km at 100 m resolution — is
        # right for a narrow gorge; a dam on broader terrain needs a wider
        # scan or the result is local micro-relief noise, not the valley
        # trend. See tools/paraview/reservoir.py::build_reservoir's docstring.

    # --- visualization defaults ----------------------------------------------
    # Consumed only by the printed render_static.py command; render_static.py
    # itself stays dam-agnostic and never imports this module.
    vertical_exaggeration: float
    nominal_depth_m: float  # --depth-max, the colour-ramp upper bound

    # --- descriptive labels ---------------------------------------------------
    # Split out of `region` rather than parsed from it. The API layer
    # (services/api/jalraksha_service/config.py) publishes river and state as
    # separate fields, and splitting "Mutha River Basin, Pune, Maharashtra" on
    # commas to recover them is brittle in exactly the way that data belongs in
    # the record instead. Defaulted and declared last so `with_location`'s
    # dataclasses.replace() and every existing construction site are unaffected.
    river: Optional[str] = None
    state: Optional[str] = None

    # Reservoir surface area at FRL. Optional because it is genuinely unknown for
    # both presets, and this is one of the places where a guess does real damage:
    # reservoir_storage_curve() (terrain/breach.py) falls back to
    # storage_exponent=3.0 — a cone — when this is None. That is defensible for
    # Tehri's Himalayan gorge. For a broad shallow Deccan pool like Khadakwasla
    # the exact exponent b = A0*d0/S0 is nearer 9, and getting b wrong distorts
    # the drawdown rate, and therefore the routed peak and the whole recession
    # limb. Supplying a real area here removes that assumption; inventing one
    # would only hide it. Declared last, with a default, so with_location()'s
    # dataclasses.replace() and every existing construction site are unaffected.
    surface_area_km2: Optional[float] = None

    def to_dam_config(self) -> Dict[str, Any]:
        """
        The plain dict ``build_domain()`` / ``run_dam_break_ensemble()``
        consume as their first positional argument. Raises PresetError if a
        solver-only field is missing rather than silently passing None into
        the breach regressions.
        """
        missing = [
            field
            for field, value in (
                ("height_m", self.height_m),
                ("storage_mm3", self.storage_mm3),
                ("dam_type", self.dam_type),
            )
            if value is None
        ]
        if missing:
            raise PresetError(
                f"{self.name} has no vetted value for {', '.join(missing)}. "
                f"These are required for the solver (breach regressions) but "
                f"not for --terrain-only or --reservoir. Per CLAUDE.md, "
                f"unvetted coefficients must not be guessed — supply a "
                f"primary CWC / dam-authority source before running the "
                f"solver for this preset."
            )
        config: Dict[str, Any] = {
            # dam_id travels with the config so downstream code can look up this
            # dam's own gauge corridor (get_gauges) instead of falling back to a
            # hardcoded one. Before this key existed, define_downstream_gauges()
            # had no way to tell which dam it was being called for and returned
            # the Tehri corridor unconditionally.
            "dam_id": self.dam_id,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "height_m": self.height_m,
            "storage_mm3": self.storage_mm3,
            "dam_type": self.dam_type,
            "failure_mode": self.failure_mode,
            # The DEM-backed extent for this dam. Emitted here so every caller
            # gets it, not just the HTTP layer: the service used to bolt it on
            # in RunRequest.to_dam_config, so a library-side caller (the Delft3D
            # comparison builder, scripts, tests) silently ran with no domain
            # cap. For Khadakwasla that meant a 70 km domain against a DEM that
            # covers 27 km — 83.7% of the grid filled with interpolated NoData,
            # which in turn made the reservoir undetectable.
            "domain_radius_km": self.domain_radius_km,
        }
        # Emitted only when known, so breach.py's own `surface_area_km2=None`
        # default path stays exactly as it is for a preset that lacks it.
        if self.surface_area_km2 is not None:
            config["surface_area_km2"] = self.surface_area_km2
        return config

    def dem_filename(self) -> str:
        """Must mirror jalraksha/dem.py::fetch_dem's clipped-cache filename."""
        return f"dem_{self.lat:.2f}_{self.lon:.2f}_clipped.tif"

    def with_location(self, lat: Optional[float], lon: Optional[float]) -> "DamPreset":
        """Return a copy with lat/lon overridden — the --dam-lat/--dam-lon path."""
        if lat is None and lon is None:
            return self
        return replace(
            self,
            lat=lat if lat is not None else self.lat,
            lon=lon if lon is not None else self.lon,
        )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

TEHRI = DamPreset(
    dam_id="tehri",
    name="Tehri Dam",
    lat=30.3789,
    lon=78.4789,
    height_m=260.0,
    storage_mm3=3540.0,
    dam_type="embankment",
    failure_mode="overtopping",
    region="Bhagirathi Basin, Uttarakhand",
    domain_radius_km=60.0,
    epsg=32644,
    # TODO: UNVETTED — confirm against a primary THDC / CWC source before
    # these are used for anything beyond visualization. Moved verbatim from
    # tools/paraview/reservoir.py, where they previously lived as
    # TEHRI_FRL_M / TEHRI_CREST_M module constants.
    frl_m=830.0,
    crest_m=839.5,
    frl_source="preset literal, UNVETTED (no primary THDC/CWC citation yet)",
    render_freeboard_m=0.0,
    barrier_freeboard_m=9.5,
    barrier_halfwidth_m=5000.0,
    direction_search_radius_cells=(5, 12),
    vertical_exaggeration=1.2,
    nominal_depth_m=120.0,
    river="Bhagirathi",
    state="Uttarakhand",
)
# NOTE: the visualization spec's Tehri dam-crest UTM (EPSG:32644, X=271500,
# Y=2043600) inverse-projects to 30.369248 N, 78.622323 E — 13.8 km from the
# dam coordinate above. The coordinate above is the one the cached DEM, the
# gauge set in services/api/jalraksha_service/config.py, and every verified
# artifact (phase1_terrain.png, phase3_reservoir.png, phase8b_tehri_*.png)
# were built against. The spec's UTM pair is intentionally not used.

KHADAKWASLA = DamPreset(
    dam_id="khadakwasla",
    name="Khadakwasla Dam",
    # NOT derived from the spec's UTM crest coordinate — see the rejection
    # note below this record. This is the same situation as TEHRI above: the
    # spec table's coordinate proved to place the "dam" on a hillside rather
    # than at a real pool.
    #
    # Validated by inspecting the DEM directly around this point: 400-3200 m
    # to the SW (bearing ~233 deg — the stable downhill direction at a 2-4 km
    # search radius, confirmed independently by a connected-component check
    # of the DEM's own low-elevation region) sits a dead-flat, 2.8 km-wide
    # plateau at exactly 580.0 m — GLO-30's baked-in reservoir surface (see
    # reservoir.py's module docstring: this DEM is a surface model and
    # already contains the impounded pool). The dam point itself, at 558.7 m,
    # sits in the discharge channel ~21 m below that pool — a normal dam
    # profile. The DEM also shows 11.6% NoData in the surrounding clip,
    # consistent with a real water body producing bad Copernicus pixels.
    #
    # NOTE: a naive small-radius (5-12 cell / 500 m-1.2 km) direction search
    # — the default that works for Tehri's narrow gorge — finds a spurious
    # ~11 deg (N) bearing here from local micro-relief, not this real
    # plateau; direction_search_radius_cells below overrides that.
    lat=18.4436,
    lon=73.7686,
    # PARTIALLY VETTED — revised 2026-08-28 from a sourced dam-parameter review
    # that supersedes the first pass (51.3 m / 33.5 MCM), both of which it
    # identifies as wrong for this purpose:
    #   * 51.3 m traces to a 1961 failure report describing a PLANNED dam stage
    #     that was never attained — not a current structural height.
    #   * 33.5 MCM is a partial live-storage figure. The regressions need GROSS.
    #
    # HEIGHT, 39.6 m — above deepest foundation, the NRLD convention the breach
    # regressions expect: 31.25 m above riverbed plus 8.37 m of foundation.
    # Attributed to CWPRS / civil dam records.
    #
    # STORAGE, 85.31 MCM — GROSS (live 55.91 MCM + dead). The live figure is
    # independently corroborated: 1.97 TMC = 55.9 MCM, matching NDMA.
    #
    # TODO: STILL UNVETTED as primary sources. The review's citations are
    # secondary — press reporting, an FAO 1989 fisheries survey, and
    # Wikipedia-derived compilations — not a National Register of Large Dams
    # entry read directly. It also flags a spurious "341 MCM" capacity in one
    # wiki table, which is a fair warning about the provenance chain generally.
    # Replace with an NRLD row when one is in hand.
    height_m=39.6,
    storage_mm3=85.31,
    # The same review describes the structure as "earth/gravity", while the
    # brief that requested this dam said "masonry gravity" (1879). Kept as
    # "gravity" deliberately: it is what was originally specified, and it is
    # the conservative reading. Reclassifying to an embankment on an ambiguous
    # secondary phrase would silently switch OFF breach.py's
    # dam_class_outside_fitted_population caveat, and a caveat wrongly removed
    # is a worse failure than one wrongly kept.
    dam_type="gravity",
    failure_mode="overtopping",
    region="Mutha River Basin, Pune, Maharashtra",
    # BOUNDED BY THE DEM, not by the gauge list. This was briefly widened to
    # 100.0 to bring Baramati (91.7 km) inside the domain, which was a mistake:
    # the cached Copernicus clip covers 73.513-74.054 E, 18.209-18.714 N — about
    # 57 x 56 km, a usable radius of ~28 km. A 100 km radius asks for a
    # 200 x 200 km grid from a DEM covering 8% of it, and build_domain duly
    # reported "Filling 920237 nodata cell(s) (92.02%)". Water then propagates
    # over interpolated fill rather than terrain, which is not a slower answer
    # but a meaningless one.
    #
    # 27.0 km, not the 30.0 this preset originally carried: the cached clip's
    # usable radius is 27.9 km, so even 30.0 was over — which is exactly where
    # its documented 11.6% NoData came from. 27.0 holds all SIX
    # Mula-Mutha corridor gauges
    # (furthest: Loni Kalbhor at 26.8 km) on real terrain. Baramati falls
    # outside and is reported as such by compute_arrival_times_at_gauges — which
    # is correct: it sits on the Karha, not this dam's river, so it was never on
    # the flood path. Raising this again REQUIRES fetching more GLO-30 tiles
    # first (N17-N19 x E072-E074), and CLAUDE.md's offline-first rule means that
    # cache must be warm before demo day.
    #
    # Margin is thin on BOTH sides and this is the real constraint on this dam:
    # the six gauges need a square half-width of 26.5 km (Loni Kalbhor is 26.5
    # km due east), and the DEM supplies 27.9 km. 27.0 fits between them with
    # ~0.5 km to spare. If Loni Kalbhor's arrival time ever matters precisely,
    # re-fetch the DEM with an eastward margin rather than nudging this up.
    # test_domain_radius_does_not_exceed_the_cached_dem pins the DEM side so
    # this cannot silently drift again.
    #
    # UPDATE: the cached DEM at data/dem/dem_18.44_73.77_clipped.tif was
    # subsequently widened to a 240 x 188 km (40 km west / 200 km east / 94 km
    # north+south) extent for a specific investigation — a 27 km dam-centred
    # domain plateaus the hazard classification instead of letting it recede,
    # because the flood has nowhere to drain to (see run.py's
    # _notch_breach_into_bed and terrain/conditioning.py's fill_depressions).
    # That investigation used domain_margins_km as a PER-REQUEST override
    # (services/api/jalraksha_service/schemas.py's RunRequest.domain_margins_km),
    # not a change to this preset — every default Khadakwasla run, including
    # the dashboard demo, still gets exactly this 27 km dam-centred square.
    # The wider cache is a superset of the old 57x56 km clip (nothing that
    # worked before stopped working); test_domain_radius_does_not_exceed_the_
    # cached_dem still passes, now with much more headroom.
    domain_radius_km=27.0,
    epsg=32643,
    # None => derive the fill level from the DEM's own impounded pool surface
    # at runtime (tools/paraview/reservoir.py::estimate_pool_surface_m).
    # Deliberately not a guessed published FRL.
    frl_m=None,
    crest_m=None,
    frl_source="DEM-derived pool surface (UNVETTED — not a published FRL)",
    # frl_m stays None above rather than becoming a literal. No published FRL
    # was found. The sourced review offers ~585 m MSL, but that is its OWN DEM
    # estimate, not a citation — and it contradicts itself, also quoting local
    # gauge readings of ~1666-1680 ft (~508-512 m), a ~73 m disagreement it
    # does not resolve. The two independent DEM reads DO agree (this repository
    # measured the pool plateau at exactly 580.0 m; the review got ~585 m),
    # which is what estimate_pool_surface_m already computes at runtime.
    # Hardcoding an estimate the code derives better trades a measurement for
    # a guess.
    render_freeboard_m=2.0,
    barrier_freeboard_m=10.0,
    # Wider than Tehri's: the Mutha corridor downstream opens onto the Pune
    # plain, which sits only tens of metres below the pool, so a wall sized
    # for a Himalayan gorge can be flanked. Widen further if
    # downstream_leak_cells > 0.
    barrier_halfwidth_m=12000.0,
    direction_search_radius_cells=(20, 40),
    vertical_exaggeration=2.0,
    nominal_depth_m=18.5,
    river="Mutha",
    state="Maharashtra",
    # 1,472 ha at full pool (FAO 1989 fisheries survey, via the same review).
    # Numerically the most consequential figure here: reservoir_storage_curve
    # derives b = A0*d0/S0 = 6.83 from it, against the cone default of 3.0 it
    # fell back on while this was unknown. A mean depth of only 5.8 m over
    # 14.72 km2 is a broad shallow pool, nothing like a cone, and b sets the
    # drawdown rate and therefore the routed peak and the recession limb.
    #
    # TODO: UNVETTED — a 1989 survey, not a current CWC/NRLD area-capacity
    # table. Better than assuming a cone; not a substitute for the real curve.
    surface_area_km2=14.72,
)
# REJECTED CANDIDATE: the visualization spec's Khadakwasla dam-crest UTM
# (EPSG:32643, X=373100, Y=2043600) inverse-projects to 18.478968 N,
# 73.798061 E — round-trips cleanly, but --locate-only at that point found
# the "dam" cell 36 m above the nearest DEM plateau (581.8 m vs. a 12-cell,
# 545.1 m pool sample found by the default small-radius direction search) —
# a hillside, not a reservoir. Same failure mode as Tehri's spec coordinate
# (see above): the spec table's UTM pairs are not reliable enough to use
# directly for either dam in this repository.

PRESETS: Dict[str, DamPreset] = {p.dam_id: p for p in (KHADAKWASLA, TEHRI)}
DEFAULT_PRESET_ID = "khadakwasla"


# ---------------------------------------------------------------------------
# River-blockage sites (natural dams)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockagePreset:
    """
    A site where a landslide can dam the river. NOT a dam.

    A sibling of DamPreset rather than a subclass, because the two disagree
    about what is knowable and DamPreset's disagreement is a safety property
    worth keeping intact. DamPreset.to_dam_config() REFUSES to emit a config
    with a missing height, storage or dam type, which is right for an
    engineered structure whose figures are published in a register. A landslide
    deposit has none of the three by nature, so a subclass would have to weaken
    that refusal for every dam in order to serve this one record.

    lat/lon are the BARRIER, not a dam. Everything the release model needs that
    is not here — impounded volume, surface area, crest and floor elevations —
    is measured at run time from a DEM with the barrier burned into it
    (jalraksha.terrain.blockage, jalraksha.terrain.dem_update). There is
    deliberately no storage field: a literal here would be exactly the
    slider-sets-the-physics failure that
    breach._synthesize_blockage_ensemble refuses.
    """

    site_id: str
    name: str
    lat: float
    lon: float
    river: str
    state: str
    region: str
    domain_radius_km: float
    epsg: int
    barrier_source: str
    event_date: Optional[str] = None
    barrier_crest_height_m: Optional[float] = None
    barrier_width_m: Optional[float] = None
    barrier_thickness_m: Optional[float] = None
    # A terrain-derived starting position for the operator, NOT a surveyed
    # deposit location. Kept separate from lat/lon, which is the reach centre.
    suggested_barrier_lat: Optional[float] = None
    suggested_barrier_lon: Optional[float] = None
    direction_search_radius_cells: Tuple[int, int] = (5, 12)
    vertical_exaggeration: float = 1.2
    nominal_depth_m: float = 40.0
    detect_date_pre: Optional[str] = None
    detect_date_post: Optional[str] = None
    note: Optional[str] = None

    def dem_filename(self) -> str:
        """Must mirror jalraksha/dem.py::fetch_dem's clipped-cache filename."""
        return f"dem_{self.lat:.2f}_{self.lon:.2f}_clipped.tif"

    def to_dam_config(self) -> Dict[str, Any]:
        """
        Config for a river_blockage run.

        Emits no storage and no height. ``storage_source`` is set to the
        pending marker so the ensemble refuses to run until tasks.py has
        replaced it with a measured volume — an absent marker is refused too,
        so deleting this line fails loudly rather than silently restoring the
        old slider-driven behaviour.
        """
        config: Dict[str, Any] = {
            "dam_id": self.site_id,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "dam_type": "landslide",
            "scenario_type": "river_blockage",
            "domain_radius_km": self.domain_radius_km,
            "storage_source": "hypsometric_fill_pending",
            "direction_search_radius_cells": self.direction_search_radius_cells,
        }
        if self.barrier_crest_height_m is not None:
            config["blockage_crest_height_m"] = self.barrier_crest_height_m
        if self.barrier_width_m is not None:
            config["blockage_width_m"] = self.barrier_width_m
        if self.barrier_thickness_m is not None:
            config["blockage_thickness_m"] = self.barrier_thickness_m
        return config


RISHI_GANGA = BlockagePreset(
    site_id="rishi_ganga",
    name="Rishi Ganga / Dhauliganga, Chamoli",
    # THE REACH CENTRE, which is where the DOMAIN is centred and where the map
    # marker sits. It is not the barrier — the barrier is supplied per run,
    # because a landslide can dam a river anywhere along it.
    #
    # Placed on the Dhauliganga between Tapovan and Joshimath rather than at a
    # nominal village coordinate. An earlier value of (30.44, 79.70) was taken
    # from a gazetteer reading of Raini and lands on a 4,100 m RIDGE in GLO-30;
    # the domain still covered the river, but the marker described a mountain
    # top. Checked against the DEM: Tapovan reads 1,830 m at its valley floor
    # and Joshimath 1,876 m, both consistent with published elevations, so the
    # terrain here is right and only the coordinate was wrong.
    lat=30.50,
    lon=79.63,
    river="Rishi Ganga / Dhauliganga",
    state="Uttarakhand",
    region="Chamoli, Garhwal Himalaya",
    # 18 km. Two constraints, both measured rather than assumed:
    #
    #   * At 30 km the domain crosses into the E080 Copernicus tile, which is
    #     not staged. The clip that IS staged was fetched at 20 km and spans
    #     lon 79.491-79.909, lat 30.260-30.620.
    #   * That clip's usable radius is 19.92 km, not 20. fetch_dem sizes its
    #     bbox with 111.0 km per degree of latitude; the true figure near 30 N
    #     is 110.57, so a "20 km" clip is 0.08 km short of 20 km on the ground.
    #     Declaring 20 here would put the solver on interpolated fill at the
    #     domain edge — silently, because build_domain fills the gap and runs.
    #
    # 18 km leaves margin against both and still contains the corridor that
    # matters: Raini to Tapovan to Joshimath is about 15 km.
    domain_radius_km=18.0,
    epsg=32644,
    event_date="2021-02-07",
    # TODO: UNVETTED — no crest height or width is published for the temporary
    # blockage, so none is asserted here and the operator must supply them.
    #
    # They are MEASURABLE rather than guessable: Chamoli is the only event in
    # the problem statement's list with pre- and post-event 2 m DEMs publicly
    # downloadable (Zenodo 4554647 pre, 4558692 post, CC BY-NC-4.0). Differencing
    # those two gives the deposit's actual location, crest height and width.
    # Use the NUMBERS; do not redistribute the DEMs, the licence is
    # non-commercial. docs/VERIFICATION_LOG.md row 26.
    barrier_crest_height_m=None,
    barrier_width_m=None,
    barrier_source=(
        "Not yet derived. Measure by differencing Zenodo 4554647 (pre-event) "
        "against 4558692 (post-event), both 2 m; see docs/VERIFICATION_LOG.md "
        "row 26. Until then the barrier is operator-supplied."
    ),
    # A defensible place to put one, found in the DEM rather than in a source:
    # the deepest gorge cell in this domain below 2,600 m, at 1,702 m with
    # 1,200 m of cross-valley relief within 2.1 km. Offered as a starting point
    # for the operator, and labelled as terrain-derived so nobody reads it as
    # the surveyed 2021 deposit location, which is item 26 in the queue.
    suggested_barrier_lat=30.5207,
    suggested_barrier_lon=79.6098,
    # A steep Himalayan gorge: the narrow-radius annulus that works for Tehri is
    # the right scale here too, and the broad-terrain radius Khadakwasla needs
    # would average across ridges.
    direction_search_radius_cells=(5, 12),
    vertical_exaggeration=1.2,
    nominal_depth_m=30.0,
    # The Sentinel-1 windows for detection. The post date is the first
    # acquisition after the 7 February 2021 event; a SINGLE scene, not a
    # composite, so "rebuilt from the 2021-02-08 scene" is a true sentence.
    detect_date_pre="2021-01-15",
    detect_date_post="2021-02-08",
    note=(
        "The problem statement calls this a natural lake formation on the Rishi "
        "Ganga. The 7 February 2021 Chamoli event was in fact a ROCK-AND-ICE "
        "AVALANCHE from Ronti Peak, not a glacial lake outburst — though a "
        "temporary blockage did form on the Rishi Ganga afterwards, which is "
        "the blockage modelled here. Shugar et al. (2021), Science."
    ),
)

BLOCKAGE_PRESETS: Dict[str, BlockagePreset] = {
    p.site_id: p for p in (RISHI_GANGA,)
}


def get_blockage_preset(site_id: str) -> BlockagePreset:
    try:
        return BLOCKAGE_PRESETS[site_id]
    except KeyError:
        raise PresetError(
            f"Unknown blockage site {site_id!r}. Available: "
            f"{sorted(BLOCKAGE_PRESETS)}"
        ) from None


# ---------------------------------------------------------------------------
# Downstream gauge corridors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GaugePoint:
    """
    One downstream location where arrival time is reported.

    distance_km is DISPLAY metadata (and the only input to the Delft3D-Ritter
    analytic fallback in delft3d/runner.py). Arrival times from the SWE solver
    are computed from lat/lon: compute_arrival_times_at_gauges() projects the
    gauge into the domain's UTM zone and snaps it onto the channel. So a
    distance that is approximate degrades a label, not a result.

    That matters because the two corridors below do not measure distance the
    same way — see GAUGES.
    """

    name: str
    distance_km: float
    lat: float
    lon: float
    river: Optional[str] = None
    note: Optional[str] = None  # surfaced in the API and the dashboard


# Which downstream towns a dam's flood is reported at, keyed by dam_id.
#
# WHY THIS EXISTS: this list was previously duplicated in six places
# (jalraksha/run.py, jalraksha/api.py twice, services/api/.../config.py,
# services/api/.../tasks.py, frontend/src/data/entities.js) and every copy was
# the Tehri corridor, unconditionally. A Khadakwasla run therefore reported
# arrival times at Himalayan towns ~1,500 km outside its own domain. Gauges
# belong to a dam, so they live next to the dams.
#
# DISTANCE CONVENTIONS DIFFER BETWEEN CORRIDORS AND ARE NOT COMPARABLE:
#   tehri        — river distances along the Bhagirathi/Ganga, from the brief.
#   khadakwasla  — straight-line (great-circle) from the dam. No channel trace
#                  was available to derive river distance, and inventing a
#                  meander factor would be a fabricated number. River distance
#                  along the Mutha is longer than every value listed here.
GAUGES: Dict[str, Tuple[GaugePoint, ...]] = {
    # Moved verbatim from jalraksha/run.py::define_downstream_gauges. Do NOT
    # re-derive these: run.py's own comment records that they were previously
    # approximate to the point of being wrong (Koteshwar sat ~4 km east of the
    # gorge, so the flood never reached it; Rishikesh and Haridwar carried 77.x
    # longitudes placing them ~112 km and ~29 km west of the real towns).
    "tehri": (
        GaugePoint("Koteshwar", 13.0, 30.3167, 78.4833, river="Bhagirathi"),
        GaugePoint("Devprayag", 28.0, 30.15, 78.60, river="Ganga"),
        GaugePoint("Rishikesh", 34.8, 30.0869, 78.2676, river="Ganga"),
        GaugePoint("Haridwar", 58.4, 29.9457, 78.1642, river="Ganga"),
    ),
    # The Pune corridor: the Mutha runs east from the dam through the city,
    # joins the Mula near Sangam, and continues as the Mula-Mutha toward the
    # Bhima. Ordered by distance ascending so the dashboard table reads down
    # the corridor. Coordinates are as supplied (approximate town centres).
    "khadakwasla": (
        GaugePoint("Deccan Gymkhana", 10.5, 18.51, 73.84, river="Mutha"),
        GaugePoint("Swargate", 11.5, 18.50, 73.86, river="Mutha"),
        GaugePoint("Shivajinagar", 12.1, 18.52, 73.85, river="Mutha"),
        GaugePoint("Hadapsar", 18.6, 18.51, 73.93, river="Mula-Mutha"),
        GaugePoint("Magarpatta City", 19.0, 18.52, 73.93, river="Mula-Mutha"),
        GaugePoint("Loni Kalbhor", 26.8, 18.48, 74.02, river="Mula-Mutha"),
        GaugePoint(
            "Baramati",
            91.7,
            18.15,
            74.58,
            river="Karha",
            note=(
                "OFF-CORRIDOR AND OUTSIDE THE DOMAIN. Baramati sits on the "
                "Karha/Nira, not the Mula-Mutha that carries this dam's "
                "flood, and at 91.7 km it lies beyond the 30 km solver "
                "domain, so no arrival is computed for it. Listed because it "
                "was requested as a downstream reference point; extending "
                "the domain to reach it would require fetching more GLO-30 "
                "tiles first, and would still be routing water down a river "
                "this town is not on."
            ),
        ),
    ),
    # NO CORRIDOR FOR rishi_ganga, DELIBERATELY.
    #
    # A first attempt published Rishiganga, Tapovan and Joshimath from gazetteer
    # town coordinates. Checked against the DEM they sat 1,319 m, 79 m and 516 m
    # ABOVE the nearest river channel -- the pipeline's own _no_arrival_reason
    # caught it and reported "a town centre, not a riverside gauge" -- and even
    # snapped to the lowest cell within 2 km, "Rishiganga power project" landed
    # at 2,851 m, which is not where a riverside plant is. Two of them are hill
    # towns whose centres genuinely sit hundreds of metres above their rivers, so
    # the coordinates were not simply mistyped: they answer a different question
    # from the one a flood gauge asks.
    #
    # This repeats the failure GAUGES was created to end (Koteshwar 4 km east of
    # the gorge, Rishikesh 112 km west of itself), so the entries are removed
    # rather than snapped into plausibility. get_gauges returns () and the
    # dashboard shows no corridor, which is the honest state: nobody has sourced
    # channel positions for this reach.
    #
    # WORTH FINISHING. The published HEC-RAS study of the 7 February 2021 flow
    # reports peak discharge and depth at two named points -- Rishiganga
    # 7,908-7,975 m3/s at 19.85 m, and Tapovan 5,780-5,957 m3/s at 18.15 m
    # (literature.md 11.2). With sourced CHANNEL coordinates those become a
    # citable validation comparison for a natural-dam outburst -- the equivalent
    # of the Teton benchmark the breach regressions are scored on, and the
    # strongest evidence this scenario could carry.
    #
    # WHAT IS PUBLISHED INSTEAD: unnamed CHANNEL POINTS, derived from the DEM.
    #
    # They carry no town name because none is claimed. Each is a cell on the
    # traced thalweg downstream of the suggested barrier, at a stated
    # along-channel distance, and the question they answer -- does the release
    # get this far, and when -- is the one a gauge is for. Naming them after
    # Joshimath or Tapovan would assert a location this repository cannot source;
    # leaving the reach unmonitored would discard a real result.
    #
    # Traced on dem_30.50_79.63_clipped.tif at 100 m by steepest descent from the
    # suggested barrier: bed falls 1,700 m -> 1,500 m -> 1,357 m -> 1,271 m over
    # 15.1 km, which is a plausible Himalayan river profile and not a walk up a
    # valley wall. Distances are along that trace, so they are approximate in the
    # way a DEM-traced channel is: the step is up to 15 cells, and the real river
    # meanders inside it.
    "rishi_ganga": (
        GaugePoint(
            "Dhauliganga channel +5 km", 5.0, 30.5559, 79.5828,
            river="Dhauliganga",
            note=(
                "TERRAIN-DERIVED channel point, not a surveyed gauge and not a "
                "town. Bed 1,500 m, traced 5.0 km down the thalweg from the "
                "suggested barrier."
            ),
        ),
        GaugePoint(
            "Alaknanda channel +10 km", 10.5, 30.5581, 79.5348,
            river="Dhauliganga / Alaknanda",
            note=(
                "TERRAIN-DERIVED channel point, not a surveyed gauge and not a "
                "town. Bed 1,357 m, traced 10.5 km down the thalweg."
            ),
        ),
        GaugePoint(
            "Alaknanda channel +15 km", 15.1, 30.5270, 79.5051,
            river="Alaknanda",
            note=(
                "TERRAIN-DERIVED channel point, not a surveyed gauge and not a "
                "town. Bed 1,271 m, traced 15.1 km down the thalweg -- the "
                "furthest the trace reaches inside this domain."
            ),
        ),
    ),
}


def get_gauges(dam_id: Optional[str]) -> Tuple[GaugePoint, ...]:
    """
    The downstream corridor for a dam, or () if this dam has no defined one.

    Returns empty rather than raising, and empty rather than substituting
    another dam's towns: a dam with no surveyed corridor should report no
    gauges. Callers that need a fallback (jalraksha/api.py's generic
    Gauge_Nkm placeholders) apply it themselves, visibly.
    """
    if not dam_id:
        return ()
    return GAUGES.get(dam_id, ())


def get_preset(dam_id: str) -> DamPreset:
    try:
        return PRESETS[dam_id]
    except KeyError:
        raise PresetError(
            f"Unknown dam preset {dam_id!r}. Available: {sorted(PRESETS)}"
        ) from None
