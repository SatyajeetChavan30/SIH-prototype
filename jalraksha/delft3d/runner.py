"""
Delft3D FM Runner — Binary Execution + Fallback SWE Solver.

Two-tier execution:
  Tier A: Detects dflowfm binary → runs via subprocess → parses NetCDF output
  Tier B: Falls back to built-in 2D SWE solver (same Saint-Venant equations)

Both tiers return identical result dicts for downstream consumption.

References:
  - Deltares (2024) D-Flow FM Technical Reference Manual.
  - Toro (2001) Shock-Capturing Methods for Free-Surface Shallow Flows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import math
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional


def resolve_dflowfm(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Locate the dflowfm executable, returning the path that should be EXECUTED.

    Returning the path rather than a bare bool is the point. The previous
    arrangement had `is_dflowfm_available(custom_path)` honour an explicit
    location while `_run_dflowfm_binary` went on to invoke the literal string
    "dflowfm" — so an install pointed at by JALRAKSHA_DFLOWFM_EXE would be
    detected as present and then launched as a bare PATH lookup that fails.
    Detection and execution now agree by construction, because they use the
    same value.

    Args:
        custom_path: Explicit path to the executable (JALRAKSHA_DFLOWFM_EXE).
            An empty string means "not configured" and falls through to PATH.

    Returns:
        Absolute path to the executable, or None if there is none to run.
    """
    if custom_path:
        # An explicitly configured path that is wrong is a configuration error,
        # not a reason to quietly search PATH instead and run something else.
        if os.path.isfile(custom_path):
            return os.path.abspath(custom_path)
        print(
            f"[delft3d] JALRAKSHA_DFLOWFM_EXE points at {custom_path!r}, "
            f"which is not a file. Not falling back to PATH — fix the setting "
            f"or unset it."
        )
        return None

    # The FM Suite ships the executable as dflowfm-cli.exe, not "dflowfm".
    # Looking only for the latter is why a perfectly good local install went
    # undetected.
    for candidate in ("dflowfm-cli", "dflowfm"):
        found = shutil.which(candidate)
        if found:
            return found

    return _discover_installed_kernel()


#: Where the Deltares installers put the DIMR kernel set. The FM Suite nests it
#: under the DeltaShell plugin rather than in a top-level bin, so PATH lookups
#: never find it — every install needs either this search or an explicit
#: JALRAKSHA_DFLOWFM_EXE.
#:
#: Note that not every edition ships kernels at all: the "Open" editions
#: (e.g. 2026.02 OpenHMWQ) install the DeltaShell framework WITHOUT
#: plugins/DeltaShell.Dimr/kernels, so only the editions that have them match.
_KERNEL_GLOBS = (
    r"C:\Program Files\Deltares\*\plugins\DeltaShell.Dimr\kernels\x64\bin\dflowfm-cli.exe",
    r"C:\Program Files (x86)\Deltares\*\plugins\DeltaShell.Dimr\kernels\x64\bin\dflowfm-cli.exe",
    r"C:\Program Files\Deltares\*\x64\dflowfm\bin\dflowfm-cli.exe",
    # Some editions place the kernel directly under bin/ rather than under the
    # Dimr plugin tree. Added for completeness; on the machine this was written
    # for, the 2026.01 HM install matches the first pattern and 2026.02 OpenHMWQ
    # ships no kernel at all (see the note above), so this one currently matches
    # nothing. It costs one glob and covers an edition layout that does exist.
    r"C:\Program Files\Deltares\*\bin\dflowfm-cli.exe",
)


def _discover_installed_kernel() -> Optional[str]:
    """Find a Deltares kernel in the usual install locations."""
    import glob

    for pattern in _KERNEL_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            # Newest suite version last after a lexical sort of the install
            # names, which carry the year.version.
            chosen = matches[-1]
            print(f"[delft3d] Discovered Delft3D FM kernel: {chosen}")
            return chosen
    return None


def kernel_environment(executable: str) -> Dict[str, str]:
    r"""
    Environment the kernel needs to find its own libraries.

    `run_dflowfm.bat` sets `PATH = <root>\share;<root>\lib` before invoking
    the exe. Without it the process dies on missing DLLs, which surfaces as an
    opaque non-zero exit and no output at all.
    """
    env = dict(os.environ)
    bin_dir = Path(executable).parent
    root = bin_dir.parent
    share, lib = root / "share", root / "lib"
    if share.is_dir() and lib.is_dir():
        env["PATH"] = f"{share};{lib}"
    else:
        # Not the FM Suite layout; leave PATH alone and let the loader try.
        env["PATH"] = f"{bin_dir};{env.get('PATH', '')}"
    env.setdefault("OMP_NUM_THREADS", "1")
    return env


def is_dflowfm_available(custom_path: Optional[str] = None) -> bool:
    """Predicate form of resolve_dflowfm(), kept for callers that want a bool."""
    return resolve_dflowfm(custom_path) is not None


def _run_dflowfm_binary(
    mdu_path: Path,
    executable: str = "dflowfm",
    timeout_s: int = 3600,
) -> Dict:
    """
    Execute the dflowfm binary on the .mdu file.

    Args:
        mdu_path: Path to the .mdu master definition file.
        executable: The resolved executable to run (see resolve_dflowfm).
        timeout_s: Maximum runtime (seconds).

    Returns:
        Dict with execution status and output paths.
    """
    mdu_path = Path(mdu_path)
    work_dir = mdu_path.parent

    cmd = [executable, "--autostartstop", mdu_path.name]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=kernel_environment(executable),
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "output_dir": _resolve_output_dir(work_dir),
            "engine": "Delft3D_FM",
        }
    except FileNotFoundError:
        return {"success": False, "error": f"{executable!r} could not be executed",
                "engine": "none", "output_dir": work_dir}
    except OSError as exc:
        # e.g. the file exists but is not a valid executable for this platform.
        return {"success": False, "error": f"{executable!r}: {exc}",
                "engine": "none", "output_dir": work_dir}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout after {timeout_s}s",
                "engine": "none", "output_dir": work_dir}


def _ritter_gauge_arrivals(
    gauge_locations: Optional[List[Dict]],
    c_wave: float,
) -> Dict[str, Dict]:
    """
    Arrival times from Ritter wave celerity — a FORMULA, not a simulation result.

    t = distance / c, with c = 0.5*sqrt(g*H) (Ritter 1892, dry-bed dam-break
    front celerity). The +/-20% band is a nominal spread, not an uncertainty
    quantification.

    This is tagged `method: "ritter_celerity_estimate"` on every entry, and the
    tag is carried all the way to the dashboard, because these numbers are
    routinely produced by a run whose domain CANNOT REACH the gauges they
    describe: setup_delft3d_model is called at 40x40 cells of 30 m, a 1.2 km
    box, while the nearest Tehri gauge is 13 km downstream. Presenting a
    closed-form estimate beside solver output without saying which is which is
    precisely the overclaiming CLAUDE.md forbids.

    TODO: UNVETTED - the 0.5 coefficient is the classical Ritter dry-bed value
    and the +/-20% band has no cited source. Spec section 17 verification queue.
    """
    gauge_arrivals: Dict[str, Dict] = {}
    if not gauge_locations:
        return gauge_arrivals

    for gauge in gauge_locations:
        dist_km = gauge.get("distance_km", 10.0)
        name = gauge.get("name", f"Gauge_{dist_km:.0f}km")
        t_s = (dist_km * 1000.0) / c_wave
        spread = 0.2 * t_s
        gauge_arrivals[name] = {
            "median_s": round(t_s, 1),
            "median_min": round(t_s / 60.0, 1),
            "p05_min": round((t_s - spread) / 60.0, 1),
            "p95_min": round((t_s + spread) / 60.0, 1),
            "distance_km": dist_km,
            "method": "ritter_celerity_estimate",
        }
    return gauge_arrivals


def _analytic_fallback(
    dam_config: Dict,
    gauge_locations: Optional[List[Dict]],
    nx: int, ny: int, dx: float, dy: float,
    total_time_s: float,
) -> Dict:
    """
    Analytic dam-break estimate for small grids where SWE solver can't run.

    Uses Ritter's 1D dam-break wave speed: c = sqrt(g * h).
    """
    height_m = dam_config.get("height_m", 100.0)
    c_wave = 0.5 * math.sqrt(9.81 * height_m)

    max_depth = np.zeros((ny, nx), dtype=np.float32)
    max_velocity = np.zeros((ny, nx), dtype=np.float32)
    arrival_time = np.full((ny, nx), np.nan, dtype=np.float32)

    # Simple radial wave propagation estimate
    dam_row = int(ny * 0.15)
    for j in range(ny):
        dist = abs(j - dam_row) * dy
        t_arrival = dist / max(c_wave, 0.1)
        if t_arrival <= total_time_s:
            decay = max(0.0, 1.0 - dist / (ny * dy))
            max_depth[j, :] = height_m * 0.3 * decay
            max_velocity[j, :] = c_wave * decay
            arrival_time[j, :] = t_arrival

    gauge_arrivals = _ritter_gauge_arrivals(gauge_locations, c_wave)

    return {
        "engine": "JalRaksha_Ritter_Analytic",
        "engine_label": "Ritter analytic estimate - NOT a solver run",
        "success": True,
        "max_depth": max_depth,
        "max_velocity": max_velocity,
        "arrival_time": arrival_time,
        "total_time_s": total_time_s,
        "num_steps": 0,
        "gauge_arrivals": gauge_arrivals,
        "grid_nx": nx,
        "grid_ny": ny,
        "grid_dx": dx,
        "grid_dy": dy,
        "dam_name": dam_config.get("name", "Unknown"),
        "note": "Analytic Ritter dam-break estimate (grid too small for numerical solver).",
    }



def _run_builtin_swe_fallback(
    grid: Dict,
    bathymetry: np.ndarray,
    initial_conditions: Dict,
    dam_config: Dict,
    total_time_s: float = 10800.0,
    manning_n: float = 0.03,
    gauge_locations: Optional[List[Dict]] = None,
) -> Dict:
    """
    Run the built-in 2D SWE solver as Delft3D-equivalent fallback.

    Uses the same Saint-Venant / Shallow Water Equations that Delft3D FM
    solves internally, implemented in our own solver.

    Args:
        grid: Grid definition dict.
        bathymetry: 2D bathymetry array.
        initial_conditions: IC dict with 'water_level' and 'dam_row_index'.
        dam_config: Dam configuration dict.
        total_time_s: Total simulation time (s).
        manning_n: Manning's roughness coefficient.
        gauge_locations: Optional list of gauge dicts with 'distance_km'.

    Returns:
        Standardised result dict (same format as Delft3D binary output).
    """
    from jalraksha.solver.types import Grid as SWEGrid, create_state
    from jalraksha.solver.core import SWESolver

    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]

    # Create SWE grid
    swe_grid = SWEGrid(nx=nx, ny=ny, dx=dx, dy=dy)

    # Create initial state from IC
    wl = initial_conditions["water_level"]
    bed = bathymetry

    # Depth = water_level - bed_elevation (clamp non-negative)
    depth = np.maximum(0.0, wl - bed).astype(np.float32)

    state = create_state(swe_grid, h_init=depth, b_init=bed.astype(np.float32))
    state.h[:] = depth
    state.u[:] = 0.0
    state.v[:] = 0.0

    # Minimum grid size guard for SWE central differences
    if nx < 5 or ny < 5:
        # Grid too small for central-diff solver — return analytic estimate
        return _analytic_fallback(dam_config, gauge_locations, nx, ny, dx, dy, total_time_s)

    # Run solver
    try:
        solver = SWESolver(swe_grid, manning_n=manning_n, cfl=0.5)

        snapshot_interval = 60.0  # seconds
        next_snapshot = snapshot_interval

        max_depth = np.zeros((ny, nx), dtype=np.float32)
        max_velocity = np.zeros((ny, nx), dtype=np.float32)
        arrival_time = np.full((ny, nx), np.nan, dtype=np.float32)
        depth_threshold = 0.1  # metres

        num_steps = 0
        max_steps = 500_000  # Safety cap

        while state.t < total_time_s and num_steps < max_steps:
            state = solver.step(state)
            t = state.t
            num_steps += 1

            # NaN guard — break early if solver blows up
            if np.any(np.isnan(state.h)):
                break

            # Update running maxima
            current_depth = state.h
            current_vel = np.sqrt(state.u**2 + state.v**2)

            np.maximum(max_depth, current_depth, out=max_depth)
            np.maximum(max_velocity, current_vel, out=max_velocity)

            # Arrival time detection
            newly_wet = (current_depth >= depth_threshold) & np.isnan(arrival_time)
            arrival_time[newly_wet] = t

            if t >= next_snapshot:
                next_snapshot += snapshot_interval
    except Exception as exc:
        # A numerical blowup is a real event with a cause. Dropping to a
        # closed-form estimate without naming it turns "the solver diverged"
        # into a plausible-looking table of arrival times.
        import traceback

        print(f"[delft3d] Built-in SWE solver failed ({type(exc).__name__}: {exc}); "
              f"falling back to the Ritter analytic estimate.")
        traceback.print_exc()
        return _analytic_fallback(dam_config, gauge_locations, nx, ny, dx, dy, total_time_s)

    # Gauge arrivals are a Ritter CELERITY ESTIMATE, not a reading taken from
    # the simulation above — see _ritter_gauge_arrivals. The domain this
    # function is called with (40x40 at 30 m from tasks.py) is 1.2 km across
    # and cannot reach a gauge 13 km downstream, so there is nothing in
    # `arrival_time` to read at those locations. The `method` tag travels with
    # the numbers so the dashboard can say so.
    gauge_arrivals = _ritter_gauge_arrivals(
        gauge_locations, 0.5 * math.sqrt(9.81 * dam_config.get("height_m", 100.0))
    )

    return {
        "engine": "JalRaksha_SWE_Delft3D_Equivalent",
        "engine_label": "JalRaksha built-in 2D SWE - Delft3D-class, NOT Delft3D FM",
        "success": True,
        "max_depth": max_depth,
        "max_velocity": max_velocity,
        "arrival_time": arrival_time,
        "total_time_s": t,
        "num_steps": num_steps,
        "gauge_arrivals": gauge_arrivals,
        "grid_nx": nx,
        "grid_ny": ny,
        "grid_dx": dx,
        "grid_dy": dy,
        "dam_name": dam_config.get("name", "Unknown"),
        "note": (
            "Built-in 2D Saint-Venant / Shallow Water Equation solver. "
            "Solves the same governing equations as Delft3D FM "
            "(depth-averaged 2D SWE with Manning friction on structured grid)."
        ),
    }


def run_delft3d_simulation(
    model_setup: Dict,
    dam_config: Dict,
    gauge_locations: Optional[List[Dict]] = None,
    total_time_s: float = 10800.0,
    manning_n: float = 0.03,
    force_fallback: bool = False,
    dflowfm_path: Optional[str] = None,
) -> Dict:
    """
    Run Delft3D FM simulation with automatic fallback.

    Tier A: If dflowfm binary is found, runs the real Delft3D FM engine.
    Tier B: Otherwise, runs the built-in SWE solver (same equations).

    Args:
        model_setup: Dict from setup_delft3d_model().
        dam_config: JalRaksha dam configuration dict.
        gauge_locations: List of downstream gauge dicts.
        total_time_s: Total simulation time (s).
        manning_n: Manning's roughness coefficient.
        force_fallback: If True, skip binary detection and use built-in SWE.
        dflowfm_path: Optional explicit path to dflowfm executable.

    Returns:
        Standardised result dict with:
            'engine': str — which engine ran
            'success': bool
            'max_depth': 2D array
            'max_velocity': 2D array
            'arrival_time': 2D array
            'gauge_arrivals': dict per gauge
    """
    # Every route to Tier B records WHY it got there. Falling back is a
    # legitimate outcome; falling back silently is not — the result of this
    # function is labelled in the dashboard as the engine that produced the
    # numbers, and a fallback nobody was told about reads as Delft3D FM.
    fallback_reason: Optional[str] = None

    # Tier A: Try real Delft3D FM binary
    if force_fallback:
        fallback_reason = "force_fallback=True was requested by the caller."
    else:
        executable = resolve_dflowfm(dflowfm_path)
        if executable is None:
            fallback_reason = (
                f"JALRAKSHA_DFLOWFM_EXE is set to {dflowfm_path!r}, which is "
                f"not a file. Fix the setting or unset it to search PATH."
                if dflowfm_path else
                "The dflowfm binary is not on PATH and JALRAKSHA_DFLOWFM_EXE is "
                "not set. Delft3D FM is not installed on this machine."
            )
        else:
            print(f"[delft3d] Running Delft3D FM: {executable}")
            binary_result = _run_dflowfm_binary(
                model_setup["mdu_path"], executable=executable
            )

            if not binary_result["success"]:
                detail = binary_result.get("error") or (
                    f"exit code {binary_result.get('returncode')}: "
                    f"{(binary_result.get('stderr') or '').strip()[-400:]}"
                )
                fallback_reason = f"dflowfm ran but did not succeed — {detail}"
                print(f"[delft3d] {fallback_reason}")
            else:
                try:
                    parsed = _parse_delft3d_output(
                        binary_result["output_dir"], gauge_locations,
                        model_setup=model_setup, total_time_s=total_time_s,
                        dam_config=dam_config,
                    )
                    parsed["engine"] = "Delft3D_FM"
                    parsed["engine_label"] = "Delft3D FM (official dflowfm binary)"
                    parsed["delft3d_binary_used"] = True
                    parsed["fallback_reason"] = None
                    parsed["dflowfm_path"] = executable
                    print("[delft3d] Delft3D FM output parsed successfully.")
                    return parsed
                except Exception as exc:
                    # Previously `except Exception as exc: pass` — the binary
                    # had run, its output was unreadable, and the run silently
                    # became a built-in SWE result wearing a Delft3D label.
                    fallback_reason = (
                        f"dflowfm exited 0 but its output could not be parsed "
                        f"({type(exc).__name__}: {exc})"
                    )
                    print(f"[delft3d] {fallback_reason}")

    print(f"[delft3d] Falling back to the built-in solver. Reason: {fallback_reason}")

    # Tier B: Built-in SWE fallback
    result = _run_builtin_swe_fallback(
        grid=model_setup["grid"],
        bathymetry=model_setup["bathymetry"],
        initial_conditions=model_setup["initial_conditions"],
        dam_config=dam_config,
        total_time_s=total_time_s,
        manning_n=manning_n,
        gauge_locations=gauge_locations,
    )
    result["delft3d_binary_used"] = False
    result["fallback_reason"] = fallback_reason
    return result


def _resolve_output_dir(work_dir: Path) -> Path:
    """
    Where D-Flow FM actually put its results.

    The kernel does not write next to the .mdu. It creates a
    `DFM_OUTPUT_<model name>/` subdirectory and writes `*_map.nc`, `*_his.nc`
    and the .dia log there. Returning the model directory instead meant a run
    that had genuinely SUCCEEDED - kernel found, exit code 0, both NetCDF files
    on disk - was reported as "output could not be parsed" and silently
    downgraded to the built-in solver.

    Falls back to work_dir when there is no such subdirectory, so a layout that
    does write in place still parses.
    """
    work_dir = Path(work_dir)
    candidates = sorted(work_dir.glob("DFM_OUTPUT_*"))
    for candidate in candidates:
        if candidate.is_dir():
            print(f"[delft3d] Output directory: {candidate}")
            return candidate
    return work_dir


def _parse_his_gauge_arrivals(
    output_dir: Path,
    gauge_locations: Optional[List[Dict]] = None,
    threshold_m: float = 0.1,
) -> Dict[str, Dict]:
    """
    True gauge arrival times from Delft3D FM's history file.

    D-Flow FM writes observation-point time series to `*_his.nc`, separately
    from the gridded `*_map.nc` this module otherwise reads. The history file
    gives depth AT each station directly, so no nearest-cell search is needed.

    One subtlety, and the reason this is not a two-line function: the history
    file records water LEVEL and bed level, not depth. Depth is the difference,
    which also keeps dry stations at exactly zero rather than at a negative
    level-minus-bed. `jalraksha/validation/delft3d_benchmark.py::_read_his_gauges`
    established that; this is the same computation applied to arrival times.

    Returns {} - never a fabricated arrival - when there is no history file, no
    stations, or no variables to read. An empty table is a truthful "the model
    did not report this"; a celerity estimate wearing a Delft3D label would not
    be, and defeats the point of running the real engine.
    """
    output_dir = Path(output_dir)
    his_files = sorted(output_dir.glob("*_his.nc"))
    if not his_files:
        print(f"[delft3d] No *_his.nc under {output_dir}; no gauge arrivals "
              f"from the kernel. (Were observation points written?)")
        return {}

    distances = {str(g.get("name")): g.get("distance_km")
                 for g in (gauge_locations or [])}

    try:
        import netCDF4 as nc
        import numpy as np
    except ImportError as exc:  # pragma: no cover - netCDF4 is a hard dep here
        print(f"[delft3d] Cannot read {his_files[0].name}: {exc}")
        return {}

    dataset = nc.Dataset(his_files[0])
    try:
        variables = dataset.variables
        names_var = next((v for v in ("station_name", "station_id")
                          if v in variables), None)
        if names_var is None or "waterlevel" not in variables:
            print(f"[delft3d] {his_files[0].name} has no station names or "
                  f"waterlevel (present: {sorted(variables)}).")
            return {}

        times = np.asarray(variables["time"][:], dtype=float)
        levels = np.asarray(variables["waterlevel"][:], dtype=float)
        if "bedlevel" in variables:
            beds = np.asarray(variables["bedlevel"][:], dtype=float)
        else:
            # Without a bed level the best available floor is the initial
            # water level at each station, which for a dry downstream station
            # is the bed. Stated rather than silently assumed.
            beds = levels[0, :]
            print("[delft3d] No bedlevel in the history file; using the "
                  "initial water level as the reference for depth.")

        raw_names = np.asarray(variables[names_var][:])
        station_names = []
        for row in raw_names:
            if isinstance(row, (bytes, str)):
                station_names.append(str(row).strip())
            else:
                station_names.append(
                    b"".join(bytes(c) for c in row if c not in (b"", None))
                    .decode("utf-8", "ignore").strip())

        arrivals: Dict[str, Dict] = {}
        for index, name in enumerate(station_names):
            if not name:
                continue
            depth = levels[:, index] - np.atleast_1d(beds)[
                index if np.ndim(beds) else 0]
            wet = np.nonzero(depth >= threshold_m)[0]
            if wet.size == 0:
                arrivals[name] = {
                    "median_s": None, "median_min": None,
                    "distance_km": distances.get(name),
                    "method": "delft3d_fm_his",
                    "note": (f"Water never reached {threshold_m} m at this "
                             f"station within the simulated period."),
                }
                continue
            arrival_s = float(times[wet[0]])
            arrivals[name] = {
                "median_s": arrival_s,
                "median_min": arrival_s / 60.0,
                "max_depth_m": float(np.nanmax(depth)),
                "distance_km": distances.get(name),
                # No p05/p95: a single deterministic Delft3D run has no
                # ensemble spread, and inventing a +/-20% band here (as the
                # analytic fallback does) would misrepresent one model run as
                # an uncertainty quantification.
                "method": "delft3d_fm_his",
            }
        print(f"[delft3d] Read {len(arrivals)} gauge series from "
              f"{his_files[0].name}.")
        return arrivals
    except Exception as exc:
        print(f"[delft3d] Could not read gauge arrivals from "
              f"{his_files[0].name}: {type(exc).__name__}: {exc}")
        return {}
    finally:
        dataset.close()


def _parse_delft3d_output(
    output_dir: Path,
    gauge_locations: Optional[List[Dict]] = None,
    model_setup: Optional[Dict] = None,
    total_time_s: float = 0.0,
    dam_config: Optional[Dict] = None,
) -> Dict:
    """
    Parse Delft3D FM NetCDF output files.

    Looks for FlowFM_map.nc in output_dir and extracts:
      - Maximum depth field
      - Maximum velocity field
      - Arrival time field
      - Gauge arrival times

    The grid description is carried through from model_setup rather than left
    out. Downstream, compare_sph_vs_delft3d() reads grid_nx/grid_ny/grid_dx/
    grid_dy with `.get()` defaults of 100x200 at 30 m — so omitting them, as
    this function used to, meant a SUCCESSFUL real Delft3D run was rasterised
    and compared on a grid of entirely the wrong size. That is a wrong answer
    produced by the code path that is supposed to be the trustworthy one.

    Args:
        output_dir: Directory containing Delft3D output files.
        gauge_locations: List of gauge dicts for arrival time extraction.
        model_setup: The dict from setup_delft3d_model(), for grid metadata.
        total_time_s: Simulated duration, echoed into the result.
        dam_config: Dam configuration, for the reported dam name.

    Returns:
        Standardised result dict.
    """
    import netCDF4 as nc

    output_dir = Path(output_dir)

    # Find map output file
    map_files = list(output_dir.glob("*_map.nc")) + list(output_dir.glob("FlowFM_map.nc"))
    if not map_files:
        raise FileNotFoundError(f"No Delft3D map output found in {output_dir}")

    ds = nc.Dataset(str(map_files[0]), "r")

    try:
        # Extract water depth time series
        if "mesh2d_waterdepth" in ds.variables:
            depth_var = ds.variables["mesh2d_waterdepth"][:]
        elif "s1" in ds.variables:
            depth_var = ds.variables["s1"][:]
        else:
            raise KeyError("No depth variable found in Delft3D output")

        # Compute maxima over time axis
        max_depth = np.nanmax(depth_var, axis=0).astype(np.float32)

        # Velocity
        max_velocity = np.zeros_like(max_depth)
        if "mesh2d_ucx" in ds.variables:
            ucx = ds.variables["mesh2d_ucx"][:]
            ucy = ds.variables["mesh2d_ucy"][:]
            vel_mag = np.sqrt(ucx**2 + ucy**2)
            max_velocity = np.nanmax(vel_mag, axis=0).astype(np.float32)

        # Arrival time
        arrival_time = np.full_like(max_depth, np.nan)
        if "time" in ds.variables:
            times = ds.variables["time"][:]
            for t_idx in range(depth_var.shape[0]):
                newly_wet = (depth_var[t_idx] >= 0.1) & np.isnan(arrival_time)
                arrival_time[newly_wet] = float(times[t_idx])

    finally:
        ds.close()

    grid = (model_setup or {}).get("grid", {})

    return {
        "success": True,
        "max_depth": max_depth,
        "max_velocity": max_velocity,
        "arrival_time": arrival_time,
        # Read from the model's own history output. This was `{}` with a
        # standing TODO, which meant a SUCCESSFUL Delft3D FM run reported no
        # gauge arrivals at all while the built-in fallback reported a full
        # table - the better engine looked like the emptier one.
        "gauge_arrivals": _parse_his_gauge_arrivals(output_dir, gauge_locations),
        "grid_nx": grid.get("nx"),
        "grid_ny": grid.get("ny"),
        "grid_dx": grid.get("dx"),
        "grid_dy": grid.get("dy"),
        "total_time_s": total_time_s,
        "num_steps": int(depth_var.shape[0]),
        "dam_name": (dam_config or {}).get("name", "Unknown"),
        "note": "Parsed from Delft3D FM NetCDF map output.",
    }
