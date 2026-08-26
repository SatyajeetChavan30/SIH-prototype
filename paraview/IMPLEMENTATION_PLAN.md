# Implementation plan

Phases from spec Section 17. A phase is done when its artifact exists and has been
looked at — not when the code is elegant (Section 0).

**Who verifies** is the honest column. ParaView is not installed on the build
machine, so its half cannot be checked here; the data half is checked by running it.

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

- [ ] Texture or elevation colormap, lighting, terrain base block — *needs ParaView*
- [ ] **Artifact: screenshot resembling the reference terrain**

Note the base block is the one item here that may need data-side work: extruding
the terrain boundary down to a flat plane is easier to generate in Python than to
approximate in ParaView. Decide when Phase 2 starts.

## Phase 3 — Static water

- [x] Single-timestep water surface available (`--terrain-only` writes zero depth;
      `--synthetic` at t=0 gives a dry start, any later frame gives a surface)
- [ ] **Artifact: terrain + plausible static water, one image** — *needs ParaView*

## Phase 4 — Time-varying data

- [x] Multi-timestep file — `data/simulation/synthetic.xdmf`, 30 steps, 0–3600 s
- [x] **Verified**: reader reports 30 timesteps; wet cells 0 → 5,127 → 19,216 and
      max depth 0 → 24.7 m across the series, so it is genuinely time-varying and
      not N copies of one field
- [x] Labelled `is_synthetic=1`, confirmed to survive the reader
- [x] **Artifact: `paraview/artifacts/phase4_synthetic_water.png`** — water lifted
      to terrain+depth via Calculator, dendritic drainage pattern, both legends

## Phase 5 — Timeline

- [ ] Animation View mode + frame rate configured — *needs ParaView*
- [ ] **Artifact: working scrubbable animation in the GUI**

No custom code: Section 10 requires ParaView's own VCR toolbar and Animation View.
Use **Sequence** mode for video (interpolates to a fixed frame rate) and **Snap To
TimeSteps** to inspect raw solver output.

## Phase 6 — Scientific overlays

- [x] Data side ready: `water_depth`, `velocity` (3-component, Glyph-ready),
      `velocity_magnitude`, `is_synthetic`
- [ ] Depth colouring with a fixed custom range — *needs ParaView*
- [ ] Velocity Glyphs with capped density — *needs ParaView*
- [ ] Flood-extent Threshold + area readout — *needs ParaView*
- [ ] Annotate Time + Python Annotation reading `is_synthetic` — *needs ParaView*

## Phase 7 — Static export

- [ ] `render_static.py` using `SaveScreenshot` at a named time — *needs ParaView*
- [ ] **Artifact: `flood_t_25s.png`**

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

## Blocked on install

ParaView (Phases 1–8 artifacts, all pvpython scripts) and FFmpeg (Phase 8 encode).
Every decision those scripts encode is settled in ARCHITECTURE.md; only the typing
is pending.




| Phase | Task / Objective | Model | Effort Level | Token Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 3 Finish** | Visual sign-off on `phase3_reservoir.png` & update `paraview/IMPLEMENTATION_PLAN.md` | Haiku 4.5 | Low | Use Haiku for plain text markdown check-offs to conserve credits. |
| **Phase 2 Planning** | Design XDMF+HDF5 schema, wave equations, and solver contract | Opus 5 / Opus 5 | High | Front-load reasoning in 1 comprehensive prompt to avoid back-and-forth loops. |
| **Phase 2 Execution** | Write `demo_synthetic.py` & `xdmf_export.py` HDF5 serialization code | Sonnet 5 | Medium–High | Pass the exact specification from Opus directly to Sonnet 5 for clean single-pass code output. |
| **Phase 5** | Scientific overlays (`Annotate Time`, synthetic flag warning, fixed depth legends, velocity glyphs) | Sonnet 5 | Medium | Combine all filter node logic into a single script request to minimize context window overhead. |
| **Phase 6** | Set up `camera_presets.py` and fix `render_static.py` pre-render auto-reset issue | Sonnet 5 | Medium | Use Sonnet 5 for routine API script bug fixes and parameter matrix definitions. |
| **Phase 7 Planning** | Frame interpolation sequence design & FFmpeg H.264 pipe strategy | Opus 5 | Medium–High | Map out execution steps and error-handling constraints before requesting code. |
| **Phase 7 Execution** | Implement `render_animation.py` (`SaveAnimation()`) & FFmpeg wrapper script | Sonnet 5 | High | Delegate heavy Python file generation to Sonnet 5. |
| **Phase 8** | Grid resolution decimation (30m/60m/120m) & ParaView interactive LOD tuning | Sonnet 5 | Low–Medium | Simple array resampling and property setting updates. |
| **Phase 9** | Create unified CLI orchestrator `main.py` (`argparse` setup) | Haiku 4.5 | Low | Haiku handles standard CLI boilerplate with minimal token cost. |