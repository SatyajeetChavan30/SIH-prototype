# Implementation plan

Phases from spec Section 17. A phase is done when its artifact exists and has been
looked at — not when the code is elegant (Section 0).

**Two dam presets** (`jalraksha/presets.py`): **Khadakwasla** (Mutha River Basin,
Pune; default) and **Tehri** (Bhagirathi Basin, Uttarakhand). Everything below
that used to say "Tehri" implicitly now works for either via `--dam`; artifact
filenames below are dam-specific where both have been rendered.

ParaView 6.2.0 and FFmpeg are now installed on this machine
(`/c/Program Files/ParaView 6.2.0/bin/pvpython`) — the "blocked on install" note
that used to sit at the bottom of this file no longer applies.

---

## Phase 1 — DEM → 3D terrain

- [x] Clean elevation raster with known CRS — `conditioning.py::load_dem_as_grid`,
      EPSG:32644, nearest-valid NoData fill, no smoothing
- [x] Written as a ParaView-readable dataset — `data/simulation/terrain.xdmf`
- [x] **Verified**: reader reports dims `(300, 300, 1)`, bounds in the XY plane,
      elevation 248–6743 m, landmark bias +5.8 m at Tehri
- [x] README command reproducing it from a clean checkout
- [x] **Artifact: `paraview/artifacts/phase1_terrain.png`** — real Garhwal relief,
      ridges/drainage/snow peaks, elevated oblique camera, elevation legend

Deliberately **not** baked into the data: vertical exaggeration is Warp By
Scalar's Scale Factor, so it is changed in the GUI, not by regenerating files.

## Phase 2 — Terrain appearance

- [x] Elevation colormap (`gist_earth`) — a texture was not needed; the ramp
      already reads as terrain, and a satellite texture would obscure the
      depth/velocity fields that the later phases exist to show
- [x] Lighting tuned — `Ambient 0.25 / Diffuse 0.85 / Specular 0.15` on the
      terrain. `GetDisplayProperties` had been imported since Phase 1 and never
      called; flat default lighting is the main reason a correctly-warped
      terrain still reads as a 2D map
- [x] Terrain base block — `tools/paraview/base_block.py` writes a skirt + bottom
      cap as a standalone `.vtp`, loaded via `render_static.py --base-block`
- [x] **Artifact: `paraview/artifacts/phase2_terrain_block.png`** — raised
      rectangular block with visible grey side walls, snow-capped Garhwal relief,
      clean background. Matches the reference composition.

**Base-block decision (was open).** Resolved in favour of a *separate* `.vtp`
rather than extending `xdmf_export.py`: that writer's layout is pinned by 12
passing tests and consumed by the solver path, and a presentational pedestal
should not make every consumer pay for geometry only the renderer wants.

The skirt is stored flat at z=0 carrying its target elevation as a
`terrain_elevation` scalar, and is warped by the *same* Scale Factor as the
terrain. This is what lets one file work at any vertical exaggeration — baked z
values would line up at exactly one exaggeration and visibly detach at others.
Showing the block *unwarped* leaves it lying at z=0 while the terrain lifts away
above it, which renders as a sliver at the domain edge rather than a pedestal.

Its default depth is `max(30% of relief, 3% of domain width, 100 m)`. Relief
alone is not sufficient: on the 120 km Tehri domain, 12% of 6.5 km of relief is
a 780 m wall — under 1% of frame width, i.e. a hairline.

## Phase 3 — Static water

- [x] Single-timestep water surface available (`--terrain-only` writes zero depth;
      `--synthetic` at t=0 gives a dry start, any later frame gives a surface)
- [x] **Artifact: terrain + plausible static water, one image.**
      `paraview/artifacts/phase3_reservoir.png` (Tehri) — the impounded pool
      reads as a sinuous lake following the Bhagirathi valley, terminating
      cleanly at the dam with no downstream leakage.
      `paraview/artifacts/phase3_khadakwasla_reservoir.png` (Khadakwasla) —
      a branching lake following the Mutha valley's moderate relief,
      likewise cleanly stopped at the dam
      (`downstream_leak_cells: 0`, `surface_spread: 0.000 m`, both dams).
      Both viewed and confirmed correct.

## Phase 4 — Time-varying data

- [x] Multi-timestep file — `data/simulation/synthetic.xdmf`, 30 steps, 0–3600 s
- [x] **Verified**: reader reports 30 timesteps; wet cells 0 → 5,127 → 19,216 and
      max depth 0 → 24.7 m across the series, so it is genuinely time-varying and
      not N copies of one field
- [x] Labelled `is_synthetic=1`, confirmed to survive the reader
- [x] **Artifact: `paraview/artifacts/phase4_synthetic_water.png`** — water lifted
      to terrain+depth via Calculator, dendritic drainage pattern, both legends

## Phase 5 — Timeline

- [x] Animation View mode + frame rate configured — `render_static.py
      --save-state` writes a `.pvsm` with `PlayMode=Sequence` and a frame count
- [x] **Artifact: `paraview/state/tehri_animation.pvsm`** — opening it in the
      ParaView GUI restores this exact scene with the Animation View already in
      Sequence mode, which *is* the scrubbable animation this phase asks for
- [x] **Verified genuinely time-varying** (not N copies of one field): rendering
      `tehri.xdmf` at t = 0 / 5400 / 10800 s gives 0 → 227 → 311 wet cells and
      peak depth 0 → 110.1 → 160.8 m, cross-checked against the `.h5` in numpy.
      At t=0 the renderer correctly reports a dry bed and skips glyphs.

No custom code: Section 10 requires ParaView's own VCR toolbar and Animation View.
Use **Sequence** mode for video (interpolates to a fixed frame rate) and **Snap To
TimeSteps** to inspect raw solver output.

**Reading the saved state back:** ParaView 6.2.0 exposes only two play modes and
serialises `Sequence` as `0`, `Snap To TimeSteps` as `2` (confirmed by
round-tripping both). A `PlayMode` of `0` in the `.pvsm` XML is therefore
correct — it is *not* the older three-value enum in which `0` meant Snap To
TimeSteps. This cost some time to diagnose once; it is recorded here and in
`render_static.py` so it is not re-diagnosed.

## Phase 6 — Scientific overlays

- [x] Data side ready: `water_depth`, `velocity` (3-component, Glyph-ready),
      `velocity_magnitude`, `is_synthetic`
- [x] Depth colouring with a fixed custom range — `--depth-max` (default 25 m),
      never per-timestep auto-scale, so a colour means the same depth in every
      frame. The ramp is explicit RGB points rather than the stock "Linear Blue
      (8_31f)", whose deep end is so near black that deep water read as shadow.
- [x] Velocity Glyphs with capped density — `--glyphs`, `--glyph-stride`,
      `--glyph-scale`. Both default to **auto**, and both had to: a fixed stride
      cannot serve `tehri.xdmf` (311 wet cells) and `synthetic.xdmf` (19,216) at
      once, and the previous fixed `--glyph-scale 50` produced 750 m arrows on a
      120 km domain — under a pixel. Stride now targets ~400 arrows and scale
      makes the longest arrow ~2.5% of the domain diagonal.
      Measured: synthetic → stride 45 (407 arrows); Tehri → stride 1 (273).
- [x] Glyphs auto-skip, loudly, when max |v| is 0 — the reservoir datasets have
      no flow by construction, and glyphing them would draw a degenerate
      zero-length arrow per wet cell, implying a current the data disclaims.
- [x] Flood-extent Threshold + area readout — `--show-area`. Cell area is derived
      from the reader's own grid, not a third hardcoded literal.
      **Verified**: on-frame 3074.56 km² for synthetic and 49.76 km² for Tehri
      both match a direct numpy count over the `.h5` exactly.
- [x] Annotate Time — the built-in filter, which reads the scene clock and so
      cannot drift out of sync with the frame the way a drawn label would.
- [x] Python Annotation reading `is_synthetic` — **and this fixed a live spec
      violation**: `phase4_synthetic_water.png` was shipping as a synthetic
      result carrying no warning at all, which is precisely the failure mode
      Section 0 exists to prevent. The banner is deliberately **not** behind a
      flag; it is driven by the dataset's own field data, so it cannot be
      forgotten or switched off independently of the data it describes.
      Verified to fire on `synthetic.xdmf` and stay absent on both the real
      solver run and the reservoir fills.

Two ParaView 6.2.0 details worth recording, both found the hard way:
`is_synthetic` arrives in a Python Annotation expression as a plain **int**, so
`is_synthetic[0]` raises "int object is not subscriptable"; and the expression
pre-processor mangles ` and `/` or `, truncating the expression mid-parenthesis,
so these expressions stay to a single comparison.

## Phase 7 — Static export

- [x] `render_static.py` using `SaveScreenshot` at a named time. Handles both
      dams (dam-agnostic — operates on whatever `--xdmf` path is passed).
      Fixed two real bugs along the way: (1) mutating `GetActiveCamera()`'s
      vtkCamera directly is silently overwritten by the view proxy on
      render — now sets `view.CameraPosition`/`FocalPoint`/`ViewUp`
      directly; (2) a view auto-resets its camera on first render,
      discarding any pre-set position — fixed by rendering once before
      positioning the camera.
- [x] Named, reproducible cameras — `paraview/camera_presets.py` provides
      `perspective` (the signed-off Phase 1/3/4 framing, carried over verbatim so
      reviewed artifacts stay valid), `isometric`, `oblique_low` and `top`,
      selected with `--camera`. Previously elevation/azimuth were defaults in
      `setup_camera`'s signature with no way to reach them from the CLI; only
      `--zoom` was exposed. Section 13 asks for exactly this.
      **Verified reproducible**: the same preset rendered twice is byte-identical.
      `top` carries a `view_up` override — at near-nadir elevation the default
      +Z up vector becomes parallel to the view direction and the frame degenerates.
- [x] **Artifacts**: `phase1_terrain.png`, `phase2_terrain_block.png`,
      `phase3_reservoir.png`, `phase3_khadakwasla_reservoir.png`,
      `phase4_synthetic_water.png`, `phase7_flood_t10800s.png`,
      `phase7_camera_top.png`, `phase7_camera_isometric.png`,
      `phase8b_tehri_real.png`, `phase8b_tehri_closeup.png`.

**On the spec's `flood_t_25s.png`:** that filename is illustrative. Export at an
arbitrary named time is implemented and exercised (`--time`, verified at
t = 0 / 5400 / 10800 s). t = 25 s specifically is not a useful *artifact* here:
the Tehri run is 3 h long with snapshots ~180 s apart, so 25 s falls inside the
dry initial state and would produce a deliberately empty frame. The named-time
artifacts are recorded at times where there is something to see.

## Phase 8 — Video export

- [ ] `render_animation.py` using `SaveAnimation` → PNG sequence — *needs ParaView*
- [ ] FFmpeg encode to MP4 — *needs FFmpeg*
- [ ] **Artifact: `flood_simulation.mp4` with continuously moving water**

## Phase 9 — Optimization

- [ ] Only once Phases 1–8 have artifacts. Section 0 forbids tuning earlier.
- [x] Already in place upstream: DEM downsampled in Python rather than decimated
      in ParaView; HDF5 so only requested timesteps are read; terrain stored once.

---

## Real-solver dataset

- [x] Solver records velocity — `solver/parallel.py::_snapshot`
- [x] Pipeline returns the bed it solved over — `run.py`
- [x] `frames_from_result()` adapts it, and **fails loudly** on a pre-velocity run
      rather than exporting zeros that would render as still water
- [x] Rendered: `phase8b_tehri_real.png` (wide) and `phase8b_tehri_closeup.png`
      (zoomed). The real flood wets ~0.35% of the 120 km domain versus the
      synthetic's 21%, so the wide shot shows a hairline — that is the physics
      of a gorge-confined dam-break at 400 m, not a rendering fault. The
      close-up shows the deep channel and shallow fringes clearly.

## Khadakwasla preset (added, Phase 3 sign-off)

- [x] `jalraksha/presets.py` — `DamPreset` dataclass, `KHADAKWASLA` and `TEHRI`
      records, `get_preset()`/`to_dam_config()`. Replaces the module-level
      `TEHRI` dict that used to live in `tools/paraview/make_dataset.py`.
- [x] `--dam {khadakwasla,tehri}` on `make_dataset.py` (default `khadakwasla`),
      with per-dam output stems (`{dam}_{mode}`) so one dam's run cannot
      overwrite another's files.
- [x] Khadakwasla's lat/lon validated against the DEM directly
      (`--locate-only`): the dam cell's own elevation and a DEM-derived pool
      plateau agree to within ~2.4 m, and 11.6% surrounding NoData is
      consistent with a real water body. The spec's own UTM coordinate was
      tried first and rejected — it placed the "dam" 36 m above the nearest
      plateau (a hillside). The same check on Tehri's spec UTM coordinate
      found a 13.8 km discrepancy from the value this repo has always used;
      Tehri's coordinate was left unchanged.
- [x] `tools/paraview/reservoir.py::estimate_pool_surface_m` — derives a fill
      level from the DEM's own baked-in pool surface (a statistical mode of
      upstream elevations, not "closest to the local minimum" — the latter
      was measured latching onto the discharge channel instead of the real
      580 m, 2.8 km-wide plateau) for a dam with no published FRL.
      `_downhill_direction`'s search radius is now configurable per preset —
      Tehri's narrow-gorge default (5–12 cells) found spurious local noise on
      Khadakwasla's broader terrain; (20, 40) cells found the real valley
      trend, confirmed independently by a connected-component check.
- [x] Tehri regression: `--dam tehri --reservoir --resolution 100` reproduces
      the pre-refactor baseline exactly (extent 32.6 km², mean fill 14.3 m,
      max 16.1 m, leak 0 cells).
- [x] `python -m pytest tests/ -q` passes after the refactor.

## Blocked on install

Nothing — ParaView 6.2.0 and FFmpeg are both installed on this machine.

