"""
UGRID network files for D-Flow FM (Phase 19: Delft3D integration).

D-Flow FM reads its computational mesh from a `*_net.nc` file in UGRID
convention — an unstructured description of nodes, edges and faces, even when
the mesh happens to be a regular quad grid. There is no structured-grid input
path in FM; the `.grd` files of Delft3D-4 belong to a different program.

WHY THIS MODULE EXISTS. `setup.py` previously wrote an INI stub for the mesh:

    [Grid]
    GridType = rectangular
    NX = 40
    ...

and named that file as the `.mdu`'s `NetFile`. Nothing in D-Flow FM can read
that, so every model the adapter produced would have died at mesh load. It was
never noticed because the kernel had never actually been run — the code path
that would have hit it was disabled by a hardcoded `force_fallback=True`.

CONVENTIONS THAT MUST HOLD. The mesh has to describe the SAME ground as the
solver grid, or the comparison it exists to support is meaningless:

  * Node coordinates are the grid's own metric CRS (CLAUDE.md: never degrees).
  * `Grid.x0/y0` is the domain's lower-left CORNER, so node (i, j) sits at
    (x0 + i*dx, y0 + j*dy) for i in 0..nx, j in 0..ny — one more node than
    cells in each direction.
  * Row order is SOUTH-UP, matching the solver (`terrain/conditioning.py`
    flips the north-up DEM to get there). Nothing is flipped here; UGRID is
    unstructured and carries explicit coordinates, so "row order" is only a
    statement about how the caller's bed_elevation array is indexed.
  * Connectivity indices are 1-based (`start_index = 1`), which is what
    D-Flow FM expects.

References:
  - Deltares (2024) "D-Flow Flexible Mesh User Manual", section on network
    files and the UGRID convention.
  - UGRID Conventions v1.0, https://ugrid-conventions.github.io/ugrid-conventions/
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np


class UgridError(ValueError):
    """The requested mesh cannot be written correctly."""


def quad_mesh_topology(nx: int, ny: int):
    """
    Node, edge and face connectivity for an nx-by-ny grid of quadrilaterals.

    Returns 0-BASED index arrays; the writer adds one when storing them.

    Args:
        nx, ny: Number of CELLS in x and y. Nodes are (nx+1) by (ny+1).

    Returns:
        (edge_nodes [n_edge, 2], face_nodes [n_face, 4])
    """
    if nx < 1 or ny < 1:
        raise UgridError(f"A mesh needs at least one cell; got nx={nx}, ny={ny}.")

    def node(i, j):
        """Flat 0-based node index for grid position (i, j)."""
        return j * (nx + 1) + i

    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="xy")
    ii, jj = ii.ravel(), jj.ravel()

    # Faces, counter-clockwise, as UGRID requires for a right-handed 2D mesh.
    face_nodes = np.column_stack([
        node(ii, jj),
        node(ii + 1, jj),
        node(ii + 1, jj + 1),
        node(ii, jj + 1),
    ])

    # Edges: every horizontal segment on each of the ny+1 node rows, then every
    # vertical segment on each of the nx+1 node columns. Listing them explicitly
    # (rather than deriving from faces) keeps interior edges unduplicated.
    hi, hj = np.meshgrid(np.arange(nx), np.arange(ny + 1), indexing="xy")
    horizontal = np.column_stack([node(hi.ravel(), hj.ravel()),
                                  node(hi.ravel() + 1, hj.ravel())])

    vi, vj = np.meshgrid(np.arange(nx + 1), np.arange(ny), indexing="xy")
    vertical = np.column_stack([node(vi.ravel(), vj.ravel()),
                                node(vi.ravel(), vj.ravel() + 1)])

    return np.vstack([horizontal, vertical]), face_nodes


def write_ugrid_net(
    path,
    grid_dict: Dict,
    bed_elevation: Optional[np.ndarray] = None,
    crs_epsg: Optional[int] = None,
    mesh_name: str = "mesh2d",
) -> Path:
    """
    Write a D-Flow FM `*_net.nc` mesh for a rectangular solver grid.

    Args:
        path: Output path. D-Flow FM conventionally expects a `_net.nc` suffix.
        grid_dict: {"nx","ny","dx","dy","x0","y0"} in metres. x0/y0 are the
            domain's lower-left CORNER.
        bed_elevation: Bed level per CELL, shaped [ny, nx], south-up. Averaged
            onto nodes for `mesh2d_node_z`. The `.mdu` must then declare a
            NODE-based bed level — `BedlevType=3` (mean of surrounding nodes).
            Declaring `BedlevType=1` (cell centres) against a node-based mesh
            makes the kernel abort with "bed-level type and conveyance type do
            not match".
            When omitted the mesh carries no z and the `.mdu` must supply a bed
            level another way.
        crs_epsg: Metric EPSG code, recorded for provenance.
        mesh_name: UGRID mesh variable name. D-Flow FM uses "mesh2d".

    Returns:
        The path written.

    Raises:
        UgridError: on a degenerate grid or a bed_elevation shape mismatch —
            rather than writing a mesh that silently describes other ground.
    """
    import netCDF4 as nc

    nx, ny = int(grid_dict["nx"]), int(grid_dict["ny"])
    dx, dy = float(grid_dict["dx"]), float(grid_dict["dy"])
    x0, y0 = float(grid_dict["x0"]), float(grid_dict["y0"])

    edge_nodes, face_nodes = quad_mesh_topology(nx, ny)

    node_x, node_y = np.meshgrid(x0 + np.arange(nx + 1) * dx,
                                 y0 + np.arange(ny + 1) * dy, indexing="xy")
    node_x, node_y = node_x.ravel(), node_y.ravel()
    n_node = node_x.size

    node_z = _cell_values_to_nodes(bed_elevation, nx, ny) if bed_elevation is not None else None

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ds = nc.Dataset(path, "w", format="NETCDF4")
    try:
        ds.Conventions = "CF-1.8 UGRID-1.0"
        ds.title = "JalRaksha dam-break mesh"
        ds.source = "jalraksha.delft3d.ugrid"
        ds.institution = "JalRaksha (SIH 2026, PS 26161)"
        if crs_epsg:
            ds.crs = f"EPSG:{crs_epsg}"

        ds.createDimension(f"n{mesh_name}_node", n_node)
        ds.createDimension(f"n{mesh_name}_edge", edge_nodes.shape[0])
        ds.createDimension(f"n{mesh_name}_face", face_nodes.shape[0])
        ds.createDimension(f"max_n{mesh_name}_face_nodes", 4)
        ds.createDimension("Two", 2)

        # The topology "dummy" variable. It holds no data; its ATTRIBUTES are
        # the mesh definition, and D-Flow FM navigates the file through them.
        topology = ds.createVariable(mesh_name, "i4", ())
        topology.cf_role = "mesh_topology"
        topology.long_name = "Topology data of 2D mesh"
        topology.topology_dimension = 2
        topology.node_coordinates = f"{mesh_name}_node_x {mesh_name}_node_y"
        topology.face_coordinates = f"{mesh_name}_face_x {mesh_name}_face_y"
        topology.node_dimension = f"n{mesh_name}_node"
        topology.edge_node_connectivity = f"{mesh_name}_edge_nodes"
        topology.edge_dimension = f"n{mesh_name}_edge"
        topology.face_node_connectivity = f"{mesh_name}_face_nodes"
        topology.face_dimension = f"n{mesh_name}_face"
        topology.max_face_nodes_dimension = f"max_n{mesh_name}_face_nodes"

        var_x = ds.createVariable(f"{mesh_name}_node_x", "f8", (f"n{mesh_name}_node",))
        var_x.standard_name = "projection_x_coordinate"
        var_x.long_name = "x-coordinate of mesh nodes"
        var_x.units = "m"
        var_x.mesh = mesh_name
        var_x.location = "node"
        var_x[:] = node_x

        var_y = ds.createVariable(f"{mesh_name}_node_y", "f8", (f"n{mesh_name}_node",))
        var_y.standard_name = "projection_y_coordinate"
        var_y.long_name = "y-coordinate of mesh nodes"
        var_y.units = "m"
        var_y.mesh = mesh_name
        var_y.location = "node"
        var_y[:] = node_y

        if node_z is not None:
            var_z = ds.createVariable(f"{mesh_name}_node_z", "f8",
                                      (f"n{mesh_name}_node",), fill_value=-999.0)
            var_z.standard_name = "altitude"
            var_z.long_name = "bed level at mesh nodes"
            var_z.units = "m"
            var_z.mesh = mesh_name
            var_z.location = "node"
            var_z.grid_mapping = "projected_coordinate_system"
            var_z[:] = node_z

        # Face centres. Without these the kernel logs "Could not read mesh face
        # x-coordinates" twice and falls back to deriving them; supplying them
        # is both cheaper and unambiguous.
        face_x = node_x[face_nodes].mean(axis=1)
        face_y = node_y[face_nodes].mean(axis=1)

        var_fx = ds.createVariable(f"{mesh_name}_face_x", "f8", (f"n{mesh_name}_face",))
        var_fx.standard_name = "projection_x_coordinate"
        var_fx.long_name = "x-coordinate of face centres"
        var_fx.units = "m"
        var_fx.mesh = mesh_name
        var_fx.location = "face"
        var_fx[:] = face_x

        var_fy = ds.createVariable(f"{mesh_name}_face_y", "f8", (f"n{mesh_name}_face",))
        var_fy.standard_name = "projection_y_coordinate"
        var_fy.long_name = "y-coordinate of face centres"
        var_fy.units = "m"
        var_fy.mesh = mesh_name
        var_fy.location = "face"
        var_fy[:] = face_y

        var_edges = ds.createVariable(f"{mesh_name}_edge_nodes", "i4",
                                      (f"n{mesh_name}_edge", "Two"))
        var_edges.cf_role = "edge_node_connectivity"
        var_edges.long_name = "Mapping from every edge to its two endpoints"
        var_edges.start_index = 1
        var_edges[:] = edge_nodes + 1

        var_faces = ds.createVariable(f"{mesh_name}_face_nodes", "i4",
                                      (f"n{mesh_name}_face", f"max_n{mesh_name}_face_nodes"),
                                      fill_value=-999)
        var_faces.cf_role = "face_node_connectivity"
        var_faces.long_name = "Mapping from every face to its corner nodes"
        var_faces.start_index = 1
        var_faces[:] = face_nodes + 1

        # D-Flow FM looks for a coordinate-system variable to decide whether the
        # mesh is projected (metres) or spherical (degrees). Getting this wrong
        # makes it interpret UTM eastings as longitudes.
        crs_var = ds.createVariable("projected_coordinate_system", "i4", ())
        # setncattr, not attribute assignment: netCDF4 reserves `name` on
        # Variable and rebinding it raises rather than writing an attribute.
        crs_var.setncattr("name", f"EPSG:{crs_epsg}" if crs_epsg else "Unknown projected")
        crs_var.setncattr("epsg", int(crs_epsg) if crs_epsg else 0)
        crs_var.setncattr("grid_mapping_name", "Unknown projected")
        crs_var.setncattr("proj4_params", "")
        crs_var.setncattr("EPSG_code", f"EPSG:{crs_epsg}" if crs_epsg else "")
        crs_var.setncattr("projection_name", "")
        crs_var.setncattr("wkt", "")
    finally:
        ds.close()

    return path


def _cell_values_to_nodes(cell_values: np.ndarray, nx: int, ny: int) -> np.ndarray:
    """
    Average a per-cell field onto mesh nodes.

    D-Flow FM's `BedlevType=1` reads bed level at nodes, while the solver (and
    the DEM it came from) carries it per cell. Interior nodes take the mean of
    the four cells touching them; edge and corner nodes the mean of what exists.

    Raises:
        UgridError: on a shape mismatch, rather than broadcasting a bed level
            that describes a different domain.
    """
    values = np.asarray(cell_values, dtype=np.float64)
    if values.shape != (ny, nx):
        raise UgridError(
            f"bed_elevation has shape {values.shape} but the grid is "
            f"({ny}, {nx}). Refusing to write a mesh whose bed level does not "
            f"match its own geometry."
        )

    # Pad by edge replication so boundary nodes average only real cells.
    padded = np.pad(values, 1, mode="edge")
    # Each node (i, j) touches padded cells [j:j+2, i:i+2].
    node_values = 0.25 * (padded[:-1, :-1] + padded[:-1, 1:]
                          + padded[1:, :-1] + padded[1:, 1:])
    return node_values.ravel()
