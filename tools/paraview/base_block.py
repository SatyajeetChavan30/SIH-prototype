"""
Write the terrain's base block (skirt + bottom cap) as a standalone .vtp.

Spec Section 4 wants the terrain to read as a physical 3D block rather than a
floating sheet. The DEM dataset is a single-layer slab, so its warped surface
has no sides: viewed obliquely it is a bent sheet hanging in space.

Why a separate file rather than extra geometry in the XDMF:

  * `jalraksha/export/xdmf_export.py` has a contract pinned by 12 passing tests
    and consumed by the solver path. The base block is a *rendering* concern —
    baking it into the simulation dataset makes every consumer pay for geometry
    only the renderer wants.
  * ParaView-side extrusion of a heightfield boundary (Extract Surface ->
    Linear Extrusion) produces artifacts at the domain edge and cannot easily
    make a flat bottom cap.

Why the points are written at z=0 with a `terrain_elevation` scalar instead of
at their final height: `render_static.py` applies Warp By Scalar to the terrain
with a user-chosen Scale Factor (vertical exaggeration, never baked into data —
ARCHITECTURE.md section 4). If the skirt carried baked z values it would only
line up at one exaggeration and would visibly detach at any other. Carrying the
target elevation as a scalar and warping the skirt with the *same* factor keeps
the two locked together at every exaggeration, from one file.

Usage:
    python tools/paraview/base_block.py --dataset data/simulation/tehri_terrain.xdmf
    python tools/paraview/base_block.py --dataset data/simulation/tehri.h5 \
        --out data/simulation/tehri_base.vtp --base-drop-m 400
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _perimeter_indices(nx: int, ny: int) -> list[tuple[int, int]]:
    """Closed anticlockwise walk of the grid border, each (i, j) visited once."""
    ring: list[tuple[int, int]] = []
    ring += [(i, 0) for i in range(nx)]                       # south edge, west->east
    ring += [(nx - 1, j) for j in range(1, ny)]               # east edge, south->north
    ring += [(i, ny - 1) for i in range(nx - 2, -1, -1)]      # north edge, east->west
    ring += [(0, j) for j in range(ny - 2, 0, -1)]            # west edge, north->south
    return ring


def build_base_block(terrain: np.ndarray, grid: dict, base_drop_m: float | None = None):
    """
    Returns (points Nx3, scalars N, polys, info).

    `base_drop_m` is how far the flat bottom sits below the lowest terrain point.
    Default is 12% of the domain's relief, floored at 100 m: proportional so the
    block looks the same on Khadakwasla's ~300 m of relief as on Tehri's ~6500 m,
    and floored so a very flat domain still gets a visible side wall.
    """
    ny, nx = terrain.shape
    dx, dy = float(grid["dx"]), float(grid["dy"])
    x0, y0 = float(grid["x0"]), float(grid["y0"])

    elevation_min = float(np.nanmin(terrain))
    elevation_max = float(np.nanmax(terrain))
    if base_drop_m is None:
        # The block is a presentational pedestal, not a geological claim, so its
        # depth is chosen to READ as a solid block at a domain-wide camera.
        # Relief alone is not enough: on the 120 km Tehri domain, 12% of 6.5 km
        # of relief is a 780 m wall — under 1% of the frame width, which renders
        # as a hairline sliver rather than a block. Taking the larger of a share
        # of the relief and a share of the domain width keeps it substantial on
        # both a wide Himalayan domain and a small, low-relief one.
        domain_width_m = max(nx * dx, ny * dy)
        base_drop_m = max(0.30 * (elevation_max - elevation_min),
                          0.03 * domain_width_m,
                          100.0)
    base_level = elevation_min - float(base_drop_m)

    ring = _perimeter_indices(nx, ny)
    n_ring = len(ring)

    points: list[tuple[float, float, float]] = []
    scalars: list[float] = []
    # Two coincident rings in XY: the top follows the terrain, the bottom is flat.
    # Both are written at z=0; Warp By Scalar lifts them apart (see module docstring).
    for i, j in ring:
        points.append((x0 + i * dx, y0 + j * dy, 0.0))
        scalars.append(float(terrain[j, i]))
    for i, j in ring:
        points.append((x0 + i * dx, y0 + j * dy, 0.0))
        scalars.append(base_level)

    polys: list[list[int]] = []
    for k in range(n_ring):
        k_next = (k + 1) % n_ring          # wraps, closing the wall
        polys.append([k, k_next, n_ring + k_next, n_ring + k])

    # Bottom cap. Every bottom point is at the same level and the domain is
    # rectangular, so the four corners are enough — a polygon over all ~4800
    # perimeter points would be needlessly heavy and can render non-planar.
    corner_positions = [
        ring.index((0, 0)),
        ring.index((nx - 1, 0)),
        ring.index((nx - 1, ny - 1)),
        ring.index((0, ny - 1)),
    ]
    # Reversed so the cap's winding faces downward, away from the camera.
    polys.append([n_ring + p for p in reversed(corner_positions)])

    info = {
        "base_level": base_level,
        "base_drop_m": float(base_drop_m),
        "elevation_min": elevation_min,
        "elevation_max": elevation_max,
    }
    return (np.asarray(points, dtype=np.float32),
            np.asarray(scalars, dtype=np.float32),
            polys,
            info)


def _fmt(values, per_line: int, precision: int | None) -> str:
    """Wrap a flat sequence into indented ASCII lines for a VTK DataArray."""
    out: list[str] = []
    line: list[str] = []
    for count, value in enumerate(values, 1):
        line.append(str(value) if precision is None else f"{value:.{precision}f}")
        if count % per_line == 0:
            out.append(" ".join(line))
            line = []
    if line:
        out.append(" ".join(line))
    return "\n          ".join(out)


def write_vtp(path: Path, points: np.ndarray, scalars: np.ndarray,
              polys: list[list[int]]) -> None:
    """Minimal ASCII VTK XML PolyData — no vtk dependency on the writing side."""
    connectivity: list[int] = []
    offsets: list[int] = []
    running = 0
    for poly in polys:
        connectivity.extend(poly)
        running += len(poly)
        offsets.append(running)

    scalar_text = _fmt([float(s) for s in scalars], per_line=6, precision=4)
    point_text = _fmt([float(c) for c in points.ravel()], per_line=9, precision=3)
    conn_text = _fmt(connectivity, per_line=12, precision=None)
    offset_text = _fmt(offsets, per_line=12, precision=None)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            '<?xml version="1.0"?>\n'
            '<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian">\n'
            "  <PolyData>\n"
            f'    <Piece NumberOfPoints="{len(points)}" NumberOfVerts="0" '
            f'NumberOfLines="0" NumberOfStrips="0" NumberOfPolys="{len(polys)}">\n'
            '      <PointData Scalars="terrain_elevation">\n'
            '        <DataArray type="Float32" Name="terrain_elevation" format="ascii">\n'
            f"          {scalar_text}\n"
            "        </DataArray>\n"
            "      </PointData>\n"
            "      <Points>\n"
            '        <DataArray type="Float32" NumberOfComponents="3" format="ascii">\n'
            f"          {point_text}\n"
            "        </DataArray>\n"
            "      </Points>\n"
            "      <Polys>\n"
            '        <DataArray type="Int32" Name="connectivity" format="ascii">\n'
            f"          {conn_text}\n"
            "        </DataArray>\n"
            '        <DataArray type="Int32" Name="offsets" format="ascii">\n'
            f"          {offset_text}\n"
            "        </DataArray>\n"
            "      </Polys>\n"
            "    </Piece>\n"
            "  </PolyData>\n"
            "</VTKFile>\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True,
                        help="Path to the dataset .xdmf or its .h5 sibling.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output .vtp. Defaults to <dataset stem>_base.vtp.")
    parser.add_argument("--base-drop-m", type=float, default=None,
                        help="Depth of the block below the lowest terrain point. "
                             "Default: 12 percent of relief, floored at 100 m.")
    args = parser.parse_args()

    import h5py

    h5_path = args.dataset.with_suffix(".h5")
    if not h5_path.exists():
        raise SystemExit(f"No HDF5 alongside the dataset: {h5_path}")

    with h5py.File(h5_path, "r") as handle:
        if "terrain_elevation" not in handle:
            raise SystemExit(
                f"{h5_path} has no /terrain_elevation — not a JalRaksha XDMF dataset.")
        terrain = np.asarray(handle["terrain_elevation"][...], dtype=np.float64)
        # The dataset is a 3D slab of thickness 1 (xdmf_export declares a
        # singleton Z so the reader keeps easting/northing on X/Y), so the
        # stored array is (1, ny, nx). Drop the degenerate leading axis.
        terrain = np.squeeze(terrain)
        grid = {key: float(handle.attrs[key]) for key in ("dx", "dy", "x0", "y0")}

    points, scalars, polys, info = build_base_block(terrain, grid, args.base_drop_m)
    out_path = args.out or args.dataset.with_name(args.dataset.stem + "_base.vtp")
    write_vtp(out_path, points, scalars, polys)

    print(f"[base_block] wrote {out_path}")
    print(f"  terrain relief   : {info['elevation_min']:.1f} - {info['elevation_max']:.1f} m")
    print(f"  block base level : {info['base_level']:.1f} m "
          f"({info['base_drop_m']:.1f} m below the lowest cell)")
    print(f"  points / polys   : {len(points)} / {len(polys)}")


if __name__ == "__main__":
    main()
