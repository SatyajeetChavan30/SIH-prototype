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
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "height_m": self.height_m,
            "storage_mm3": self.storage_mm3,
            "dam_type": self.dam_type,
            "failure_mode": self.failure_mode,
        }

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
    # UNVETTED — no primary CWC / Maharashtra WRD source available for these.
    # Not required for --terrain-only or --reservoir; to_dam_config() raises
    # if a solver mode is requested until a real source is supplied.
    height_m=None,
    storage_mm3=None,
    dam_type=None,
    failure_mode="overtopping",
    region="Mutha River Basin, Pune, Maharashtra",
    domain_radius_km=30.0,
    epsg=32643,
    # None => derive the fill level from the DEM's own impounded pool surface
    # at runtime (tools/paraview/reservoir.py::estimate_pool_surface_m).
    # Deliberately not a guessed published FRL.
    frl_m=None,
    crest_m=None,
    frl_source="DEM-derived pool surface (UNVETTED — not a published FRL)",
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


def get_preset(dam_id: str) -> DamPreset:
    try:
        return PRESETS[dam_id]
    except KeyError:
        raise PresetError(
            f"Unknown dam preset {dam_id!r}. Available: {sorted(PRESETS)}"
        ) from None
