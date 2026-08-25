"""
Near-Field SPH Domain & Particle Generation Module (Phase 7).

Generates Lagrangian fluid and boundary particle sets for near-field dam breach
hydrodynamics (e.g. 500m x 500m breach region).

Particle Properties:
  - x, y, z: Particle positions (m)
  - u, v, w: Particle velocities (m/s)
  - m: Particle mass (kg)
  - rho: Density (kg/m3, default 1000 kg/m3)
  - h_p: Smoothing length (m)
  - p: Pressure (Pa)
  - pid: Particle type (0 = fluid, 1 = solid boundary, 2 = inflow boundary)

References:
  - Ramachandran et al. (2021) "PySPH: A Python-based Framework for SPH", ACM TOMS.
"""

import numpy as np
from typing import Dict, Tuple, Optional


class NearFieldDomain:
    """Class representing near-field SPH particle domain around breach site."""

    def __init__(
        self,
        center_x: float,
        center_y: float,
        domain_size_m: float = 500.0,
        particle_spacing_m: float = 5.0,
        water_depth_m: float = 10.0,
        bed_elevation_m: float = 100.0,
    ):
        """
        Initialize SPH Near-Field particle domain.

        Args:
            center_x, center_y: Breach center coordinates in UTM (m)
            domain_size_m: Side length of near-field domain (m)
            particle_spacing_m: Initial particle spacing dx_p (m)
            water_depth_m: Initial water depth at reservoir breach side (m)
            bed_elevation_m: Mean bed elevation at breach (m)
        """
        self.center_x = center_x
        self.center_y = center_y
        self.domain_size_m = domain_size_m
        self.dx_p = particle_spacing_m
        self.water_depth = water_depth_m
        self.bed_elevation = bed_elevation_m

        self.num_fluid = 0
        self.num_boundary = 0

        # Arrays initialized in generate()
        self.x = np.array([], dtype=np.float32)
        self.y = np.array([], dtype=np.float32)
        self.z = np.array([], dtype=np.float32)
        self.u = np.array([], dtype=np.float32)
        self.v = np.array([], dtype=np.float32)
        self.w = np.array([], dtype=np.float32)
        self.m = np.array([], dtype=np.float32)
        self.rho = np.array([], dtype=np.float32)
        self.h_p = np.array([], dtype=np.float32)
        self.p = np.array([], dtype=np.float32)
        self.pid = np.array([], dtype=np.int32)

    def generate(self) -> Dict[str, np.ndarray]:
        """
        Generate fluid and boundary particle arrays.

        Returns:
            Dict containing numpy arrays for x, y, z, u, v, w, m, rho, h_p, p, pid
        """
        half_s = self.domain_size_m / 2.0
        dx = self.dx_p

        x_coords = np.arange(self.center_x - half_s, self.center_x + half_s, dx)
        y_coords = np.arange(self.center_y - half_s, self.center_y + half_s, dx)

        fluid_x, fluid_y, fluid_z = [], [], []
        bound_x, bound_y, bound_z = [], [], []

        # Generate fluid particles (reservoir side, above bed elevation)
        z_water_levels = np.arange(self.bed_elevation + dx, self.bed_elevation + self.water_depth + 0.1, dx)
        if len(z_water_levels) == 0:
            z_water_levels = np.array([self.bed_elevation + self.water_depth], dtype=np.float32)

        for z_w in z_water_levels:
            for y_p in y_coords:
                # Fluid on reservoir side (left half)
                for x_p in x_coords[x_coords < self.center_x]:
                    fluid_x.append(x_p)
                    fluid_y.append(y_p)
                    fluid_z.append(z_w)

        # Generate solid bed boundary particles (bottom layer)
        for y_p in y_coords:
            for x_p in x_coords:
                bound_x.append(x_p)
                bound_y.append(y_p)
                bound_z.append(self.bed_elevation - dx)

        num_f = len(fluid_x)
        num_b = len(bound_x)
        total_p = num_f + num_b

        self.num_fluid = num_f
        self.num_boundary = num_b

        # Particle mass calculation: m = rho * dx^3 (for 3D)
        rho_0 = 1000.0  # kg/m3
        particle_vol = dx**3
        m_0 = rho_0 * particle_vol
        h_0 = 1.3 * dx  # Smoothing length

        self.x = np.concatenate([fluid_x, bound_x]).astype(np.float32)
        self.y = np.concatenate([fluid_y, bound_y]).astype(np.float32)
        self.z = np.concatenate([fluid_z, bound_z]).astype(np.float32)

        self.u = np.zeros(total_p, dtype=np.float32)
        self.v = np.zeros(total_p, dtype=np.float32)
        self.w = np.zeros(total_p, dtype=np.float32)

        self.m = np.full(total_p, m_0, dtype=np.float32)
        self.rho = np.full(total_p, rho_0, dtype=np.float32)
        self.h_p = np.full(total_p, h_0, dtype=np.float32)
        self.p = np.zeros(total_p, dtype=np.float32)

        # Type IDs: 0 = fluid, 1 = boundary
        self.pid = np.concatenate([np.zeros(num_f, dtype=np.int32), np.ones(num_b, dtype=np.int32)])

        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "u": self.u,
            "v": self.v,
            "w": self.w,
            "m": self.m,
            "rho": self.rho,
            "h_p": self.h_p,
            "p": self.p,
            "pid": self.pid,
            "num_fluid": self.num_fluid,
            "num_boundary": self.num_boundary,
        }


def generate_near_field_particles(
    center_x: float,
    center_y: float,
    domain_size_m: float = 500.0,
    particle_spacing_m: float = 5.0,
    water_depth_m: float = 10.0,
) -> NearFieldDomain:
    """Convenience factory function to create and generate near-field particle domain."""
    domain = NearFieldDomain(
        center_x, center_y, domain_size_m, particle_spacing_m, water_depth_m
    )
    domain.generate()
    return domain
