# Architecture — ParaView flood visualization

Answers the ten questions in spec Section 21, and records the decisions so they
do not have to be re-derived.

## 1. Tool roles

| Stage | Tool | Status |
|---|---|---|
| DEM reprojection, clipping, NoData fill | `rasterio` via `jalraksha/terrain/conditioning.py` | working |
| Hydrodynamics | `jalraksha/solver/` — HLLC + Audusse, well-balanced | working, 27 blocking gates pass |
| Synthetic stand-in water | `tools/paraview/synthetic_flood.py` | working, labelled |
| Time-series writer | `jalraksha/export/xdmf_export.py` (h5py + `xml.etree`) | working, 12 tests |
| 3D visualization, filters, camera, timeline | **ParaView** | not installed yet |
| Reproducible batch render | pvpython / pvbatch | deferred |
| Video encode | FFmpeg | not installed yet |
| Cinematic pass | Blender | not used; not a dependency |

## 2. Dependencies

Writing the dataset needs **`h5py` + `numpy` only**, both already present. That is
deliberate: XDMF is XML pointing into HDF5, so there is nothing to gain from
PyVista (which writes VTK formats, not XDMF) or `meshio` (awkward for a structured
time series). `rasterio` and `scipy` come in via the existing terrain path.

`vtk` is installed **for verification only** — `vtkXdmfReader` is the same reader
family ParaView uses, so `tests/test_xdmf_export.py` proves ParaView will accept
the file before ParaView is installed. Nothing at runtime imports it.

## 3. File format: XDMF 3.0 + HDF5, and why

Section 6 requires one static geometry referenced by many timesteps without
per-step duplication. XDMF expresses exactly that; a `.pvd` + `.vtu` series would
re-serialise the terrain into every file.

```
<stem>.h5
  /terrain_elevation          (1, ny, nx)     float32   ONE dataset
  /water_depth/0000..N        (1, ny, nx)     float32
  /velocity/0000..N           (1, ny, nx, 3)  float32   vector, for Glyph
  /velocity_magnitude/0000..N (1, ny, nx)     float32
  attrs: crs, is_synthetic, x0, y0, dx, dy, nx, ny, git_sha, created_utc

<stem>.xdmf
  Topology  3DCoRectMesh  Dimensions="1 ny nx"   declared once, Reference'd
  Geometry  ORIGIN_DXDYDZ (0, y0, x0), (1, dy, dx)
  Grid Collection Temporal
    Grid t=0 ... Attribute terrain_elevation -> <stem>.h5:/terrain_elevation
```

### Two decisions that were measured, not assumed

**A 3D slab of thickness 1, not `2DCoRectMesh`.** With `2DCoRectMesh` the reader
mapped easting/northing onto VTK's **Y and Z** axes and left X degenerate —
bounds came back `x=(0,0)`. The terrain would have stood vertically and Warp By
Scalar would have displaced it sideways. Declaring the singleton Z explicitly
yields `dimensions (nx, ny, 1)` and bounds in the expected axes.

**HDF5 datasets carry the same leading singleton.** The reader compares the HDF5
dataspace against the DataItem `Dimensions` and rejects any mismatch. With
`(ny, nx)` data against a `1 ny nx` mesh, the 3-component velocity array failed to
load at all (`selection + offset not within extent for file dataspace`) while the
scalars happened to survive. Matching them exactly fixes it. Consumers wanting a
plain 2D field index `[0]`.

`velocity` is a genuine 3-component vector because ParaView's Glyph filter
requires one; Z is zero because this is a depth-averaged 2D solver and inventing a
vertical component would fabricate physics that was never solved.

## 4. DEM entry and the CRS convention

```
Copernicus GLO-30 GeoTIFF (EPSG:4326)
  -> jalraksha/dem.py::fetch_dem()          windowed /vsicurl read, mosaic, clip
  -> conditioning.py::load_dem_as_grid()    reproject to auto-detected UTM,
                                            nearest-valid NoData fill
  -> Grid(nx, ny, dx, dy, x0, y0, crs)      metres throughout
  -> xdmf_export                            crs recorded in the file
```

**One projected CRS end to end.** Tehri resolves to **EPSG:32644** (UTM 44N).
Degrees do not survive past `load_dem_as_grid`; every coordinate in every dataset
is metres in that CRS. It is stored as an HDF5 attribute and an XDMF
`<Information>` element so it is inspectable rather than assumed.

**Orientation.** Row 0 is the **southernmost** row, because
`Grid.cell_centres_y()` increases northward. `ORIGIN_DXDYDZ` places the origin at
the first row, so a positive `dy` from `y0` is consistent. This is not a
hypothetical: the same mismatch rendered this project's keyframe PNGs
upside-down once already. The writer asserts increasing axes, and a test pins
`point 0 == terrain[0,0]`, `point NX == terrain[1,0]`.

**Smoothing is off by default.** Measured against the 30 m source, an isotropic
Gaussian roughly doubled valley-floor error (Devprayag +61.8 m → +140.3 m at
400 m) because it blends the channel with the canyon walls above it. See
`conditioning.py::load_dem_as_grid`.

**Vertical exaggeration is not baked in.** It is Warp By Scalar's Scale Factor in
ParaView, so it can be changed without regenerating data.

## 5. Solver data entry

Two producers, one contract; the ParaView pipeline cannot tell them apart.

- **Synthetic** — `tools/paraview/synthetic_flood.py`. A depth profile that
  attenuates with distance and is masked to valley floors, over *real* terrain.
  No mass conservation, no momentum: a pipeline exercise. Sets `is_synthetic=1`.
- **Real** — `run_dam_break_ensemble(record_depth_snapshots=True)`, adapted by
  `frames_from_result()`. Sets `is_synthetic=0`.

`frames_from_result` raises if a snapshot lacks velocity rather than exporting
zeros, because zeros would render as still water — a wrong result that looks fine.

## 6. Animation mode for the exported video

**Sequence** mode, not Snap To TimeSteps. Solver output is sparse and unevenly
spaced (adaptive CFL timestep); Sequence divides the duration into N evenly spaced
frames and interpolates between the bracketing real timesteps, giving a fixed
frame rate and fixed length. Snap To TimeSteps is for inspecting raw solver output.

ParaView performs that interpolation, so no custom interpolation code is written
(Section 18).

## 7. Static rendering path *(deferred until ParaView is installed)*

Set the scene time, then `SaveScreenshot()` in pvpython for repeatable exports at
named times. Timestamp via the **Annotate Time** filter, which reads the scene
clock, rather than a hand-drawn label that can silently drift out of sync.

## 8. Video rendering path *(deferred)*

`SaveAnimation()` writes a PNG per frame; FFmpeg encodes:

```
ffmpeg -framerate 30 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p flood_simulation.mp4
```

FFmpeg rather than ParaView's built-in encoder, for reliable configurable H.264.

## 9. The SYNTHETIC banner

`is_synthetic` travels **inside the dataset** as Grid-centred field data, verified
to survive the reader (a flag that does not arrive fails in the direction of
looking correct). In ParaView a Python Annotation filter reads that field data, so
the banner cannot be forgotten or removed independently of the data it describes.

## 10. What is not built yet

The pvpython layer — `build_pipeline.py`, `camera_presets.py`, `render_static.py`,
`render_animation.py`, `.pvsm` state — waits until ParaView is installed, so that
nothing ships unrun. The decisions above are settled; only the typing is pending.
