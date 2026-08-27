# ParaView flood visualization

3D terrain + flood visualization for two dam presets — **Khadakwasla** (Mutha
River Basin, Pune; default) and **Tehri** (Bhagirathi Basin, Uttarakhand) —
from real Copernicus GLO-30 DEM and a validated shallow-water solver.

## Status

| Half | State |
|---|---|
| Data layer — DEM → XDMF+HDF5 time series | **working and verified** |
| ParaView layer — static render (`render_static.py`) | **working** — ParaView 6.2.0, FFmpeg installed |
| ParaView layer — overlays, terrain block, cameras, saved state | **working** (spec Phases 2/5/6/7) |
| ParaView layer — video export, optimization | not built (spec Phases 8/9) |
| Dashboard → ParaView desktop launch | **working** (local host only) |

See [ARCHITECTURE.md](ARCHITECTURE.md) for format/CRS decisions and
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the phase checklist.

## Dam presets

Both presets live in `jalraksha/presets.py`. Select with `--dam` on
`make_dataset.py` (default `khadakwasla`).

| | Khadakwasla (default) | Tehri |
|---|---|---|
| Region | Mutha River Basin, Pune, MH | Bhagirathi Basin, Uttarakhand |
| CRS | EPSG:32643 (UTM 43N) | EPSG:32644 (UTM 44N) |
| Domain radius | 30 km | 60 km |
| Vertical exaggeration (default) | 2.0x | 1.2x |
| FRL / crest | derived from the DEM's own pool surface (UNVETTED — no published figure) | 830.0 / 839.5 m (UNVETTED — no primary THDC/CWC citation) |
| Solver modes (`--duration`, no mode flag) | **not available** — no vetted height/storage/dam_type | available |

Khadakwasla's `height_m`/`storage_mm3`/`dam_type` have no primary source yet;
`--terrain-only` and `--reservoir` work regardless, but the full solver path
raises a clear error until those are supplied — see `jalraksha/presets.py`.

## Generate a dataset

From the repository root. Output lands in `data/simulation/<dam>_<mode>.*`.

Terrain only — no solver, no water. Seconds:

```bash
python tools/paraview/make_dataset.py --dam khadakwasla --terrain-only --resolution 100
```

Static reservoir at full supply level — the intact-dam, t=0 state:

```bash
python tools/paraview/make_dataset.py --dam khadakwasla --reservoir --resolution 100
```

Real terrain with **synthetic** water, 30 timesteps (Tehri only for now):

```bash
python tools/paraview/make_dataset.py --dam tehri --synthetic --duration 3600 --frames 30
```

Real terrain with the **validated solver** (Tehri only — see the presets table above):

```bash
python tools/paraview/make_dataset.py --dam tehri --duration 10800 --resolution 400 --frames 60
```

If a dam's DEM is missing (`data/` is gitignored, so a fresh clone has none),
fetch it once:

```bash
python -c "from jalraksha.dem import fetch_dem; print(fetch_dem(18.4436, 73.7686, domain_radius_km=30.0, cache_dir='./data'))"   # Khadakwasla, ~13 MB
python -c "from jalraksha.dem import fetch_dem; print(fetch_dem(30.3789, 78.4789, domain_radius_km=60.0, cache_dir='./data'))"   # Tehri, ~170 MB
```

`make_dataset.py` prints the exact `fetch_dem` command (with the right
lat/lon) if the DEM it expects isn't cached.

### Checking a dam location before trusting it

A dam's lat/lon is easy to get wrong by several kilometres even when it
"looks right" on paper — see the note in `jalraksha/presets.py` on the two
UTM coordinates this project's original spec supplied, both of which
resolved to a hillside, not a reservoir. Before generating a dataset for a
new or corrected location, run:

```bash
python tools/paraview/make_dataset.py --dam khadakwasla --locate-only --resolution 100
```

This builds the domain, reports the dam cell's own elevation, the downstream
flow bearing, and whether a real flat pool plateau exists upstream — and
writes nothing. If the bearing doesn't point toward the dam's known outflow,
or no plateau is found, correct the location with `--dam-lat`/`--dam-lon`
rather than editing the preset from memory.

## Render a static image

ParaView 6.2.0 is installed; `pvpython` is at
`/c/Program Files/ParaView 6.2.0/bin/pvpython` on this machine.

```bash
"/c/Program Files/ParaView 6.2.0/bin/pvpython" paraview/render_static.py \
    --xdmf data/simulation/khadakwasla_reservoir.xdmf \
    --with-water --water-solid --focus-water \
    --exaggeration 2.0 --depth-max 18.5 \
    --out paraview/artifacts/phase3_khadakwasla_reservoir.png
```

`make_dataset.py` prints the exact matching render command (with the
preset's own exaggeration/depth-max) after every run — `render_static.py`
itself has no dam-specific knowledge and works unchanged for both presets.

### Scientific overlays and the terrain block

```bash
# Build the base block once per dataset (skirt + bottom cap, its own .vtp)
python tools/paraview/base_block.py --dataset data/simulation/tehri.xdmf

"/c/Program Files/ParaView 6.2.0/bin/pvpython" paraview/render_static.py \
    --xdmf data/simulation/tehri.xdmf \
    --with-water --glyphs --show-area \
    --base-block data/simulation/tehri_base.vtp \
    --camera isometric --time 10800 \
    --save-state paraview/state/tehri_animation.pvsm \
    --out paraview/artifacts/phase7_flood_t10800s.png
```

| Flag | Effect |
| :--- | :--- |
| `--base-block PATH` | Solid pedestal under the terrain (Section 4). Build it with `tools/paraview/base_block.py`. Warped with the same Scale Factor as the terrain, so one file works at any `--exaggeration`. |
| `--glyphs` | Velocity arrows on wet cells. `--glyph-stride` / `--glyph-scale` default to **auto** (≈400 arrows; longest ≈2.5% of the domain diagonal). Auto-skips, with a printed reason, when max \|v\| is 0. |
| `--show-area` | On-frame flooded area in km², counted at the canonical 0.01 m wet/dry cutoff. |
| `--camera NAME` | `perspective` (default), `isometric`, `oblique_low`, `top`. Byte-identical across runs. |
| `--elevation-range MIN MAX` | Fixed terrain colour range, so a colour means the same height on both dams. |
| `--save-state PATH` | Write a `.pvsm` with the Animation View already in Sequence mode — open it in the GUI to scrub (Phase 5). |

The **SYNTHETIC DATA banner is not a flag.** It is driven by the dataset's own
`is_synthetic` field data, so any frame rendered from demo data carries the
warning and it cannot be switched off independently of the data it describes
(spec Section 0).

## Run the dashboard

Two processes. Both are defined in `.claude/launch.json`, or run them directly:

```bash
python scripts/run_api.py          # http://localhost:8000
npm run dev --prefix frontend      # http://localhost:3000
```

`scripts/run_api.py` sets `CELERY_EAGER=1` (tasks run in-process, no Redis
needed) and `JALRAKSHA_DATA_DIR`, and pins the working directory to the repo
root — the export paths in `data/jalraksha.db` are relative and are resolved
against the process CWD, so starting the API elsewhere silently breaks every
`/files/...` URL.

Starting only the frontend makes a working system look dead: every API call
fails, and the dam dropdown swallows the error and renders empty.

### View a run in the ParaView desktop app

Once a run is loaded, the control panel shows **View in ParaView (3D)**. It asks
the API to write a per-run `.pvsm` (via `pvpython render_static.py --save-state`)
and then launches `paraview.exe` on it, so the scene opens with terrain warp,
water surface, glyphs and overlays already built — not a bare reader.

This only works when the API runs on the **same machine as the browser**: it
opens a desktop window on the API's host. Under `docker-compose` the api
container is headless Linux with no ParaView, and the endpoint says so rather
than hanging. Override the executable with `JALRAKSHA_PARAVIEW_EXE`.

Only `solver="swe"` runs get a dataset — `delft3d`/`both` produce an analytic
estimate with no depth series. Runs created before this feature existed cannot
be given one retroactively (the solver output is not persisted); re-create them,
or re-run the solver for them:

```bash
python scripts/backfill_xdmf.py --list
```

Clicking the button twice opens a second ParaView window, which is intentional.

To see a flood without waiting for a solve, paste a pre-baked run id into
**Load run id…**. Ids with keyframes:

```bash
python -c "import sqlite3;c=sqlite3.connect('data/jalraksha.db');print([r[0] for r in c.execute(\"select run_id from exports where kind='keyframe_manifest'\")])"
```

## Open it in ParaView (GUI)

1. **File > Open** → `data/simulation/<dam>_synthetic.xdmf`. If prompted for a
   reader, either XDMF reader works.
2. Press **Apply**.
3. Confirm the **Information** panel reports the expected number of time steps —
   30 for the synthetic dataset. One time step means the file is not a series and
   nothing downstream will animate.
4. Select the reader in the Pipeline Browser and apply **Filters > Alphabetical >
   Warp By Scalar**:
   - Scalars = `terrain_elevation`
   - Scale Factor = vertical exaggeration (the preset's default, or start at
     `1` and raise to taste)
   - **Apply**. Rotate the view — if elevation is not visible, nothing else in the
     appearance settings will help.
5. Colour by `water_depth`, and in the Color Map Editor **rescale to a custom
   range** (e.g. 0–25 m) rather than letting it auto-scale per time step, or the
   colours will not be comparable across the animation.
6. **Filters > Threshold** on `water_depth`, lower limit ≈ `0.01`, so dry cells
   stop rendering as a thin film over the whole domain.
7. Press **Play** on the VCR toolbar, or drag the time slider.

## Important

Datasets carry an `is_synthetic` flag as field data. When it is `1` the water is
**not a physical simulation** — it is a spreading depth profile masked to valley
floors, used to exercise the pipeline. Add a Python Annotation filter reading that
field data so the label travels with the scene, and never present such a run as a
result.

A `--reservoir` dataset is likewise **not a hydrodynamic result** — see its
`provenance/solver` field and the printed `[reservoir] FRL source:` line for
whether the fill level came from a preset literal (itself UNVETTED for both
dams — see `jalraksha/presets.py`) or was derived from the DEM's own pool
surface.

```bash
python -c "import h5py; f=h5py.File('data/simulation/tehri_synthetic.h5'); print('is_synthetic =', f.attrs['is_synthetic'])"
```

## Layout

```
jalraksha/presets.py               dam presets (Khadakwasla, Tehri)
jalraksha/export/xdmf_export.py    the Section 6 contract (writer)
tools/paraview/make_dataset.py     CLI: --dam | --terrain-only | --reservoir | --synthetic | real
tools/paraview/reservoir.py        static reservoir fill + DEM-derived FRL estimate
tools/paraview/synthetic_flood.py  labelled synthetic generator
tools/paraview/base_block.py       skirt + bottom cap as a standalone .vtp
paraview/render_static.py          pvpython: reader -> warp -> overlays -> camera -> SaveScreenshot
paraview/camera_presets.py         named reproducible cameras (Section 13)
paraview/state/                    saved .pvsm scenes (Sequence mode, for GUI scrubbing)
scripts/run_api.py                 starts the dashboard API with the right env + CWD
tests/test_presets.py              preset coordinate/config regression pins
tests/test_xdmf_export.py          12 checks, incl. VTK round-trip
data/simulation/                   output (gitignored)
paraview/artifacts/                rendered PNGs (gitignored contents; committed as proof artifacts)
paraview/ARCHITECTURE.md           format and CRS decisions
paraview/IMPLEMENTATION_PLAN.md    phase checklist
```
