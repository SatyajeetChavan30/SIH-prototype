"""
Ensemble execution — sequential or across CPU cores (Phase 12: Optimization).

Monte Carlo ensemble members are fully independent: each takes its own breach
hydrograph and integrates the same initial state. That makes the ensemble, not
the solver kernel, the cheap axis of parallelism.

Design rule: `run_ensemble_member()` is the SINGLE definition of what running one
member means. Both the sequential and the process-pool paths call it, so results
cannot diverge between them. An earlier version of this module reimplemented the
time-stepping loop with its own simplified breach injection, which meant parallel
runs silently produced different physics from sequential ones.

Why not GPU: the flux kernels are numba scalar loops on float64 (mandated by
solver/types.py for the lake-at-rest gate), and consumer GPUs run float64 at
1/64 of float32 — a float64 CUDA port would likely be slower than these CPU
kernels. See solver/flux.py:48 on why fastmath is also off the table.

References:
  Spec §12: Parallelization & Performance Optimization
"""

import math
import os
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

# Depth snapshots exist only to be colorized into keyframe PNGs, so float32
# halves what crosses the process boundary. Everything the solver itself
# touches stays float64 per the precision policy in solver/types.py.
SNAPSHOT_DTYPE = np.float32

ARRIVAL_THRESHOLD_M = 0.1  # CLAUDE.md / Spec §4.3: arrival when depth >= 0.1 m

# Cost of bringing up one worker process on Windows (spawn, not fork):
# re-importing numpy/rasterio/numba and reloading the JIT cache.
WORKER_STARTUP_SECONDS = 15.0

# How much faster one member runs using every numba thread versus a single
# thread. Measured on this codebase at 400 m / 600x600 / 16 logical cores:
# 12.8 s with 16 threads vs 30.3 s with 1, i.e. 2.37x — poor scaling, as expected
# for a memory-bound stencil that synchronises every timestep.
#
# That ratio is exactly why ensemble-level parallelism wins. Per unit of wall
# time, 16 single-threaded members deliver 16/30.3 = 0.53 members/s against
# 1/12.8 = 0.078 for one all-threads member: nearly 7x the throughput. The two
# axes compete for the same cores, so workers are pinned to one thread each
# (see _init_worker) and the parallelism is spent across members instead.
INTRA_MEMBER_THREAD_SPEEDUP = 2.4


def _snapshot(state: Any, time_s: float) -> Dict[str, Any]:
    """
    Record one instant of the flow field for downstream visualization.

    Depth alone is not enough: the MATLAB viewer draws velocity vectors and
    reports flow speed (spec sections 5, 15, 21), and the solver's State already
    carries u/v — they were simply never captured. Storing them here is the only
    change needed to feed that, and it costs 3x a depth-only snapshot rather than
    re-running the solver later to recover them.
    """
    return {
        "time_s": float(time_s),
        "depth": state.h.astype(SNAPSHOT_DTYPE),
        "velocity_x": state.u.astype(SNAPSHOT_DTYPE),
        "velocity_y": state.v.astype(SNAPSHOT_DTYPE),
    }


def run_ensemble_member(
    sample_id: int,
    hydrograph: Dict[str, Any],
    grid: Any,
    state_init: Any,
    manning_field: np.ndarray,
    i_breach: int,
    j_breach: int,
    solver_duration_s: float,
    snapshot_times: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """
    Integrate one ensemble member. The single source of truth for member physics.

    Args:
        sample_id: Index of this member within the ensemble.
        hydrograph: One entry from synthesize_breach_ensemble().
        grid: Grid definition.
        state_init: Initial State (dry bed, real topography in .b).
        manning_field: Manning's n field.
        i_breach, j_breach: Breach cell (i = column/x, j = row/y).
        solver_duration_s: Simulated duration (s).
        snapshot_times: If given, record the depth grid at each of these
            simulation times (for keyframe export). None for most members.

    Returns:
        On success: {sample_id, t_arrival, h_max, v_max, metadata, depth_series,
        success=True}
        On failure: {sample_id, error, success=False} — failures are reported,
        never silently dropped.
    """
    # Imported here rather than at module scope so process-pool workers pick them
    # up on their own side of the fork/spawn boundary.
    from jalraksha.solver.core import SWESolver
    from jalraksha.run import inject_breach_hydrograph

    try:
        t_hydro = hydrograph["t_array"]
        q_hydro = hydrograph["Q_t"]
        metadata = hydrograph["metadata"]

        # cfl is clamped to SWESolver's own CFL_MAX; pass a value inside that
        # bound so max_steps below reflects the timestep actually taken. The
        # previous cfl=0.9 was silently clamped, making the estimate ~3x off.
        solver = SWESolver(grid, manning_n=float(np.mean(manning_field)), cfl=0.3)

        state = state_init.copy()
        t_sim = 0.0
        dt_adaptive = solver.compute_cfl_timestep(state)

        t_arrival = np.full((grid.ny, grid.nx), np.inf, dtype=np.float64)
        h_max = np.zeros((grid.ny, grid.nx), dtype=np.float64)
        # Running maximum of depth-averaged speed |(u, v)|. Needed by the Phase 5
        # exports: the velocity COGs and the FD2320 hazard classes are functions
        # of speed as well as depth, and without capturing it here the export
        # layer's `r.get("v_max", zeros)` default silently writes an all-zero
        # velocity field — a plausible-looking wrong answer, which is the one
        # outcome CLAUDE.md's no-silent-fallback rule exists to prevent.
        v_max = np.zeros((grid.ny, grid.nx), dtype=np.float64)

        step_count = 0
        # Safety cap only — it must not silently truncate the run. Sizing it from
        # the initial timestep (as this once did) is badly wrong: the domain
        # starts dry, so the first CFL timestep is the maximum allowed, and once
        # the flood arrives dt collapses by orders of magnitude. The old cap cut
        # runs off after a handful of real steps. Deriving it from dt_min gives a
        # bound the physics cannot legitimately exceed.
        max_steps = int(solver_duration_s / max(getattr(solver, "dt_min", 1e-3), 1e-6)) + 1
        max_steps = min(max_steps, 5_000_000)

        depth_series: List[Dict[str, Any]] = []
        next_snapshot_idx = 0
        if snapshot_times is not None and len(snapshot_times) and snapshot_times[0] <= 0:
            depth_series.append(_snapshot(state, 0.0))
            next_snapshot_idx = 1

        # Volume balance. `released` is measured as the depth the injector
        # actually adds, not integrated from the hydrograph analytically: the
        # injector clamps and the two can differ, and the number that matters
        # for "where did the water go" is what really entered the domain.
        cell_area_m2 = float(grid.dx) * float(grid.dy)
        volume_released_m3 = 0.0

        while t_sim < solver_duration_s and step_count < max_steps:
            h_before_inject = float(state.h.sum())
            inject_breach_hydrograph(
                state, grid, i_breach, j_breach, t_sim, dt_adaptive, q_hydro, t_hydro
            )
            volume_released_m3 += (
                float(state.h.sum()) - h_before_inject
            ) * cell_area_m2

            state = solver.step(state)
            t_sim += dt_adaptive
            dt_adaptive = solver.compute_cfl_timestep(state)

            newly_wet = (state.h >= ARRIVAL_THRESHOLD_M) & (t_arrival == np.inf)
            t_arrival[newly_wet] = t_sim

            np.maximum(h_max, state.h, out=h_max)
            np.maximum(v_max, np.hypot(state.u, state.v), out=v_max)

            if snapshot_times is not None:
                # A single step can cross SEVERAL scheduled times — early steps
                # are large relative to the requested spacing (30 s steps against
                # ~20 s spacing, say). Advance past all the times crossed, but
                # record only ONE snapshot.
                #
                # Appending one per crossed time (the previous behaviour) stamped
                # every one of them with the same t_sim, producing duplicate
                # frames: a 30-snapshot request came back with 0, 30, 60, 90,
                # 90, 120, ... That is redundant for keyframes and outright
                # rejected by xdmf_export.write_xdmf_series, which requires
                # strictly increasing frame times.
                if (
                    next_snapshot_idx < len(snapshot_times)
                    and t_sim >= snapshot_times[next_snapshot_idx]
                ):
                    depth_series.append(_snapshot(state, t_sim))
                    while (
                        next_snapshot_idx < len(snapshot_times)
                        and t_sim >= snapshot_times[next_snapshot_idx]
                    ):
                        next_snapshot_idx += 1

            step_count += 1

        if step_count >= max_steps:
            warnings.warn(
                f"Member {sample_id} hit the {max_steps}-step safety cap at "
                f"t={t_sim:.1f}s of {solver_duration_s:.1f}s — the timestep has "
                f"probably collapsed. Results are truncated, not converged."
            )

        # Retained is the water still standing at the cutoff, counting only
        # cells at or above the solver's own dry threshold — a domain-wide film
        # of 1e-9 m is a numerical residue, not trapped water.
        h_final = state.h
        volume_retained_m3 = float(
            h_final[h_final >= solver.h_dry].sum()
        ) * cell_area_m2

        return {
            "sample_id": sample_id,
            "t_arrival": t_arrival,
            "h_max": h_max,
            "v_max": v_max,
            "metadata": metadata,
            "depth_series": depth_series,
            "n_steps": step_count,
            # Volume balance: released should equal exited + retained to within
            # the scheme's own conservation error. A large retained fraction is
            # the drainage plateau of docs/validation_findings.md section 8,
            # measured directly instead of inferred from hazard cell counts.
            "volume_released_m3": volume_released_m3,
            "volume_exited_m3": float(solver.volume_exited_m3),
            "volume_retained_m3": volume_retained_m3,
            "success": True,
        }
    except Exception as e:
        return {"sample_id": sample_id, "error": f"{type(e).__name__}: {e}", "success": False}


def _member_task(args: tuple) -> Dict[str, Any]:
    """Unpack a task tuple for ProcessPoolExecutor (which cannot pickle lambdas)."""
    return run_ensemble_member(*args)


# Native math libraries each start their own thread pool per process, sized to
# the core count, and each thread carries private scratch buffers. Sixteen
# workers x sixteen OpenBLAS threads exhausted memory outright
# ("OpenBLAS error: Memory allocation still failed after 10 retries"), killing
# the pool. Spawned children inherit os.environ, so setting these in the parent
# before the pool starts is what actually takes effect — an initializer runs too
# late, after the child has already imported numpy.
_SINGLE_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "NUMBA_NUM_THREADS": "1",
}


def _worker_memory_cap(pool_size: int) -> int:
    """Clamp worker count to what RAM can hold (~400 MB of interpreter each)."""
    try:
        import psutil

        available_mb = psutil.virtual_memory().available / 1e6
    except Exception:
        return min(pool_size, 8)  # no psutil: stay conservative
    return max(1, min(pool_size, int(available_mb // 400)))


def _init_worker() -> None:
    """
    Pin each worker to a single numba thread.

    The flux kernels are @njit(parallel=True) and fan out over prange, so by
    default every worker process tries to use all cores. With one worker per core
    that is N^2 threads on N cores — on this 16-thread machine, 8 workers each
    spawning 16 threads. The oversubscription thrashes and eats the entire
    benefit of running members concurrently.

    Parallelism belongs on exactly one axis. Across members is the better one:
    they are fully independent, so it needs no synchronisation and scales
    linearly, whereas the in-kernel prange has to synchronise every timestep.
    """
    try:
        import numba

        numba.set_num_threads(1)
    except Exception:
        pass


def run_ensemble(
    hydrographs: List[Dict[str, Any]],
    grid: Any,
    state_init: Any,
    manning_field: np.ndarray,
    i_breach: int,
    j_breach: int,
    solver_duration_s: float,
    snapshot_sample_id: Optional[int] = None,
    snapshot_times: Optional[Sequence[float]] = None,
    n_workers: Optional[int] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Run every ensemble member, in-process or across a process pool.

    On Windows, callers running this from a script MUST guard their entry point::

        if __name__ == "__main__":
            run_ensemble(...)

    Spawned children re-import the parent's __main__ module, so without the guard
    each worker re-executes the whole script and multiprocessing raises. This
    function degrades to sequential rather than failing outright when that
    happens, so an unguarded script still produces correct results — just slowly.

    Args:
        n_workers: 1 runs in-process (best for debugging, and required when the
            caller is itself inside a worker process). None uses os.cpu_count().

    The first member always runs in-process as a cost probe (see below), so the
    achievable speedup is bounded by Amdahl on that one member: negligible for a
    100-member ensemble, noticeable for a handful.

    Returns:
        Member result dicts ordered by sample_id, successes and failures alike —
        the caller decides how to report failures.
    """
    if n_workers is None:
        n_workers = os.cpu_count() or 1
    n_workers = max(1, min(int(n_workers), len(hydrographs) or 1))

    tasks = [
        (
            sample_id,
            hydrograph,
            grid,
            state_init,
            manning_field,
            i_breach,
            j_breach,
            solver_duration_s,
            snapshot_times if sample_id == snapshot_sample_id else None,
        )
        for sample_id, hydrograph in enumerate(hydrographs)
    ]

    # A process pool is not free on Windows, which spawns rather than forks, and
    # its workers are single-threaded (see _init_worker) so each member runs
    # slower there than it does in-process. Whether the pool wins therefore
    # depends on the ENSEMBLE SIZE, not on any per-member threshold: time one
    # member, then compare the two estimates directly. The probe result is kept,
    # not thrown away.
    total_members = len(tasks)
    completed = 0

    def _tick(result):
        """
        Count one finished member and report it.

        run_ensemble has four distinct completion paths - the probe, the
        sequential cost-model branch, the process pool, and the pool-failure
        fallback - and progress has to work on all of them, so every path routes
        through here rather than each growing its own counter.

        Reporting failures are swallowed: this is telemetry attached to a
        long-running simulation, and a broken status write must not lose the run.
        """
        nonlocal completed
        completed += 1
        if progress_cb is not None:
            try:
                progress_cb(completed, total_members)
            except Exception:  # pragma: no cover - telemetry only
                pass
        return result

    def _tick_all(results):
        return [_tick(r) for r in results]

    if n_workers > 1 and len(tasks) > 1:
        probe_start = time.perf_counter()
        probe = _tick(_member_task(tasks[0]))
        probe_seconds = time.perf_counter() - probe_start

        remaining = tasks[1:]
        pool_size = _worker_memory_cap(min(n_workers, len(remaining)))
        sequential_estimate = len(remaining) * probe_seconds
        waves = math.ceil(len(remaining) / pool_size)
        parallel_estimate = (
            waves * probe_seconds * INTRA_MEMBER_THREAD_SPEEDUP + WORKER_STARTUP_SECONDS
        )

        if parallel_estimate >= sequential_estimate:
            print(
                f"  Member takes {probe_seconds:.1f}s; {len(remaining)} left would "
                f"cost ~{parallel_estimate:.0f}s across {pool_size} workers vs "
                f"~{sequential_estimate:.0f}s in-process — staying sequential."
            )
            return _finish([probe] + _tick_all(_member_task(t) for t in remaining))

        print(
            f"  Member takes {probe_seconds:.1f}s; running the remaining "
            f"{len(remaining)} across {pool_size} worker processes "
            f"(~{parallel_estimate:.0f}s vs ~{sequential_estimate:.0f}s sequential)..."
        )
        saved_env = {k: os.environ.get(k) for k in _SINGLE_THREAD_ENV}
        try:
            os.environ.update(_SINGLE_THREAD_ENV)
            with ProcessPoolExecutor(
                max_workers=pool_size, initializer=_init_worker
            ) as executor:
                # executor.map yields in submission order as workers finish, so
                # counting as we consume gives real progress rather than a jump
                # from 0 to 100 when the pool drains.
                return _finish(
                    [probe] + _tick_all(executor.map(_member_task, remaining)))
        except Exception as e:
            warnings.warn(
                f"Parallel ensemble failed to start ({type(e).__name__}: {e}); "
                f"falling back to sequential execution."
            )
            return _finish([probe] + _tick_all(_member_task(t) for t in remaining))
        finally:
            # Leave the caller's environment as we found it — these vars are for
            # the children, and a library must not permanently reconfigure the
            # host process's threading.
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    return _finish(_tick_all(_member_task(t) for t in tasks))


def _finish(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order results by sample_id so callers see a deterministic sequence."""
    results.sort(key=lambda r: r["sample_id"])
    return results
