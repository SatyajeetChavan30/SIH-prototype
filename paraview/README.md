# ParaView flood visualization

3D terrain + time-varying flood for the Tehri dam-break case, from real
Copernicus GLO-30 DEM and a validated shallow-water solver.

## Status

| Half | State |
|---|---|
| Data layer — DEM → XDMF+HDF5 time series | **working and verified** |
| ParaView layer — pipeline, render, video | not built (ParaView not installed) |

The data layer is verified against ParaView's own reader family via `vtk`, so the
files are known to load correctly before ParaView is installed. See
[ARCHITECTURE.md](ARCHITECTURE.md) for why each format decision was made.

## Generate a dataset

From the repository root. Output lands in `data/simulation/`.

Terrain only — no solver, no water. Seconds:

```bash
python tools/paraview/make_dataset.py --terrain-only
```

Real terrain with **synthetic** water, 30 timesteps. Seconds:

```bash
python tools/paraview/make_dataset.py --synthetic --duration 3600 --frames 30
```

Real terrain with the **validated solver**. Minutes to hours:

```bash
python tools/paraview/make_dataset.py --duration 10800 --resolution 400 --frames 60
```

If the DEM is missing (`data/` is gitignored, so a fresh clone has none), fetch it
once — about 170 MB:

```bash
python -c "from jalraksha.dem import fetch_dem; print(fetch_dem(30.3789, 78.4789, domain_radius_km=60.0, cache_dir='./data'))"
```

## Open it in ParaView

1. **File > Open** → `data/simulation/synthetic.xdmf`. If prompted for a reader,
   either XDMF reader works.
2. Press **Apply**.
3. Confirm the **Information** panel reports the expected number of time steps —
   30 for the synthetic dataset. One time step means the file is not a series and
   nothing downstream will animate.
4. Select the reader in the Pipeline Browser and apply **Filters > Alphabetical >
   Warp By Scalar**:
   - Scalars = `terrain_elevation`
   - Scale Factor = vertical exaggeration (start at `1`, raise to taste)
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

`--synthetic` sets the flag; the default (real solver) clears it. Verify with:

```bash
python -c "import h5py; f=h5py.File('data/simulation/synthetic.h5'); print('is_synthetic =', f.attrs['is_synthetic'])"
```

## Layout

```
jalraksha/export/xdmf_export.py    the Section 6 contract (writer)
tools/paraview/make_dataset.py     CLI: --terrain-only | --synthetic | real
tools/paraview/synthetic_flood.py  labelled synthetic generator
tests/test_xdmf_export.py          12 checks, incl. VTK round-trip
data/simulation/                   output (gitignored)
paraview/ARCHITECTURE.md           format and CRS decisions
paraview/IMPLEMENTATION_PLAN.md    phase checklist
```
