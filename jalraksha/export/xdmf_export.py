"""
Write a time-varying flood dataset as XDMF 3.0 + HDF5, for ParaView.

This is the solver-independent file contract (spec section 6). ParaView's job is
to visualize anything conforming to it; the solver's job is to produce it. Neither
needs to know about the other.

WHY XDMF RATHER THAN A VTK FORMAT
    The requirement is that one static geometry be referenced by many timesteps
    without duplicating it per step. XDMF expresses exactly that: the XML declares
    the topology and geometry once and each timestep's <Grid> References them,
    while the bulk arrays live in HDF5. A .pvd + .vtu series would re-serialise the
    terrain into every file.

    That also means the writer needs no VTK, no PyVista and no meshio — XDMF is XML
    pointing into HDF5, so h5py plus xml.etree is the whole dependency set. (VTK is
    used in the test suite to *read* the result back through ParaView's own reader,
    but nothing here depends on it.)

LAYOUT
    <stem>.h5
        /terrain_elevation        (ny, nx)     float32   written ONCE
        /water_depth/0000..N      (ny, nx)     float32
        /velocity/0000..N         (ny, nx, 3)  float32   vector, for Glyph
        /velocity_magnitude/0000..N (ny, nx)   float32
    <stem>.xdmf
        Topology/Geometry declared once, Reference'd by every timestep.

ORIENTATION — the failure this project has already had once
    Row 0 is the SOUTHERNMOST row, because Grid.cell_centres_y() increases
    northward. Image formats put row 0 at the top (north); that mismatch rendered
    this project's keyframe PNGs upside-down. XDMF ORIGIN_DXDY takes the origin at
    the FIRST row, so a positive dy from y0 is correct and consistent. The writer
    asserts increasing axes rather than leaving the reader to infer it.

    Note the ordering trap: ORIGIN_DXDY lists values as (Y, X) and Dimensions is
    slowest-first (ny, nx). Reversing either silently transposes the terrain.
"""

from __future__ import annotations

import datetime
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

# Visualization-only precision. The solver stays float64 (types.py precision
# policy); nothing rendered needs more than float32, and it halves the file.
EXPORT_DTYPE = np.float32

# Below this depth a cell is dry. ParaView's Threshold filter uses the same idea
# to stop dry cells rendering as a thin film over the whole domain.
DRY_DEPTH_M = 0.01


class XdmfExportError(Exception):
    """Raised when a simulation cannot be expressed in the XDMF contract."""


def _git_sha() -> str:
    """Short commit hash, so a dataset can be traced to the code that made it."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "unknown"


def _axes_from_grid(grid: Dict[str, Any]) -> tuple:
    """
    Cell-centre coordinate vectors in metres, both strictly increasing.

    Mirrors Grid.cell_centres_x/y (origin + (i + 0.5) * spacing) rather than
    inventing a different convention: a half-cell disagreement would offset the
    terrain against the water everywhere.
    """
    nx, ny = int(grid["nx"]), int(grid["ny"])
    dx, dy = float(grid["dx"]), float(grid["dy"])
    x0, y0 = float(grid.get("x0", 0.0)), float(grid.get("y0", 0.0))
    x = x0 + (np.arange(nx, dtype=np.float64) + 0.5) * dx
    y = y0 + (np.arange(ny, dtype=np.float64) + 0.5) * dy
    if not (np.all(np.diff(x) > 0) and np.all(np.diff(y) > 0)):
        raise XdmfExportError(
            "grid axes must be strictly increasing (metres). Row 0 must be the "
            "southernmost row; do not flip arrays before exporting."
        )
    return x, y


def _as_field(arr: Any, shape: tuple, label: str, idx: int) -> np.ndarray:
    """Coerce one snapshot field to EXPORT_DTYPE, failing loudly on shape drift."""
    a = np.asarray(arr, dtype=EXPORT_DTYPE)
    if a.shape != shape:
        raise XdmfExportError(
            f"snapshot {idx} field {label!r} has shape {a.shape}, expected {shape}"
        )
    return a


def _indent(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print in place — the .xdmf is meant to be human-inspectable."""
    pad = "\n" + "  " * level
    if len(elem):
        if not (elem.text or "").strip():
            elem.text = pad + "  "
        for child in elem:
            _indent(child, level + 1)
        if not (child.tail or "").strip():
            child.tail = pad
    if level and not (elem.tail or "").strip():
        elem.tail = pad


def _data_item(parent: ET.Element, dims: Sequence[int], h5_ref: str) -> ET.Element:
    """An HDF5-backed DataItem. Dimensions are slowest-first."""
    item = ET.SubElement(parent, "DataItem", {
        "Format": "HDF",
        "NumberType": "Float",
        "Precision": "4",
        "Dimensions": " ".join(str(int(d)) for d in dims),
    })
    item.text = h5_ref
    return item


def write_xdmf_series(
    out_stem: Path | str,
    grid: Dict[str, Any],
    terrain_elevation: np.ndarray,
    frames: Optional[List[Dict[str, Any]]] = None,
    *,
    is_synthetic: bool = False,
    provenance: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Write <stem>.h5 and <stem>.xdmf.

    Args:
        out_stem: Path without extension; both files are written beside it.
        grid: nx, ny, dx, dy, x0, y0, crs — as returned by run_dam_break_ensemble.
        terrain_elevation: (ny, nx) bed elevation, metres. Row 0 = south.
        frames: Per-timestep dicts with keys time_s, depth, velocity_x, velocity_y.
            None or empty writes a terrain-only dataset (one timestep, no water) —
            legitimate for the terrain-rendering phase, and announced rather than
            silently producing an empty water array.
        is_synthetic: True if ANY part of this dataset is fallback/synthetic. Stored
            in the file itself so a mislabeled dataset cannot be produced by
            forgetting a flag at render time.
        provenance: Extra strings recorded alongside; never load-bearing.

    Returns:
        Path to the written .xdmf.
    """
    import h5py

    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    h5_path = out_stem.with_suffix(".h5")
    xdmf_path = out_stem.with_suffix(".xdmf")

    nx, ny = int(grid["nx"]), int(grid["ny"])
    dx, dy = float(grid["dx"]), float(grid["dy"])
    x, y = _axes_from_grid(grid)
    shape = (ny, nx)

    terrain = np.asarray(terrain_elevation, dtype=EXPORT_DTYPE)
    if terrain.shape != shape:
        raise XdmfExportError(
            f"terrain_elevation shape {terrain.shape} does not match grid {shape}"
        )

    crs = str(grid.get("crs", ""))
    if "EPSG" not in crs.upper():
        raise XdmfExportError(
            f"grid crs {crs!r} is not an EPSG code. Everything downstream assumes a "
            f"projected metric CRS and performs no reprojection."
        )

    frames = list(frames or [])
    terrain_only = not frames
    if terrain_only:
        print(
            "[xdmf] No frames supplied — writing a TERRAIN-ONLY dataset "
            "(one timestep, zero water). This is expected for the terrain phase."
        )
        frames = [{
            "time_s": 0.0,
            "depth": np.zeros(shape, dtype=EXPORT_DTYPE),
            "velocity_x": np.zeros(shape, dtype=EXPORT_DTYPE),
            "velocity_y": np.zeros(shape, dtype=EXPORT_DTYPE),
        }]

    times = np.array([float(f["time_s"]) for f in frames], dtype=np.float64)
    if times.size > 1 and not np.all(np.diff(times) > 0):
        raise XdmfExportError(f"frame times are not strictly increasing: {times}")

    # ---------------------------------------------------------------- HDF5 ---
    with h5py.File(h5_path, "w") as h5:
        # Datasets carry a leading singleton Z to match the 3DCoRectMesh slab
        # declared in the XDMF. The reader compares HDF5 dataspace against the
        # DataItem Dimensions and rejects any mismatch, so these must agree
        # exactly. Consumers wanting the plain 2D field just index [0].
        def _slab(a: np.ndarray) -> np.ndarray:
            return a.reshape((1,) + a.shape)

        # Terrain: ONE dataset, referenced by every timestep in the XML below.
        h5.create_dataset("terrain_elevation", data=_slab(terrain), compression="gzip")

        g_depth = h5.create_group("water_depth")
        g_vel = h5.create_group("velocity")
        g_mag = h5.create_group("velocity_magnitude")

        for idx, frame in enumerate(frames):
            key = f"{idx:04d}"
            depth = _as_field(frame["depth"], shape, "depth", idx)
            vx = _as_field(frame.get("velocity_x", 0.0) if "velocity_x" in frame
                           else np.zeros(shape), shape, "velocity_x", idx)
            vy = _as_field(frame.get("velocity_y", 0.0) if "velocity_y" in frame
                           else np.zeros(shape), shape, "velocity_y", idx)

            # ParaView's Glyph filter needs a genuine 3-component vector; two
            # scalars would force the user to build one with a Calculator first.
            # Z is zero: this is a depth-averaged 2D solver, and pretending
            # otherwise would invent a vertical component that was never solved.
            vel = np.zeros(shape + (3,), dtype=EXPORT_DTYPE)
            vel[..., 0] = vx
            vel[..., 1] = vy

            g_depth.create_dataset(key, data=_slab(depth), compression="gzip")
            g_vel.create_dataset(key, data=_slab(vel), compression="gzip")
            g_mag.create_dataset(key, data=_slab(np.hypot(vx, vy)), compression="gzip")

        h5.attrs["crs"] = crs
        h5.attrs["is_synthetic"] = int(bool(is_synthetic))
        h5.attrs["x0"], h5.attrs["y0"] = float(x[0]), float(y[0])
        h5.attrs["dx"], h5.attrs["dy"] = dx, dy
        h5.attrs["nx"], h5.attrs["ny"] = nx, ny
        h5.attrs["dry_depth_m"] = DRY_DEPTH_M
        h5.attrs["created_utc"] = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        h5.attrs["git_sha"] = _git_sha()
        h5.attrs["terrain_only"] = int(terrain_only)
        for key, value in (provenance or {}).items():
            h5.attrs[f"provenance_{key}"] = str(value)

    # ---------------------------------------------------------------- XDMF ---
    h5_name = h5_path.name
    xdmf = ET.Element("Xdmf", {"Version": "3.0"})
    domain = ET.SubElement(xdmf, "Domain")

    # Declared once at Domain level; each timestep References these rather than
    # repeating them. This is the whole reason for choosing XDMF (section 6).
    #
    # A 3D slab of thickness 1, NOT 2DCoRectMesh. Measured: with 2DCoRectMesh the
    # XDMF2 reader mapped easting/northing onto VTK's Y/Z axes and left X
    # degenerate (bounds came back x=(0,0)), so the terrain stood vertically and
    # Warp By Scalar would have displaced it sideways. Declaring the singleton Z
    # explicitly removes the ambiguity and yields bounds in the expected axes.
    ET.SubElement(domain, "Topology", {
        "name": "topo",
        "TopologyType": "3DCoRectMesh",
        "Dimensions": f"1 {ny} {nx}",          # slowest-first: Z, Y, X
    })
    geom = ET.SubElement(domain, "Geometry", {
        "name": "geo",
        "GeometryType": "ORIGIN_DXDYDZ",
    })
    # Ordered (Z, Y, X) — not (X, Y, Z).
    origin = ET.SubElement(geom, "DataItem",
                           {"Format": "XML", "Dimensions": "3", "NumberType": "Float"})
    origin.text = f"0.0 {y[0]:.6f} {x[0]:.6f}"
    spacing = ET.SubElement(geom, "DataItem",
                            {"Format": "XML", "Dimensions": "3", "NumberType": "Float"})
    # dz is arbitrary for a single layer; 1.0 keeps the slab from being degenerate.
    spacing.text = f"1.0 {dy:.6f} {dx:.6f}"

    collection = ET.SubElement(domain, "Grid", {
        "Name": "TimeSeries",
        "GridType": "Collection",
        "CollectionType": "Temporal",
    })

    for idx, t in enumerate(times):
        key = f"{idx:04d}"
        step = ET.SubElement(collection, "Grid",
                             {"Name": f"t{key}", "GridType": "Uniform"})
        ET.SubElement(step, "Topology",
                      {"Reference": "/Xdmf/Domain/Topology[@name='topo']"})
        ET.SubElement(step, "Geometry",
                      {"Reference": "/Xdmf/Domain/Geometry[@name='geo']"})
        ET.SubElement(step, "Time", {"Value": f"{t:.6f}"})

        # DataItem dimensions must match the HDF5 datasets exactly, including the
        # singleton Z — a mismatch is what made the reader reject the vector array
        # ("selection + offset not within extent for file dataspace").
        slab = (1, ny, nx)

        # Same HDF5 dataset in every step — stored once, referenced N times.
        attr = ET.SubElement(step, "Attribute", {
            "Name": "terrain_elevation", "AttributeType": "Scalar", "Center": "Node"})
        _data_item(attr, slab, f"{h5_name}:/terrain_elevation")

        attr = ET.SubElement(step, "Attribute", {
            "Name": "water_depth", "AttributeType": "Scalar", "Center": "Node"})
        _data_item(attr, slab, f"{h5_name}:/water_depth/{key}")

        attr = ET.SubElement(step, "Attribute", {
            "Name": "velocity", "AttributeType": "Vector", "Center": "Node"})
        _data_item(attr, slab + (3,), f"{h5_name}:/velocity/{key}")

        attr = ET.SubElement(step, "Attribute", {
            "Name": "velocity_magnitude", "AttributeType": "Scalar", "Center": "Node"})
        _data_item(attr, slab, f"{h5_name}:/velocity_magnitude/{key}")

        # Grid-centred attributes arrive in ParaView as field data. is_synthetic
        # drives the mandatory SYNTHETIC annotation, so it travels inside the
        # dataset rather than depending on anyone remembering a checkbox.
        attr = ET.SubElement(step, "Attribute", {
            "Name": "is_synthetic", "AttributeType": "Scalar", "Center": "Grid"})
        item = ET.SubElement(attr, "DataItem", {
            "Format": "XML", "Dimensions": "1", "NumberType": "Int"})
        item.text = str(int(bool(is_synthetic)))

        ET.SubElement(step, "Information", {"Name": "crs", "Value": crs})

    _indent(xdmf)
    ET.ElementTree(xdmf).write(xdmf_path, encoding="utf-8", xml_declaration=True)

    nt = int(times.size)
    size_mb = (h5_path.stat().st_size + xdmf_path.stat().st_size) / 1e6
    depth_max = max(float(np.asarray(f["depth"]).max()) for f in frames)
    # Describe what this actually is. Keying the label off is_synthetic alone
    # printed "[real solver]" for a static geometric fill, and "(terrain only)"
    # for any single-timestep dataset even when it carried water — both are the
    # kind of confident-but-wrong label this project keeps having to hunt down.
    label = ("SYNTHETIC" if is_synthetic
             else str((provenance or {}).get("solver", "unlabelled source")))
    if nt > 1:
        span = f", t = {times[0]:.0f}..{times[-1]:.0f} s"
    elif depth_max > 0.0:
        span = " (single state, with water)"
    else:
        span = " (terrain only, no water)"
    print(
        f"[xdmf] {xdmf_path.name} + {h5_name}  ({size_mb:.1f} MB)\n"
        f"  grid {ny} x {nx} @ {dx:.0f} m   {crs}\n"
        f"  {nt} timestep(s)"
        + span
        + f"\n  terrain {terrain.min():.1f}..{terrain.max():.1f} m"
          f"   max depth {depth_max:.2f} m"
          f"\n  source: {label}"
    )
    return xdmf_path


def frames_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Adapt run_dam_break_ensemble()'s depth_series to the frame contract.

    Velocity capture was added to solver/parallel.py::_snapshot; a run recorded
    before that change carries depth only and cannot supply Glyph vectors, so say
    so rather than silently exporting zeros that look like still water.
    """
    series = result.get("depth_series") or []
    frames = []
    for idx, snap in enumerate(series):
        if "velocity_x" not in snap or "velocity_y" not in snap:
            raise XdmfExportError(
                f"snapshot {idx} has no velocity. It predates the velocity capture "
                f"in jalraksha/solver/parallel.py::_snapshot — re-run the simulation."
            )
        frames.append({
            "time_s": snap["time_s"],
            "depth": snap["depth"],
            "velocity_x": snap["velocity_x"],
            "velocity_y": snap["velocity_y"],
        })
    return frames
