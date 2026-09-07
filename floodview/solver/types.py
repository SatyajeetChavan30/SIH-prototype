"""
Type definitions and data structures for JalRaksha 2D SWE solver.

Phase 1 responsibility: Define Grid, State, and Result classes
to standardize data flow between solver components.

Conventions:
  - All quantities in metric units (m, s, m/s, kg/m³)
  - Cell-centred finite volume on uniform Cartesian grid
  - h = water depth (m, always >= 0)
  - u, v = depth-averaged velocities (m/s)
  - b = bed elevation (m, fixed)
  - eta = water surface elevation (m) = b + h

Precision policy (IMPORTANT):
  All solver arrays are float64. This is not negotiable and is not a
  performance oversight. The blocking lake-at-rest gate requires the
  water-surface elevation to be preserved to <1e-6 m over 1000 steps.
  For a reservoir surface at eta ~ 10-2000 m, float32 (~1e-7 relative,
  i.e. ~1e-4 m absolute at eta=1000 m) cannot represent that gate even
  with a perfectly well-balanced scheme. Storage is halved by casting
  only at export time (see jalraksha.export.geotiff).

State layout:
  State.h[j, i] = depth at cell (row j, column i)
  State.u[j, i] = x-velocity at cell (row j, column i)
  State.v[j, i] = y-velocity at cell (row j, column i)
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

# Solver working precision. See "Precision policy" in the module docstring.
DTYPE = np.float64


@dataclass
class Grid:
    """
    Cartesian grid definition for 2D SWE solver.

    Attributes:
        nx, ny: Number of cells in x, y directions (cell-centred)
        dx, dy: Cell dimensions (metres)
        x0, y0: Lower-left corner coordinates (metres, metric CRS)
        crs: Coordinate reference system (e.g., "EPSG:32643" for UTM 43N)

    Note: the solver operates exclusively in a metric CRS. Passing a
    geographic CRS (degrees) will silently produce nonsense because dx/dy
    are treated as metres in the flux divergence.
    """

    nx: int
    ny: int
    dx: float
    dy: float
    x0: float = 0.0
    y0: float = 0.0
    crs: str = "EPSG:32643"

    def __post_init__(self):
        if self.nx < 1 or self.ny < 1:
            raise ValueError(f"Grid must have nx, ny >= 1 (got {self.nx}, {self.ny})")
        if self.dx <= 0 or self.dy <= 0:
            raise ValueError(f"Grid spacing must be positive (got {self.dx}, {self.dy})")

    @property
    def area(self) -> float:
        """Cell area (m²)."""
        return self.dx * self.dy

    @property
    def shape(self) -> Tuple[int, int]:
        """Array shape (ny, nx) — row-major, matching raster convention."""
        return (self.ny, self.nx)

    def cell_centres_x(self) -> np.ndarray:
        """X coordinates of cell centres (shape: [nx])."""
        return self.x0 + (np.arange(self.nx, dtype=DTYPE) + 0.5) * self.dx

    def cell_centres_y(self) -> np.ndarray:
        """Y coordinates of cell centres (shape: [ny])."""
        return self.y0 + (np.arange(self.ny, dtype=DTYPE) + 0.5) * self.dy

    def cell_centres_2d(self) -> Tuple[np.ndarray, np.ndarray]:
        """2D meshgrid of cell centre coordinates (shape: [ny, nx] each)."""
        xx, yy = np.meshgrid(self.cell_centres_x(), self.cell_centres_y())
        return xx, yy

    def extent(self) -> Tuple[float, float, float, float]:
        """Bounding box (x_min, x_max, y_min, y_max)."""
        return (
            self.x0,
            self.x0 + self.nx * self.dx,
            self.y0,
            self.y0 + self.ny * self.dy,
        )


@dataclass
class State:
    """
    Hydrodynamic state for 2D SWE solver.

    Attributes:
        h: Water depth array (shape: [ny, nx], metres, h >= 0)
        u: X-velocity array (shape: [ny, nx], m/s)
        v: Y-velocity array (shape: [ny, nx], m/s)
        b: Bed elevation array (shape: [ny, nx], metres, fixed)
        t: Current simulation time (seconds)
    """

    h: np.ndarray  # shape: (ny, nx)
    u: np.ndarray  # shape: (ny, nx)
    v: np.ndarray  # shape: (ny, nx)
    b: np.ndarray  # shape: (ny, nx)
    t: float = 0.0

    def __post_init__(self):
        """Validate shape consistency and enforce float64 contiguous arrays."""
        if not (self.h.shape == self.u.shape == self.v.shape == self.b.shape):
            raise ValueError(
                "All state arrays must have the same shape "
                f"(h={self.h.shape}, u={self.u.shape}, v={self.v.shape}, b={self.b.shape})"
            )

        # Enforce the precision policy and C-contiguity (numba kernels assume both).
        self.h = np.ascontiguousarray(self.h, dtype=DTYPE)
        self.u = np.ascontiguousarray(self.u, dtype=DTYPE)
        self.v = np.ascontiguousarray(self.v, dtype=DTYPE)
        self.b = np.ascontiguousarray(self.b, dtype=DTYPE)

        # Sanitise non-finite inputs. A NaN in the DEM (Copernicus voids over
        # water bodies) would otherwise poison the whole domain on step 1.
        np.nan_to_num(self.h, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        np.nan_to_num(self.u, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        np.nan_to_num(self.v, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        np.nan_to_num(self.b, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

        # Depth is physically non-negative.
        np.clip(self.h, 0.0, None, out=self.h)

    @property
    def ny(self) -> int:
        """Number of rows (y-cells)."""
        return self.h.shape[0]

    @property
    def nx(self) -> int:
        """Number of columns (x-cells)."""
        return self.h.shape[1]

    @property
    def eta(self) -> np.ndarray:
        """Water surface elevation (eta = b + h)."""
        return self.b + self.h

    @property
    def volume(self) -> float:
        """
        Summed depth over all cells (m).

        NOTE: this is deliberately *not* a volume in m³ — it is sum(h).
        Multiply by grid.area (dx*dy) to obtain m³. Kept in this form
        because State has no knowledge of its Grid.
        """
        return float(np.sum(self.h))

    @property
    def speed(self) -> np.ndarray:
        """Velocity magnitude sqrt(u² + v²) (m/s)."""
        return np.sqrt(self.u * self.u + self.v * self.v)

    @property
    def froude(self) -> np.ndarray:
        """
        Froude number |V| / sqrt(g*h), zero where dry.

        Fr > 1 indicates supercritical flow — expected in the near field of a
        breach and in steep gorge reaches such as the Bhagirathi below Tehri.
        """
        g = 9.81
        denom = np.sqrt(np.maximum(g * self.h, 1e-12))
        return np.where(self.h > 1e-3, self.speed / denom, 0.0)

    def is_finite(self) -> bool:
        """True if no NaN/Inf has entered the solution."""
        return bool(
            np.all(np.isfinite(self.h))
            and np.all(np.isfinite(self.u))
            and np.all(np.isfinite(self.v))
        )

    def copy(self) -> "State":
        """Return a deep copy of the state."""
        return State(
            h=self.h.copy(),
            u=self.u.copy(),
            v=self.v.copy(),
            b=self.b.copy(),
            t=self.t,
        )


@dataclass
class Result:
    """
    Running-maxima simulation result.

    These are the Tier-1 deliverable rasters. Per the DEM-resolution caveat
    (30 m Copernicus GLO-30), t_arrival and the inundation envelope derived
    from h_max are the defensible products; point values of h_max are
    indicative only.

    Attributes:
        t: Time of last update (seconds)
        h_max: Maximum depth reached at each cell (metres)
        u_max: Maximum velocity magnitude at each cell (m/s)
        v_max: Maximum y-velocity magnitude at each cell (m/s)
        t_arrival: Time of first wetting at each cell (s), np.inf if never wet
        state: Final state (State object)
        hazard_max: Maximum FD2320 hazard rating d*(v+0.5) at each cell
        mass_error: Relative volume error over the run (dimensionless)
        n_steps: Number of timesteps taken
    """

    t: float
    h_max: np.ndarray  # shape: (ny, nx)
    u_max: np.ndarray  # shape: (ny, nx)
    v_max: np.ndarray  # shape: (ny, nx)
    t_arrival: np.ndarray  # shape: (ny, nx), np.inf if never wet
    state: State
    hazard_max: Optional[np.ndarray] = None
    mass_error: float = 0.0
    n_steps: int = 0

    @property
    def ny(self) -> int:
        """Number of rows."""
        return self.h_max.shape[0]

    @property
    def nx(self) -> int:
        """Number of columns."""
        return self.h_max.shape[1]

    @property
    def wet_mask(self) -> np.ndarray:
        """
        Boolean inundation envelope at the Tier-1 reporting threshold.

        0.05 m is used rather than the solver's numerical h_dry (1e-3 m) so
        that the published envelope is not sensitive to the wetting-front
        tolerance. A 5 cm sheet is below any damage threshold in the
        depth-damage curves but is a defensible "was wet" criterion.
        """
        return self.h_max > 0.05

    def update(self, state: State, hazard: Optional[np.ndarray] = None) -> None:
        """
        Fold a state into the running maxima.

        Args:
            state: Current solver state
            hazard: Optional pre-computed FD2320 hazard field
        """
        np.maximum(self.h_max, state.h, out=self.h_max)
        speed = state.speed
        np.maximum(self.u_max, speed, out=self.u_max)
        np.maximum(self.v_max, np.abs(state.v), out=self.v_max)

        # First-wetting time. Only cells crossing the threshold *now* and not
        # previously recorded get stamped, so t_arrival is a true first-arrival.
        newly_wet = (state.h > 0.05) & ~np.isfinite(self.t_arrival)
        self.t_arrival[newly_wet] = state.t

        if hazard is not None:
            if self.hazard_max is None:
                self.hazard_max = np.zeros_like(self.h_max)
            np.maximum(self.hazard_max, hazard, out=self.hazard_max)

        self.t = state.t


def create_state(
    grid: Grid,
    h_init: np.ndarray,
    u_init: Optional[np.ndarray] = None,
    v_init: Optional[np.ndarray] = None,
    b_init: Optional[np.ndarray] = None,
) -> State:
    """
    Create a State object with given initial conditions.

    Args:
        grid: Grid definition
        h_init: Initial depth array (shape: [ny, nx])
        u_init: Initial x-velocity (default: zeros)
        v_init: Initial y-velocity (default: zeros)
        b_init: Bed elevation (default: zeros)

    Returns:
        State object ready for simulation

    Raises:
        ValueError: if h_init does not match the grid shape
    """
    ny, nx = grid.ny, grid.nx

    h_init = np.asarray(h_init)
    if h_init.shape != (ny, nx):
        raise ValueError(f"h_init shape {h_init.shape} doesn't match grid {(ny, nx)}")

    zeros = np.zeros((ny, nx), dtype=DTYPE)
    return State(
        h=h_init,
        u=zeros.copy() if u_init is None else u_init,
        v=zeros.copy() if v_init is None else v_init,
        b=zeros.copy() if b_init is None else b_init,
        t=0.0,
    )


def create_result(grid: Grid, state: Optional[State] = None) -> Result:
    """
    Create a Result object initialized for accumulation.

    Args:
        grid: Grid definition
        state: Optional initial state to attach (default: dry state)

    Returns:
        Result with all max fields set to 0 and t_arrival set to inf
    """
    ny, nx = grid.ny, grid.nx
    if state is None:
        state = create_state(grid, np.zeros((ny, nx), dtype=DTYPE))

    return Result(
        t=0.0,
        h_max=np.zeros((ny, nx), dtype=DTYPE),
        u_max=np.zeros((ny, nx), dtype=DTYPE),
        v_max=np.zeros((ny, nx), dtype=DTYPE),
        t_arrival=np.full((ny, nx), np.inf, dtype=DTYPE),
        state=state,
    )
