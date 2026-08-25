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
  - η = water surface elevation (m) = b + h

State layout:
  State.h[i, j] = depth at cell (i, j)
  State.u[i, j] = x-velocity at cell (i, j)
  State.v[i, j] = y-velocity at cell (i, j)
"""

from dataclasses import dataclass
from typing import Tuple
import numpy as np


@dataclass
class Grid:
    """
    Cartesian grid definition for 2D SWE solver.

    Attributes:
        nx, ny: Number of cells in x, y directions (cell-centred)
        dx, dy: Cell dimensions (metres)
        x0, y0: Lower-left corner coordinates (metres, metric CRS)
        crs: Coordinate reference system (e.g., "EPSG:32643" for UTM 43N)
    """

    nx: int
    ny: int
    dx: float
    dy: float
    x0: float = 0.0
    y0: float = 0.0
    crs: str = "EPSG:32643"

    def cell_centres_x(self) -> np.ndarray:
        """X coordinates of cell centres (shape: [nx])."""
        return self.x0 + (np.arange(self.nx) + 0.5) * self.dx

    def cell_centres_y(self) -> np.ndarray:
        """Y coordinates of cell centres (shape: [ny])."""
        return self.y0 + (np.arange(self.ny) + 0.5) * self.dy

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
        """Validate state consistency."""
        if not (self.h.shape == self.u.shape == self.v.shape == self.b.shape):
            raise ValueError("All arrays must have the same shape")

        # Clean NaNs / Infs and ensure non-negative depths
        if np.any(np.isnan(self.h)) or np.any(np.isinf(self.h)):
            np.nan_to_num(self.h, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if np.any(np.isnan(self.u)) or np.any(np.isinf(self.u)):
            np.nan_to_num(self.u, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if np.any(np.isnan(self.v)) or np.any(np.isinf(self.v)):
            np.nan_to_num(self.v, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if np.any(np.isnan(self.b)) or np.any(np.isinf(self.b)):
            np.nan_to_num(self.b, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

        # Clamp all negative depths to 0.0
        if np.any(self.h < 0):
            self.h[self.h < 0] = 0.0

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
        """Water surface elevation (η = b + h)."""
        return self.b + self.h

    @property
    def volume(self) -> float:
        """Total water volume (m³)."""
        # Assume grid spacing is 1 m (will be scaled by dx*dy in caller)
        return np.sum(self.h)

    def copy(self):
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
    Simulation result snapshot.

    Attributes:
        t: Time (seconds)
        h_max: Maximum depth reached at each cell (metres)
        u_max: Maximum velocity magnitude at each cell (m/s)
        v_max: Maximum y-velocity magnitude at each cell (m/s)
        t_arrival: Time of first wetting at each cell (seconds since start)
        state: Final state (State object)
    """

    t: float
    h_max: np.ndarray  # shape: (ny, nx)
    u_max: np.ndarray  # shape: (ny, nx)
    v_max: np.ndarray  # shape: (ny, nx)
    t_arrival: np.ndarray  # shape: (ny, nx), filled with np.inf if never wet
    state: State

    @property
    def ny(self) -> int:
        """Number of rows."""
        return self.h_max.shape[0]

    @property
    def nx(self) -> int:
        """Number of columns."""
        return self.h_max.shape[1]


def create_state(
    grid: Grid,
    h_init: np.ndarray,
    u_init: np.ndarray = None,
    v_init: np.ndarray = None,
    b_init: np.ndarray = None,
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
    """
    ny, nx = grid.ny, grid.nx

    if h_init.shape != (ny, nx):
        raise ValueError(f"h_init shape {h_init.shape} doesn't match grid {(ny, nx)}")

    u = u_init if u_init is not None else np.zeros((ny, nx), dtype=np.float32)
    v = v_init if v_init is not None else np.zeros((ny, nx), dtype=np.float32)
    b = b_init if b_init is not None else np.zeros((ny, nx), dtype=np.float32)

    return State(
        h=h_init.astype(np.float32),
        u=u.astype(np.float32),
        v=v.astype(np.float32),
        b=b.astype(np.float32),
        t=0.0,
    )


def create_result(grid: Grid) -> Result:
    """
    Create a Result object initialized for accumulation.

    Args:
        grid: Grid definition

    Returns:
        Result with all max fields set to 0, t_arrival set to inf
    """
    ny, nx = grid.ny, grid.nx
    return Result(
        t=0.0,
        h_max=np.zeros((ny, nx), dtype=np.float32),
        u_max=np.zeros((ny, nx), dtype=np.float32),
        v_max=np.zeros((ny, nx), dtype=np.float32),
        t_arrival=np.full((ny, nx), np.inf, dtype=np.float32),
        state=create_state(grid, np.zeros((ny, nx))),
    )
