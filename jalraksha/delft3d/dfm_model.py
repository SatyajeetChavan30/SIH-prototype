"""
Build a runnable D-Flow FM dam-break model (Phase 19: Delft3D integration).

Produces the complete input set the real `dflowfm-cli` kernel needs:

    <name>_net.nc      UGRID mesh with bed level on nodes (jalraksha.delft3d.ugrid)
    <name>.mdu         master definition
    initial.ini        initial-field definition, pointing at...
    waterlevel.xyz     ...a dense sample set carrying the dam-break step
    <name>_obs.xyn     observation points, so the kernel writes a _his.nc
    dimr_config.xml    DIMR wrapper, for running via dimr.exe

EVERY VALUE BELOW WAS SETTLED BY RUNNING THE KERNEL, not by reading docs. The
combinations that do not work are recorded because they fail in ways that look
like something else:

  * `BedlevType = 1` against a mesh carrying node z aborts with "bed-level type
    and conveyance type do not match". Node bed levels need **BedlevType 3**.
  * A UGRID mesh without face coordinates still loads, but logs "Could not read
    mesh face x-coordinates" twice and derives them itself. `ugrid.py` writes
    them.
  * A *uniform* `WaterLevIni` over a sloping bed is a lake at rest — the kernel
    correctly holds it static forever. A dam break needs a water-level STEP,
    which is what the sample file plus `IniFieldFile` provides. Verified: the
    step is reproduced exactly at t=0 (10.000 m upstream, 0.000 downstream).

References:
  - Deltares (2024) "D-Flow Flexible Mesh User Manual", MDU reference.
  - Ritter, A. (1892) "Die Fortpflanzung der Wasserwellen", VDI Zeitschrift
    36(33):947-954.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from jalraksha.delft3d.ugrid import write_ugrid_net

#: Bed level defined at net nodes, averaged onto cells. The only value
#: compatible with a mesh that carries `mesh2d_node_z` — see module docstring.
BEDLEVTYPE_NODES = 3


def build_dfm_model(
    output_dir,
    grid_dict: Dict,
    bed_elevation: np.ndarray,
    initial_water_level: np.ndarray,
    duration_s: float,
    name: str = "dambreak",
    manning_n: float = 0.023,
    crs_epsg: Optional[int] = None,
    observation_points: Optional[Sequence[Dict]] = None,
    map_interval_s: Optional[float] = None,
    cfl_max: float = 0.7,
) -> Dict:
    """
    Write a complete, runnable D-Flow FM model for a dam-break scenario.

    Args:
        output_dir: Directory to write the model into.
        grid_dict: {"nx","ny","dx","dy","x0","y0"} in metres; x0/y0 is the
            domain's lower-left CORNER.
        bed_elevation: Bed level per cell [ny, nx], south-up, metres.
        initial_water_level: Initial WATER SURFACE elevation per cell [ny, nx],
            metres (not depth). Cells where this equals the bed start dry — that
            discontinuity is the dam break.
        duration_s: Simulated duration.
        name: Model basename.
        manning_n: Uniform Manning coefficient. Pass 0.0 for a frictionless
            benchmark such as Ritter.
        crs_epsg: Metric EPSG code, recorded in the mesh.
        observation_points: [{"name","x","y"}] written to a `.xyn`, which makes
            the kernel emit per-point time series in `<name>_his.nc`.
        map_interval_s: Map output interval. Defaults to ~30 frames.
        cfl_max: Courant limit.

    Returns:
        Dict of the paths written, plus `mdu_path` and `grid`.

    Raises:
        ValueError: on a shape mismatch between the grid and either field.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nx, ny = int(grid_dict["nx"]), int(grid_dict["ny"])
    bed = np.asarray(bed_elevation, dtype=np.float64)
    water = np.asarray(initial_water_level, dtype=np.float64)
    for label, array in (("bed_elevation", bed), ("initial_water_level", water)):
        if array.shape != (ny, nx):
            raise ValueError(
                f"{label} has shape {array.shape} but the grid is ({ny}, {nx}). "
                f"Refusing to build a model whose fields describe different ground."
            )

    net_path = write_ugrid_net(output_dir / f"{name}_net.nc", grid_dict,
                               bed_elevation=bed, crs_epsg=crs_epsg)

    # Initial water level as one sample per cell centre. Dense enough that
    # triangulation reproduces a sharp step rather than smearing it across the
    # domain — confirmed against the kernel, which returns the step exactly.
    dx, dy = float(grid_dict["dx"]), float(grid_dict["dy"])
    x0, y0 = float(grid_dict["x0"]), float(grid_dict["y0"])
    xs = x0 + (np.arange(nx) + 0.5) * dx
    ys = y0 + (np.arange(ny) + 0.5) * dy

    sample_path = output_dir / "waterlevel.xyz"
    with sample_path.open("w", encoding="utf-8") as handle:
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                handle.write(f"{x:.4f} {y:.4f} {water[j, i]:.6f}\n")

    inifield_path = output_dir / "initial.ini"
    inifield_path.write_text(
        "[General]\n"
        "fileVersion = 2.00\n"
        "fileType    = iniField\n"
        "\n"
        "[Initial]\n"
        "quantity            = waterlevel\n"
        "dataFile            = waterlevel.xyz\n"
        "dataFileType        = sample\n"
        "interpolationMethod = triangulation\n"
        "operand             = O\n",
        encoding="utf-8")

    obs_path = None
    if observation_points:
        obs_path = output_dir / f"{name}_obs.xyn"
        obs_path.write_text(
            "".join(f"{p['x']:.4f} {p['y']:.4f} '{p['name']}'\n"
                    for p in observation_points),
            encoding="utf-8")

    if map_interval_s is None:
        map_interval_s = max(duration_s / 30.0, 1.0)

    mdu_path = output_dir / f"{name}.mdu"
    mdu_path.write_text(_render_mdu(
        name=name, net_file=net_path.name, obs_file=obs_path.name if obs_path else None,
        duration_s=duration_s, manning_n=manning_n, cfl_max=cfl_max,
        map_interval_s=map_interval_s,
    ), encoding="utf-8")

    dimr_path = output_dir / "dimr_config.xml"
    dimr_path.write_text(_render_dimr(name, mdu_path.name), encoding="utf-8")

    return {
        "mdu_path": mdu_path,
        "net_path": net_path,
        "sample_path": sample_path,
        "inifield_path": inifield_path,
        "obs_path": obs_path,
        "dimr_path": dimr_path,
        "output_dir": output_dir,
        "grid": dict(grid_dict),
        "name": name,
    }


def _render_mdu(name: str, net_file: str, obs_file: Optional[str],
                duration_s: float, manning_n: float, cfl_max: float,
                map_interval_s: float) -> str:
    """The master definition file."""
    obs_line = f"ObsFile               = {obs_file}\n" if obs_file else ""
    return f"""# D-Flow FM model generated by JalRaksha (SIH 2026, PS 26161)
# Dam-break scenario: {name}

[General]
fileVersion           = 1.09
fileType              = modelDef
Program               = D-Flow FM

[geometry]
NetFile               = {net_file}
# 3 = bed level at net NODES. Must match the mesh, which carries mesh2d_node_z;
# BedlevType = 1 aborts with "bed-level type and conveyance type do not match".
BedlevType            = {BEDLEVTYPE_NODES}
IniFieldFile          = initial.ini
WaterLevIni           = 0.0

[numerics]
CFLMax                = {cfl_max:.3f}

[physics]
UnifFrictCoef         = {manning_n:.5f}
UnifFrictType         = 1

[time]
RefDate               = 20260101
Tunit                 = S
DtUser                = {max(map_interval_s / 5.0, 1.0):.3f}
DtMax                 = {max(map_interval_s / 10.0, 0.5):.3f}
TStart                = 0.
TStop                 = {duration_s:.3f}

[output]
MapInterval           = {map_interval_s:.3f}
HisInterval           = {map_interval_s:.3f}
{obs_line}"""


def _render_dimr(name: str, mdu_file: str) -> str:
    """
    DIMR wrapper, so the model can also be launched through `dimr.exe`.

    Not required for a single-component FM model — `dflowfm-cli --autostartstop`
    runs it directly and is what the adapter uses — but DIMR is the documented
    Deltares entry point and costs almost nothing to emit.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<dimrConfig xmlns="http://schemas.deltares.nl/dimr"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="http://schemas.deltares.nl/dimr
                                http://content.oss.deltares.nl/schemas/dimr-1.3.xsd">
  <documentation>
    <fileVersion>1.3</fileVersion>
    <createdBy>JalRaksha (SIH 2026, PS 26161)</createdBy>
  </documentation>
  <control>
    <start name="{name}"/>
  </control>
  <component name="{name}">
    <library>dflowfm</library>
    <workingDir>.</workingDir>
    <inputFile>{mdu_file}</inputFile>
  </component>
</dimrConfig>
"""


def dam_break_fields(grid_dict: Dict, bed_elevation: np.ndarray,
                     reservoir_level_m: float, dam_index: int,
                     axis: str = "y") -> np.ndarray:
    """
    Initial water-surface field for a dam break: full upstream, dry downstream.

    Args:
        grid_dict: Grid definition.
        bed_elevation: Bed level per cell [ny, nx].
        reservoir_level_m: Water SURFACE elevation upstream of the barrier.
        dam_index: Cell index of the barrier along `axis`.
        axis: "y" for a barrier across the flow (the usual case), "x" otherwise.

    Returns:
        Water-surface elevation per cell [ny, nx]. Downstream cells are set to
        their own bed level, i.e. zero depth — a genuinely dry bed rather than a
        thin film, which is what the Ritter solution assumes.
    """
    bed = np.asarray(bed_elevation, dtype=np.float64)
    level = bed.copy()

    if axis == "y":
        level[:dam_index, :] = reservoir_level_m
    else:
        level[:, :dam_index] = reservoir_level_m

    # Upstream cells whose bed already stands above the reservoir surface stay
    # dry; clamping keeps the level from dipping below the bed anywhere.
    return np.maximum(level, bed)
