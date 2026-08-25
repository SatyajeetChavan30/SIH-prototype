"""
Parallel Ensemble Execution Engine (Phase 12: Optimization).

Executes Monte Carlo hydrograph ensemble members in parallel across CPU cores
using ProcessPoolExecutor.

References:
  Spec §12: Parallelization & Performance Optimization
"""

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional
import numpy as np


def run_single_ensemble_member_task(args: Tuple) -> Dict:
    """Worker task function for running solver on a single ensemble member."""
    sample_id, hydrograph, grid_dict, manning_val, solver_duration_s, i_breach, j_breach = args

    try:
        from jalraksha.solver.types import Grid, create_state
        from jalraksha.solver.core import SWESolver

        grid = Grid(
            nx=grid_dict["nx"],
            ny=grid_dict["ny"],
            dx=grid_dict["dx"],
            dy=grid_dict["dy"],
            x0=grid_dict.get("x0", 0.0),
            y0=grid_dict.get("y0", 0.0),
        )

        z = np.asarray(grid_dict.get("z", np.zeros((grid.ny, grid.nx))), dtype=np.float32)
        h = np.zeros((grid.ny, grid.nx), dtype=np.float32)
        state = create_state(grid, h_init=h, b_init=z)

        solver = SWESolver(grid, manning_n=manning_val, cfl=0.9)

        t_sim = 0.0
        dt = solver.compute_cfl_timestep(state)

        t_arrival = np.full((grid.ny, grid.nx), np.inf, dtype=np.float32)
        h_max = np.zeros((grid.ny, grid.nx), dtype=np.float32)

        t_hydro = hydrograph["t_array"]
        q_hydro = hydrograph["Q_t"]

        step_count = 0
        max_steps = int(solver_duration_s / max(0.1, dt)) + 1

        while t_sim < solver_duration_s and step_count < max_steps:
            # Simple injection at breach cell
            idx = np.searchsorted(t_hydro, t_sim)
            q_curr = float(q_hydro[idx]) if idx < len(q_hydro) else 0.0

            if q_curr > 0:
                state.u[j_breach, i_breach] = q_curr / (max(0.1, state.h[j_breach, i_breach]) * grid.dx)

            state = solver.step(state)
            t_sim += dt
            dt = solver.compute_cfl_timestep(state)

            wet = (state.h >= 0.1) & (t_arrival == np.inf)
            t_arrival[wet] = t_sim
            h_max = np.maximum(h_max, state.h)
            step_count += 1

        return {
            "sample_id": sample_id,
            "t_arrival": t_arrival,
            "h_max": h_max,
            "success": True,
        }
    except Exception as e:
        return {
            "sample_id": sample_id,
            "error": str(e),
            "success": False,
        }


def run_ensemble_parallel(
    hydrographs: List[Dict],
    grid_dict: Dict,
    manning_val: float = 0.03,
    solver_duration_s: float = 3600.0,
    i_breach: int = 5,
    j_breach: int = 5,
    num_workers: Optional[int] = None,
) -> List[Dict]:
    """
    Run full hydrograph ensemble sequentially or in parallel.

    Args:
        hydrographs: List of hydrograph dicts from synthesize_breach_ensemble()
        grid_dict: Serialized grid dict
        manning_val: Manning's n value
        solver_duration_s: Simulation duration (s)
        i_breach, j_breach: Breach grid cell indices
        num_workers: Number of parallel CPU workers (default: os.cpu_count())

    Returns:
        List of result dicts for completed ensemble members
    """
    if num_workers is None:
        num_workers = min(4, os.cpu_count() or 1)

    tasks = [
        (sample_id, h, grid_dict, manning_val, solver_duration_s, i_breach, j_breach)
        for sample_id, h in enumerate(hydrographs)
    ]

    results = []
    if num_workers > 1:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(run_single_ensemble_member_task, task) for task in tasks]
            for future in as_completed(futures):
                res = future.result()
                if res.get("success"):
                    results.append(res)
    else:
        for task in tasks:
            res = run_single_ensemble_member_task(task)
            if res.get("success"):
                results.append(res)

    return results
