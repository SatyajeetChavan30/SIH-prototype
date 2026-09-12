"""
Device-resident SWE state and the per-step kernel sequence (CUDA backend).

One engine holds n_members independent solves on one grid. SWESolver drives it
with n_members=1; the batched ensemble (ensemble_cuda.py) drives it with one
member per breach hydrograph. There is one code path for both, so a single run
and an ensemble member cannot compute different physics on the GPU.

The kernel sequence of advance() mirrors SWESolver._advance exactly:

    ghosts -> faces -> assemble  -> stage 1 (combine, clip, velocity)
    ghosts -> faces -> assemble  -> stage 2 (combine, clip, velocity, friction)

Nothing here crosses to the host except where a caller explicitly asks, which
is what makes the device-resident loops in SWESolver.run and the ensemble fast.
"""

import numpy as np
from numba import cuda

from . import flux_cuda as kernels
from .types import DTYPE

PAD = kernels.PAD


def _zeros(shape, dtype=DTYPE):
    return cuda.to_device(np.zeros(shape, dtype=dtype))


class CudaSWEEngine:
    """
    Device buffers for n_members solves on one grid, plus the step kernels.

    Args:
        grid: solver Grid (metric CRS)
        bed: bed elevation, shape (ny, nx); shared by every member
        manning_field: Manning's n, shape (ny, nx); shared by every member
        n_members: number of independent solves held at once
        boundary: "transmissive" or "reflective"
        use_muscl, h_dry, velocity_max, cfl, dt_max: as SWESolver
    """

    # Float64 arrays per member, used to size batches against free VRAM:
    # padded (h, u, v, h1, u1, v1), interior (hu1, hv1, d_h, d_hu, d_hv),
    # and five face arrays per axis.
    PADDED_ARRAYS = 6
    INTERIOR_ARRAYS = 5
    FACE_ARRAYS_PER_AXIS = 5

    @classmethod
    def bytes_per_member(cls, ny: int, nx: int, extra_interior_arrays: int = 0) -> int:
        """Device bytes one member needs; callers add their own per-member arrays."""
        padded = (ny + 2 * PAD) * (nx + 2 * PAD)
        interior = ny * nx
        faces = ny * (nx + 1) + (ny + 1) * nx
        return 8 * (
            cls.PADDED_ARRAYS * padded
            + (cls.INTERIOR_ARRAYS + extra_interior_arrays) * interior
            + cls.FACE_ARRAYS_PER_AXIS * faces
            + ny  # row partial sums
        )

    def __init__(
        self,
        grid,
        bed: np.ndarray,
        manning_field: np.ndarray,
        n_members: int,
        *,
        boundary: str,
        use_muscl: bool,
        h_dry: float,
        velocity_max: float,
        cfl: float,
        dt_max: float,
    ):
        if boundary not in ("transmissive", "reflective"):
            raise ValueError(f"boundary must be 'transmissive' or 'reflective' (got {boundary!r})")

        self.ny, self.nx = int(grid.ny), int(grid.nx)
        self.dx, self.dy = float(grid.dx), float(grid.dy)
        self.cell_area = self.dx * self.dy
        self.n_members = int(n_members)
        self.use_muscl = bool(use_muscl)
        self.h_dry = float(h_dry)
        self.velocity_max = float(velocity_max)
        self.cfl = float(cfl)
        self.dt_max = float(dt_max)

        # Same rules as SWESolver: a one-cell-thick direction is inactive and
        # its ghosts are always mirrored.
        self.active_x = self.nx > 1
        self.active_y = self.ny > 1
        self.reflect_x = boundary == "reflective" or not self.active_x
        self.reflect_y = boundary == "reflective" or not self.active_y

        m, ny, nx = self.n_members, self.ny, self.nx
        padded = (m, ny + 2 * PAD, nx + 2 * PAD)
        interior = (m, ny, nx)

        self.h, self.u, self.v = _zeros(padded), _zeros(padded), _zeros(padded)
        self.h1, self.u1, self.v1 = _zeros(padded), _zeros(padded), _zeros(padded)
        self.hu1, self.hv1 = _zeros(interior), _zeros(interior)
        self.d_h, self.d_hu, self.d_hv = _zeros(interior), _zeros(interior), _zeros(interior)
        # (mass, xmom, ymom, corr_left, corr_right) per axis
        self.faces_x = tuple(_zeros((m, ny, nx + 1)) for _ in range(5))
        self.faces_y = tuple(_zeros((m, ny + 1, nx)) for _ in range(5))

        self.bed = None
        self.set_bed(bed)
        self.manning = cuda.to_device(np.ascontiguousarray(manning_field, dtype=DTYPE))

        self.inv_dt = _zeros(m)
        self.dt = _zeros(m)
        self.n_capped = _zeros(m, np.int64)
        self.row_partial = _zeros((m, ny))
        self.sum_before = _zeros(m)
        self.sum_after = _zeros(m)
        self.exited = _zeros(m)
        self.active = cuda.to_device(np.ones(m, dtype=np.int32))

        # Launch configurations, bound once: rebinding every launch is pure
        # Python overhead on a loop that runs hundreds of thousands of times.
        cells = kernels.launch_grid(nx, ny, m)
        members = ((m + 127) // 128, 128)
        self._launch = {
            "ghost_x": kernels.fill_ghosts_x[(1, (ny + 63) // 64, m), (PAD, 64, 1)],
            "ghost_y": kernels.fill_ghosts_y[((nx + 63) // 64, 1, m), (64, PAD, 1)],
            "face_x": kernels.face_flux_x[kernels.launch_grid(nx + 1, ny, m)],
            "face_y": kernels.face_flux_y[kernels.launch_grid(nx, ny + 1, m)],
            "assemble": kernels.assemble_tendencies[cells],
            "stage1": kernels.rk_stage1[cells],
            "stage2": kernels.rk_stage2_friction[cells],
            "inverse_dt": kernels.inverse_dt_cells[cells],
            "finalize_dt": kernels.finalize_dt[members],
            "row_sums": kernels.row_sums[((ny + 127) // 128, m), (128, 1)],
            "member_sums": kernels.member_sums[members],
            "outflow": kernels.accumulate_outflow[members],
            "run_maxima": kernels.run_maxima[((nx + 31) // 32, (ny + 7) // 8), (32, 8)],
        }

    # ------------------------------------------------------------------
    # Host <-> device
    # ------------------------------------------------------------------

    def _pad(self, interior: np.ndarray) -> np.ndarray:
        padded = np.zeros((self.ny + 2 * PAD, self.nx + 2 * PAD), dtype=DTYPE)
        padded[PAD : PAD + self.ny, PAD : PAD + self.nx] = interior
        return padded

    def set_bed(self, bed: np.ndarray) -> None:
        """Upload the bed with its ghost ring filled by the CPU's own rules."""
        from .core import fill_ghost_ring  # core imports this module lazily

        padded = self._pad(bed)
        scratch = np.zeros_like(padded)
        fill_ghost_ring(
            scratch, scratch, scratch, padded, self.nx, self.ny, self.reflect_x, self.reflect_y
        )
        self.bed = cuda.to_device(padded)

    def set_member_state(self, member: int, h, u, v) -> None:
        """Upload one member's interior (h, u, v)."""
        for device_array, host in ((self.h, h), (self.u, u), (self.v, v)):
            device_array[member].copy_to_device(self._pad(host))

    def set_all_states(self, h, u, v) -> None:
        """Upload the same interior (h, u, v) to every member in one transfer each."""
        shape = (self.n_members, self.ny + 2 * PAD, self.nx + 2 * PAD)
        for device_array, host in ((self.h, h), (self.u, u), (self.v, v)):
            device_array.copy_to_device(np.ascontiguousarray(np.broadcast_to(self._pad(host), shape)))

    def member_state(self, member: int):
        """Download one member's interior (h, u, v) as fresh float64 arrays."""
        interior = (slice(PAD, PAD + self.ny), slice(PAD, PAD + self.nx))
        return tuple(
            device_array[member].copy_to_host()[interior].copy()
            for device_array in (self.h, self.u, self.v)
        )

    def set_dt(self, value: float, member: int = 0) -> None:
        self.dt[member : member + 1].copy_to_device(np.array([value], dtype=DTYPE))

    def take_capped(self, member: int = 0) -> int:
        """Velocity-cap activations since the last call, then reset to zero."""
        count = int(self.n_capped.copy_to_host()[member])
        self.n_capped[member : member + 1].copy_to_device(np.zeros(1, dtype=np.int64))
        return count

    def take_exited(self, member: int = 0) -> float:
        """Boundary outflow (m^3) accumulated since the last call, then reset."""
        volume = float(self.exited.copy_to_host()[member])
        self.exited[member : member + 1].copy_to_device(np.zeros(1, dtype=DTYPE))
        return volume

    # ------------------------------------------------------------------
    # Step sequence
    # ------------------------------------------------------------------

    def _tendencies(self, h, u, v) -> None:
        launch = self._launch
        launch["ghost_x"](h, u, v, self.reflect_x, self.active)
        launch["ghost_y"](h, u, v, self.reflect_y, self.active)
        if self.active_x:
            launch["face_x"](h, u, v, self.bed, *self.faces_x, self.use_muscl, self.h_dry, self.active)
        if self.active_y:
            launch["face_y"](h, u, v, self.bed, *self.faces_y, self.use_muscl, self.h_dry, self.active)
        launch["assemble"](
            h,
            self.bed,
            *self.faces_x,
            *self.faces_y,
            self.d_h,
            self.d_hu,
            self.d_hv,
            self.dx,
            self.dy,
            self.use_muscl,
            self.active_x,
            self.active_y,
            self.active,
        )

    def advance(self, dt_device) -> None:
        """One SSP-RK2 step plus friction for every active member, with per-member dt."""
        launch = self._launch
        self._tendencies(self.h, self.u, self.v)
        launch["stage1"](
            self.h, self.u, self.v,
            self.d_h, self.d_hu, self.d_hv,
            self.h1, self.u1, self.v1, self.hu1, self.hv1,
            dt_device, self.h_dry, self.active,
        )  # fmt: skip
        self._tendencies(self.h1, self.u1, self.v1)
        launch["stage2"](
            self.h, self.u, self.v,
            self.h1, self.hu1, self.hv1,
            self.d_h, self.d_hu, self.d_hv,
            self.manning, dt_device, self.h_dry, self.velocity_max, self.n_capped, self.active,
        )  # fmt: skip

    def total_depth(self, out) -> None:
        """Sum of interior depth per member, into `out` (device, length n_members)."""
        self._launch["row_sums"](self.h, self.row_partial, self.active)
        self._launch["member_sums"](self.row_partial, out, self.active)

    def advance_with_outflow(self, dt_device) -> None:
        """advance(), and add the volume that left through the boundary to `exited`."""
        self.total_depth(self.sum_before)
        self.advance(dt_device)
        self.total_depth(self.sum_after)
        self._launch["outflow"](self.sum_before, self.sum_after, self.exited, self.cell_area, self.active)

    def compute_dt(self, out) -> None:
        """CFL timestep of every active member, into `out` (device)."""
        self._launch["inverse_dt"](
            self.h, self.u, self.v, self.bed, self.inv_dt,
            self.dx, self.dy, self.active_x, self.active_y, self.h_dry, self.active,
        )  # fmt: skip
        self._launch["finalize_dt"](self.inv_dt, out, self.cfl, self.dt_max, self.active)

    # ------------------------------------------------------------------
    # Running maxima for SWESolver.run (member 0)
    # ------------------------------------------------------------------

    def load_run_maxima(self, result) -> None:
        self.run_h_max = cuda.to_device(result.h_max)
        self.run_u_max = cuda.to_device(result.u_max)
        self.run_v_max = cuda.to_device(result.v_max)
        self.run_t_arrival = cuda.to_device(result.t_arrival)
        self.run_nonfinite = _zeros(1, np.int32)

    def update_run_maxima(self, t_now: float, wet_threshold: float) -> None:
        self._launch["run_maxima"](
            self.h, self.u, self.v,
            self.run_h_max, self.run_u_max, self.run_v_max, self.run_t_arrival,
            t_now, wet_threshold, self.run_nonfinite,
        )  # fmt: skip

    def run_went_nonfinite(self) -> bool:
        return bool(self.run_nonfinite.copy_to_host()[0])

    def read_run_maxima(self, result) -> None:
        result.h_max[...] = self.run_h_max.copy_to_host()
        result.u_max[...] = self.run_u_max.copy_to_host()
        result.v_max[...] = self.run_v_max.copy_to_host()
        result.t_arrival[...] = self.run_t_arrival.copy_to_host()
