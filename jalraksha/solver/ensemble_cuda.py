"""
Batched ensemble on the GPU: many breach hydrographs in one device-resident solve.

WHAT THIS IS, AND WHAT IT MUST NOT CHANGE
-----------------------------------------
parallel.run_ensemble_member defines what running one member means. This
module is a second implementation of that loop. It is bound to the first by
tests/test_parallel.py::TestGpuEnsemble, which runs both on the same inputs
and compares the answers. A second copy is only safe with that test in place:
the parallel.py docstring records how an unbound copy once computed different
physics from the sequential path.

The member loop is reproduced exactly. That includes one behaviour that looks
like a defect and is carried over deliberately, because a GPU port that silently
changed the physics could not be validated against the CPU: the solver runs
with manning_n = mean(manning_field), a uniform field, not the spatially
varying one. It belongs in a separate fix, applied to both backends together.

ONE TIMESTEP PER STEP. The injection, the step and the member clock all use the
same dt, which choose_injection_step picks exactly as
parallel.inject_with_one_timestep does on the CPU: start from the pre-injection
CFL limit, and shrink it until the step is CFL-valid on the state it actually
integrates. Only the breach cell changes when water is injected, so the
post-injection limit is max(limit over every other cell, limit of the breach
cell). The first term comes out of the same reduction that produces the
pre-injection limit (inverse_dt_split). The second is one call to the shared
per-cell CFL function. Each trial is therefore O(1) per member rather than a
grid-wide reduction, and it gives the same limit, because max is exact.

PER-MEMBER TIME
---------------
Members do not share a timestep. Each keeps its own dt and t_sim on the
device, exactly as it would running alone. A member that has finished is
masked out (`active`), and every kernel returns early for it. Advancing it
with dt = 0 instead would still change it, because friction zeroes velocities
in dry cells and applies the velocity cap regardless of dt.

ONE DELIBERATE DIFFERENCE, IN THE DIRECTION OF HONESTY
------------------------------------------------------
A member whose solution goes non-finite is stopped and returned with
success=False. The CPU member loop has no such check and would carry NaNs to
the end of the run.

HOST TRAFFIC
------------
The host reads the active mask every POLL_STEPS steps and nothing else until
the chunk finishes. Snapshots of the representative member are captured into
a device buffer by a kernel, not copied to the host step by step.
"""

import math
import warnings
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
from numba import cuda

from .core import CFL_MAX, DT_MAX_DEFAULT
from .engine_cuda import PAD, CudaSWEEngine
from .flux import H_DRY_DEFAULT, NO_NEIGHBOUR, VELOCITY_MAX_DEFAULT
from .flux_cuda import _inverse_dt_cell, finalize_dt, launch_grid
from .parallel import (
    ARRIVAL_THRESHOLD_M,
    INJECTION_CFL_RTOL,
    MAX_INJECTION_PASSES,
    MEMBER_CFL,
    SNAPSHOT_DTYPE,
    _snapshot,
    member_step_cap,
)
from .types import DTYPE

# Steps between reads of the active mask. Each read is a host sync. After the
# last member finishes, at most POLL_STEPS - 1 steps' worth of early-returning
# kernels are launched for nothing, which costs milliseconds.
POLL_STEPS = 64

# Share of FREE device memory one chunk may claim. The rest covers the CUDA
# context, allocator slack, and other users of the same GPU (a second run
# subprocess, the dashboard's live validation checks).
VRAM_FRACTION = 0.6

# Running maxima held per member on top of the engine's own arrays:
# h_max, v_max, t_arrival.
EXTRA_ARRAYS_PER_MEMBER = 3

# Slots of the snapshot control array.
_NEXT, _COUNT, _SLOT, _FLAG = 0, 1, 2, 3


# ----------------------------------------------------------------------
# Ensemble-only kernels
# ----------------------------------------------------------------------


@cuda.jit(device=True)
def _breach_discharge(t_hydro, q_hydro, count_t, count_q, m, t_s, dt_s):
    """
    Breach discharge (m³/s) at t_s; mirrors run.hydrograph_discharge.

    np.searchsorted (side='left') on the hydrograph times, then linear
    interpolation; zero before the first sample and after the last.
    """
    lo = 0
    hi = count_t
    while lo < hi:
        mid = (lo + hi) // 2
        if t_hydro[m, mid] < t_s:
            lo = mid + 1
        else:
            hi = mid
    idx = lo
    if idx >= count_q or idx == 0:
        return 0.0
    t_prev = t_hydro[m, idx - 1]
    t_next = t_hydro[m, idx] if idx < count_t else t_prev + dt_s
    q_prev = q_hydro[m, idx - 1]
    q_next = q_hydro[m, idx]
    if t_next > t_prev:
        alpha = (t_s - t_prev) / (t_next - t_prev)
        return (1 - alpha) * q_prev + alpha * q_next
    return q_prev


@cuda.jit(cache=True)
def inverse_dt_split(
    h, u, v, b, inv_all, inv_rest, skip_row, skip_col, dx, dy, active_x, active_y, h_dry, active
):
    """
    Per member: the maximum inverse timescale over every cell (inv_all, from
    which the pre-injection CFL limit is taken) and over every cell except the
    breach cell (inv_rest, which choose_injection_step combines with the breach
    cell's post-injection value). Mirrors flux.max_wave_speed_inverse_dt.
    """
    c, r, m = cuda.grid(3)
    ny = h.shape[1] - 2 * PAD
    nx = h.shape[2] - 2 * PAD
    if m >= h.shape[0] or r >= ny or c >= nx or active[m] == 0:
        return
    row = r + PAD
    col = c + PAD
    depth = h[m, row, col]
    if depth <= h_dry:
        return
    total = _inverse_dt_cell(
        depth,
        u[m, row, col],
        v[m, row, col],
        b[row, col],
        b[row, col - 1] if c > 0 else NO_NEIGHBOUR,
        b[row, col + 1] if c < nx - 1 else NO_NEIGHBOUR,
        b[row - 1, col] if r > 0 else NO_NEIGHBOUR,
        b[row + 1, col] if r < ny - 1 else NO_NEIGHBOUR,
        dx,
        dy,
        active_x,
        active_y,
    )
    cuda.atomic.max(inv_all, m, total)
    if row != skip_row or col != skip_col:
        cuda.atomic.max(inv_rest, m, total)


@cuda.jit(cache=True)
def choose_injection_step(
    h, u, v, b, t_hydro, q_hydro, n_t, n_q, t_sim, dt_pre, inv_rest, dt_step,
    released, retries, overruns, row, col, cell_area, cfl, dt_max, dx, dy,
    active_x, active_y, h_dry, max_passes, active,
):  # fmt: skip
    """
    Inject one step's breach outflow and choose the ONE timestep the injection,
    the step and the clock all use; mirrors parallel.inject_with_one_timestep.

    One thread per member. The post-injection CFL limit of a trial is
    max(inv_rest, breach cell's value at the trial depth). That equals the
    grid-wide limit the CPU recomputes, because injection changes nothing but
    the breach cell's depth (not its velocity, not its neighbours).
    """
    m = cuda.grid(1)
    if m >= t_sim.shape[0] or active[m] == 0:
        return
    ny = h.shape[1] - 2 * PAD
    nx = h.shape[2] - 2 * PAD
    r = row - PAD
    c = col - PAD
    saved = h[m, row, col]
    vel_x = u[m, row, col]
    vel_y = v[m, row, col]
    bed = b[row, col]
    bed_x_minus = b[row, col - 1] if c > 0 else NO_NEIGHBOUR
    bed_x_plus = b[row, col + 1] if c < nx - 1 else NO_NEIGHBOUR
    bed_y_minus = b[row - 1, col] if r > 0 else NO_NEIGHBOUR
    bed_y_plus = b[row + 1, col] if r < ny - 1 else NO_NEIGHBOUR

    dt = dt_pre[m]
    depth = saved
    passes = 0
    overran = 0
    while True:
        passes += 1
        q = _breach_discharge(t_hydro, q_hydro, n_t[m], n_q[m], m, t_sim[m], dt)
        depth = saved
        if q > 0:
            depth = saved + q * dt / cell_area
        if depth == saved:
            break  # nothing injected: the state and its limit are unchanged
        inv_breach = 0.0
        if depth > h_dry:
            inv_breach = _inverse_dt_cell(
                depth, vel_x, vel_y, bed, bed_x_minus, bed_x_plus, bed_y_minus,
                bed_y_plus, dx, dy, active_x, active_y,
            )  # fmt: skip
        inverse = inv_rest[m]
        if inv_breach > inverse:
            inverse = inv_breach
        if inverse <= 0.0:
            dt_post = dt_max
        else:
            dt_post = min(cfl / inverse, dt_max)
        if dt <= dt_post * (1.0 + INJECTION_CFL_RTOL):
            break
        if passes >= max_passes:
            overran = 1
            break
        dt = dt_post

    h[m, row, col] = depth
    released[m] += (depth - saved) * cell_area
    dt_step[m] = dt
    if passes > 1:
        retries[m] += 1
    if overran != 0:
        overruns[m] += 1
    inv_rest[m] = 0.0  # consumed; the next reduction accumulates afresh


@cuda.jit(cache=True)
def advance_clock(t_sim, dt, active):
    """t_sim += the step's one timestep."""
    m = cuda.grid(1)
    if m >= t_sim.shape[0] or active[m] == 0:
        return
    t_sim[m] += dt[m]


@cuda.jit(cache=True)
def ensemble_maxima(h, u, v, h_max, v_max, t_arrival, t_sim, threshold, nonfinite, active):
    """First arrival (depth >= threshold), running max depth and max speed."""
    c, r, m = cuda.grid(3)
    if m >= h_max.shape[0] or r >= h_max.shape[1] or c >= h_max.shape[2] or active[m] == 0:
        return
    depth = h[m, r + PAD, c + PAD]
    vel_x = u[m, r + PAD, c + PAD]
    vel_y = v[m, r + PAD, c + PAD]
    if not (math.isfinite(depth) and math.isfinite(vel_x) and math.isfinite(vel_y)):
        nonfinite[m] = 1
    if depth >= threshold and t_arrival[m, r, c] == math.inf:
        t_arrival[m, r, c] = t_sim[m]
    if depth > h_max[m, r, c]:
        h_max[m, r, c] = depth
    speed = math.hypot(vel_x, vel_y)
    if speed > v_max[m, r, c]:
        v_max[m, r, c] = speed


@cuda.jit(cache=True)
def end_of_step(
    active, step_count, t_sim, duration, max_steps, nonfinite,
    snap_member, snap_times, snap_time_out, snap_control,
):
    """
    Snapshot decision for the representative member, then the loop condition.

    A single step can cross several scheduled snapshot times. As on the CPU,
    ONE frame is recorded and every crossed time is skipped past, so frame
    times stay strictly increasing.
    """
    m = cuda.grid(1)
    if m >= active.shape[0] or active[m] == 0:
        return
    if m == snap_member:
        snap_control[_FLAG] = 0
        idx = snap_control[_NEXT]
        n_times = snap_times.shape[0]
        if idx < n_times and t_sim[m] >= snap_times[idx]:
            slot = snap_control[_COUNT]
            snap_time_out[slot] = t_sim[m]
            snap_control[_SLOT] = slot
            snap_control[_COUNT] = slot + 1
            snap_control[_FLAG] = 1
            while idx < n_times and t_sim[m] >= snap_times[idx]:
                idx += 1
            snap_control[_NEXT] = idx
    step_count[m] += 1
    if nonfinite[m] != 0 or not (t_sim[m] < duration and step_count[m] < max_steps):
        active[m] = 0


@cuda.jit(cache=True)
def copy_snapshot(h, u, v, snap_member, snap_control, buffer):
    """Copy the representative member's (h, u, v) into its frame slot, as float32."""
    c, r = cuda.grid(2)
    if snap_member < 0 or snap_control[_FLAG] == 0:
        return
    if r >= buffer.shape[2] or c >= buffer.shape[3]:
        return
    slot = snap_control[_SLOT]
    buffer[slot, 0, r, c] = h[snap_member, r + PAD, c + PAD]
    buffer[slot, 1, r, c] = u[snap_member, r + PAD, c + PAD]
    buffer[slot, 2, r, c] = v[snap_member, r + PAD, c + PAD]


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------


def ensemble_chunk_size(grid: Any, n_members: int, snapshot_frames: int = 0) -> int:
    """How many members fit on the device at once, given its FREE memory now."""
    per_member = CudaSWEEngine.bytes_per_member(grid.ny, grid.nx, EXTRA_ARRAYS_PER_MEMBER)
    free_bytes, _total = cuda.current_context().get_memory_info()
    snapshot_bytes = snapshot_frames * 3 * grid.ny * grid.nx * np.dtype(SNAPSHOT_DTYPE).itemsize
    budget = free_bytes * VRAM_FRACTION - snapshot_bytes
    return max(1, min(n_members, int(budget // per_member)))


def run_ensemble_gpu(
    hydrographs: List[Dict[str, Any]],
    grid: Any,
    state_init: Any,
    manning_field: np.ndarray,
    i_breach: int,
    j_breach: int,
    solver_duration_s: float,
    snapshot_sample_id: Optional[int] = None,
    snapshot_times: Optional[Sequence[float]] = None,
    on_member_done: Optional[Callable[[], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Run every member on the GPU, in as few device-resident chunks as fit.

    Returns the same per-member dicts as parallel.run_ensemble_member, ordered
    by sample_id. Failures are reported, never dropped. Raises only for
    failures of the device itself (a compile error, out of memory); the caller
    decides whether to fall back to the CPU.
    """
    results: Dict[int, Dict[str, Any]] = {}
    runnable = []
    for sample_id, hydrograph in enumerate(hydrographs):
        try:
            # Same keys, same order as run_ensemble_member, so a malformed
            # hydrograph fails with the same message on either backend.
            t_hydro = np.asarray(hydrograph["t_array"], dtype=DTYPE)
            q_hydro = np.asarray(hydrograph["Q_t"], dtype=DTYPE)
            metadata = hydrograph["metadata"]
        except Exception as e:
            results[sample_id] = {
                "sample_id": sample_id,
                "error": f"{type(e).__name__}: {e}",
                "success": False,
            }
            if on_member_done is not None:
                on_member_done()
            continue
        runnable.append((sample_id, t_hydro, q_hydro, metadata))

    if runnable:
        want_frames = (
            snapshot_sample_id is not None
            and snapshot_times is not None
            and len(snapshot_times) > 0
        )
        chunk = ensemble_chunk_size(grid, len(runnable), len(snapshot_times) if want_frames else 0)
        # One uniform field, as the CPU member loop builds (see module docstring).
        manning_uniform = np.full((grid.ny, grid.nx), float(np.mean(manning_field)), dtype=DTYPE)
        for start in range(0, len(runnable), chunk):
            for result in _run_chunk(
                runnable[start : start + chunk],
                grid,
                state_init,
                manning_uniform,
                i_breach,
                j_breach,
                float(solver_duration_s),
                snapshot_sample_id if want_frames else None,
                snapshot_times,
                on_member_done,
            ):
                results[result["sample_id"]] = result

    return [results[sample_id] for sample_id in sorted(results)]


def _run_chunk(
    batch,
    grid,
    state_init,
    manning_uniform,
    i_breach,
    j_breach,
    solver_duration_s,
    snapshot_sample_id,
    snapshot_times,
    on_member_done,
) -> List[Dict[str, Any]]:
    n_members = len(batch)
    ny, nx = grid.ny, grid.nx
    max_steps = member_step_cap(solver_duration_s)

    engine = CudaSWEEngine(
        grid,
        state_init.b,
        manning_uniform,
        n_members,
        boundary="transmissive",
        use_muscl=True,
        h_dry=H_DRY_DEFAULT,
        velocity_max=VELOCITY_MAX_DEFAULT,
        cfl=min(MEMBER_CFL, CFL_MAX),
        dt_max=DT_MAX_DEFAULT,
    )
    engine.set_all_states(state_init.h, state_init.u, state_init.v)

    # Hydrographs, padded to a common length; each member keeps its own count.
    length = max(1, max(max(len(t), len(q)) for _, t, q, _ in batch))
    t_host = np.zeros((n_members, length), dtype=DTYPE)
    q_host = np.zeros((n_members, length), dtype=DTYPE)
    for k, (_, t_hydro, q_hydro, _) in enumerate(batch):
        t_host[k, : len(t_hydro)] = t_hydro
        q_host[k, : len(q_hydro)] = q_hydro
    t_dev, q_dev = cuda.to_device(t_host), cuda.to_device(q_host)
    n_t = cuda.to_device(np.array([len(t) for _, t, _, _ in batch], dtype=np.int64))
    n_q = cuda.to_device(np.array([len(q) for _, _, q, _ in batch], dtype=np.int64))

    t_sim = cuda.to_device(np.zeros(n_members, dtype=DTYPE))
    dt_pre = cuda.to_device(np.zeros(n_members, dtype=DTYPE))  # CFL limit before injection
    dt_step = cuda.to_device(np.zeros(n_members, dtype=DTYPE))  # the step's ONE timestep
    inv_all = cuda.to_device(np.zeros(n_members, dtype=DTYPE))
    inv_rest = cuda.to_device(np.zeros(n_members, dtype=DTYPE))
    released = cuda.to_device(np.zeros(n_members, dtype=DTYPE))
    step_count = cuda.to_device(np.zeros(n_members, dtype=np.int64))
    nonfinite = cuda.to_device(np.zeros(n_members, dtype=np.int32))
    retries = cuda.to_device(np.zeros(n_members, dtype=np.int64))
    overruns = cuda.to_device(np.zeros(n_members, dtype=np.int64))
    h_max = cuda.to_device(np.zeros((n_members, ny, nx), dtype=DTYPE))
    v_max = cuda.to_device(np.zeros((n_members, ny, nx), dtype=DTYPE))
    t_arrival = cuda.to_device(np.full((n_members, ny, nx), np.inf, dtype=DTYPE))

    running = solver_duration_s > 0.0  # the CPU loop's first condition check
    engine.active.copy_to_device(np.full(n_members, int(running), dtype=np.int32))

    # Representative member's snapshots. The t = 0 frame, if requested, is
    # taken on the host from the initial state, exactly as the CPU does.
    snap_local = -1
    for k, (sample_id, _, _, _) in enumerate(batch):
        if sample_id == snapshot_sample_id:
            snap_local = k
    initial_frame = None
    next_idx = 0
    if snap_local >= 0:
        snap_times_host = np.asarray(snapshot_times, dtype=DTYPE)
        if snap_times_host[0] <= 0:
            initial_frame = _snapshot(state_init, 0.0)
            next_idx = 1
        frame_buffer = cuda.device_array((len(snap_times_host), 3, ny, nx), dtype=SNAPSHOT_DTYPE)
    else:
        snap_times_host = np.zeros(1, dtype=DTYPE)
        frame_buffer = cuda.device_array((1, 3, 1, 1), dtype=SNAPSHOT_DTYPE)
    snap_times_dev = cuda.to_device(snap_times_host)
    snap_time_out = cuda.to_device(np.zeros(len(snap_times_host), dtype=DTYPE))
    snap_control = cuda.to_device(np.array([next_idx, 0, 0, 0], dtype=np.int64))

    members = ((n_members + 127) // 128, 128)
    cells = launch_grid(nx, ny, n_members)
    frame_grid = (((nx + 31) // 32, (ny + 7) // 8), (32, 8))
    breach_row, breach_col = j_breach + PAD, i_breach + PAD
    reported = np.zeros(n_members, dtype=bool)

    split_limit = inverse_dt_split[cells]
    finalize = finalize_dt[members]
    choose = choose_injection_step[members]

    def pre_injection_limit() -> None:
        """dt_pre = CFL limit of the state as it stands; inv_rest for the next choose."""
        split_limit(
            engine.h, engine.u, engine.v, engine.bed, inv_all, inv_rest,
            breach_row, breach_col, engine.dx, engine.dy,
            engine.active_x, engine.active_y, engine.h_dry, engine.active,
        )  # fmt: skip
        finalize(inv_all, dt_pre, engine.cfl, engine.dt_max, engine.active)

    # CPU: dt_pre_injection = solver.compute_cfl_timestep(state) before the loop.
    pre_injection_limit()

    steps = 0
    while running:
        choose(
            engine.h, engine.u, engine.v, engine.bed, t_dev, q_dev, n_t, n_q,
            t_sim, dt_pre, inv_rest, dt_step, released, retries, overruns,
            breach_row, breach_col, engine.cell_area, engine.cfl, engine.dt_max,
            engine.dx, engine.dy, engine.active_x, engine.active_y, engine.h_dry,
            MAX_INJECTION_PASSES, engine.active,
        )  # fmt: skip
        # ONE timestep: the injection above, this step, and the clock.
        engine.advance_with_outflow(dt_step)
        advance_clock[members](t_sim, dt_step, engine.active)
        pre_injection_limit()  # for the next step, from the new state
        ensemble_maxima[cells](
            engine.h, engine.u, engine.v, h_max, v_max, t_arrival,
            t_sim, ARRIVAL_THRESHOLD_M, nonfinite, engine.active,
        )  # fmt: skip
        end_of_step[members](
            engine.active, step_count, t_sim, solver_duration_s, max_steps, nonfinite,
            snap_local, snap_times_dev, snap_time_out, snap_control,
        )  # fmt: skip
        if snap_local >= 0:
            copy_snapshot[frame_grid](engine.h, engine.u, engine.v, snap_local, snap_control, frame_buffer)

        steps += 1
        if steps % POLL_STEPS == 0:
            finished = engine.active.copy_to_host() == 0
            if on_member_done is not None:
                for _ in range(int(np.count_nonzero(finished & ~reported))):
                    on_member_done()
            reported |= finished
            running = not finished.all()

    # ---- collect ----
    h_all = engine.h.copy_to_host()[:, PAD : PAD + ny, PAD : PAD + nx]
    h_max_host = h_max.copy_to_host()
    v_max_host = v_max.copy_to_host()
    t_arrival_host = t_arrival.copy_to_host()
    t_sim_host = t_sim.copy_to_host()
    steps_host = step_count.copy_to_host()
    retries_host = retries.copy_to_host()
    overruns_host = overruns.copy_to_host()
    released_host = released.copy_to_host()
    exited_host = engine.exited.copy_to_host()
    nonfinite_host = nonfinite.copy_to_host()
    n_frames = int(snap_control.copy_to_host()[_COUNT]) if snap_local >= 0 else 0
    frames = frame_buffer.copy_to_host()[:n_frames] if n_frames else None
    frame_times = snap_time_out.copy_to_host()[:n_frames]
    cell_area = engine.cell_area

    results = []
    for k, (sample_id, _, _, metadata) in enumerate(batch):
        if on_member_done is not None and not reported[k]:
            on_member_done()
        if nonfinite_host[k]:
            results.append(
                {
                    "sample_id": sample_id,
                    "error": (
                        f"FloatingPointError: solution went non-finite by "
                        f"t={t_sim_host[k]:.1f}s (step {int(steps_host[k])})"
                    ),
                    "success": False,
                }
            )
            continue

        if steps_host[k] >= max_steps:
            warnings.warn(
                f"Member {sample_id} hit the {max_steps}-step safety cap at "
                f"t={t_sim_host[k]:.1f}s of {solver_duration_s:.1f}s — the timestep has "
                f"probably collapsed. Results are truncated, not converged.",
                stacklevel=2,
            )

        depth_series: List[Dict[str, Any]] = []
        if k == snap_local:
            if initial_frame is not None:
                depth_series.append(initial_frame)
            for f in range(n_frames):
                depth_series.append(
                    {
                        "time_s": float(frame_times[f]),
                        "depth": frames[f, 0].copy(),
                        "velocity_x": frames[f, 1].copy(),
                        "velocity_y": frames[f, 2].copy(),
                    }
                )

        h_final = h_all[k]
        results.append(
            {
                "sample_id": sample_id,
                "t_arrival": t_arrival_host[k].copy(),
                "h_max": h_max_host[k].copy(),
                "v_max": v_max_host[k].copy(),
                "metadata": metadata,
                "depth_series": depth_series,
                "n_steps": int(steps_host[k]),
                "t_end_s": float(t_sim_host[k]),
                "injection_step_retries": int(retries_host[k]),
                "injection_step_overruns": int(overruns_host[k]),
                "volume_released_m3": float(released_host[k]),
                "volume_exited_m3": float(exited_host[k]),
                "volume_retained_m3": float(h_final[h_final >= H_DRY_DEFAULT].sum()) * cell_area,
                "success": True,
            }
        )

    # Free this chunk's buffers before the next one is allocated; numba
    # otherwise defers deallocation and the next chunk can run out of memory.
    engine = h_max = v_max = t_arrival = frame_buffer = None
    cuda.current_context().deallocations.clear()
    return results
